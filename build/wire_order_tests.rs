use super::*;
use crate::screencopy::{
    CaptureSessionInner, FailureReason, Formats, Frame, ScreencopyFrameData,
};
use std::io::Read;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use wayland_client::protocol::wl_registry;
use wayland_client::{delegate_dispatch, Proxy};

type RawSession = ext_image_copy_capture_session_v1::ExtImageCopyCaptureSessionV1;
type RawFrame = ext_image_copy_capture_frame_v1::ExtImageCopyCaptureFrameV1;

struct App {
    session: CaptureSession,
    next_frame: Option<RawFrame>,
    callbacks: usize,
}

impl App {
    fn next(&mut self, frame: &CaptureFrame, qh: &QueueHandle<Self>) {
        // The portal accesses this data when its completion callback wakes a consumer.
        assert!(frame.data::<ScreencopyFrameData>().is_some());
        assert_eq!(frame.session::<ScreencopyFrameData>(), Some(self.session.clone()));
        let data = ScreencopyFrameData::default();
        assert!(data.session.set(Arc::downgrade(&self.session.0)).is_ok());
        self.next_frame = Some(self.session.0.session.create_frame(qh, data));
        self.callbacks += 1;
    }
}

impl ScreencopyHandler for App {
    fn screencopy_state(&mut self) -> &mut ScreencopyState {
        unreachable!("the frame dispatcher does not need a global registry state")
    }

    fn init_done(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        _: &CaptureSession,
        _: &Formats,
    ) {
        unreachable!()
    }

    fn stopped(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &CaptureSession) {
        unreachable!()
    }

    fn ready(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        frame: &CaptureFrame,
        _: Frame,
    ) {
        self.next(frame, qh);
    }

    fn failed(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        frame: &CaptureFrame,
        _: WEnum<FailureReason>,
    ) {
        self.next(frame, qh);
    }
}

impl Dispatch<wl_registry::WlRegistry, ()> for App {
    fn event(
        _: &mut Self,
        _: &wl_registry::WlRegistry,
        _: wl_registry::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        unreachable!()
    }
}

impl Dispatch<RawSession, ()> for App {
    fn event(
        _: &mut Self,
        _: &RawSession,
        _: ext_image_copy_capture_session_v1::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        unreachable!()
    }
}

delegate_dispatch!(App: [RawFrame: ScreencopyFrameData] => ScreencopyState);

fn request(peer: &mut UnixStream) -> (u32, u16) {
    let mut header = [0_u8; 8];
    peer.read_exact(&mut header).unwrap();
    let object = u32::from_ne_bytes(header[..4].try_into().unwrap());
    let word = u32::from_ne_bytes(header[4..].try_into().unwrap());
    let size = (word >> 16) as usize;
    assert!(size >= 8 && size % 4 == 0);
    let mut body = vec![0_u8; size - 8];
    peer.read_exact(&mut body).unwrap();
    (object, word as u16)
}

fn completion(failed: bool) {
    let (socket, mut peer) = UnixStream::pair().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
    let conn = Connection::from_socket(socket).unwrap();
    let queue = conn.new_event_queue::<App>();
    let qh = queue.handle();

    // A recording peer is sufficient: no compositor or display hardware is needed.
    // Bind a synthetic session global so the real client library allocates proxies.
    let registry = conn.display().get_registry(&qh, ());
    let raw: RawSession = registry.bind(1, 1, &qh, ());
    let session = CaptureSession(Arc::new(CaptureSessionInner { session: raw }));
    let data = ScreencopyFrameData::default();
    assert!(data.session.set(Arc::downgrade(&session.0)).is_ok());
    let first = session.0.session.create_frame(&qh, data);
    let first_id = first.id().protocol_id();
    let session_id = session.0.session.id().protocol_id();
    let mut app = App { session, next_frame: None, callbacks: 0 };

    conn.flush().unwrap();
    // get_registry, registry.bind, and the initial create_frame.
    for _ in 0..3 {
        request(&mut peer);
    }

    let event = if failed {
        ext_image_copy_capture_frame_v1::Event::Failed {
            reason: WEnum::Value(FailureReason::BufferConstraints),
        }
    } else {
        ext_image_copy_capture_frame_v1::Event::Ready
    };
    <ScreencopyState as Dispatch<RawFrame, ScreencopyFrameData, App>>::event(
        &mut app,
        &first,
        event,
        first.data::<ScreencopyFrameData>().unwrap(),
        &conn,
        &qh,
    );
    conn.flush().unwrap();
    assert_eq!(app.callbacks, 1);
    assert!(app.next_frame.is_some());
    assert_eq!(
        request(&mut peer),
        (first_id, 0),
        "destroy request must precede the next create_frame"
    );
    assert_eq!(request(&mut peer), (session_id, 0));
}

#[test]
fn ready_releases_frame_before_reentrant_capture() {
    completion(false);
}

#[test]
fn failed_releases_frame_before_reentrant_capture() {
    completion(true);
}
