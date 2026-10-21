# Pop!_OS COSMIC Capture Freeze Fix

Fixes screen and window capture freezing caused by COSMIC's `duplicate_frame` protocol error.

## Install

Close active screen captures and file dialogs, then run:

```sh
curl -fsSL https://raw.githubusercontent.com/MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix/v1.1.0/install.sh | /bin/bash
```

The installer selects the matching prebuilt executable, verifies its checksum and system libraries, backs up the original, and restarts the portal service. Enter the sudo password when prompted, then start a new capture session. No compilation or reboot is required.

## Compatibility

Pop!_OS 24.04 with COSMIC on x86-64. Supported `xdg-desktop-portal-cosmic` package versions:

| Portal package | Prebuilt executable |
| --- | --- |
| `1.10.0~1791324839~24.04~9d35e63` | Original verified 1.10.0 build |
| `1.11.0~1792525517~24.04~f448ddf` | Matching 1.11.0 build |

The installer detects the installed portal package, independently of the compositor version. Unsupported packages are left unchanged. The capture-library fix is GPU-independent.

## Backup and restore

Only `/usr/libexec/xdg-desktop-portal-cosmic` is replaced. The service `org.freedesktop.impl.portal.desktop.cosmic.service` is restarted and its running executable is verified. Failed startup verification triggers restoration of the original.

Backups and an offline restore helper are retained under `${XDG_STATE_HOME:-$HOME/.local/state}/pop-os-cosmic-capture-freeze-fix`. Each supported package version has its own backup. Backups made by v1.0.0 are recognized and preserved. Temporary downloads are removed automatically.

Restore the original for the currently installed package:

```sh
/usr/bin/python3 "${XDG_STATE_HOME:-$HOME/.local/state}/pop-os-cosmic-capture-freeze-fix/install.py" --uninstall
```

Backups survive reboots and are retained after restoration. The helper refuses to restore an older package's executable over a newer package. Regular package updates remain enabled. Other packages, drivers, compositor files, and system configuration are unchanged.

## Source and builds

[fix.patch](fix.patch) moves frame destruction before the completion callbacks in `client-toolkit/src/screencopy/dispatch.rs`. This queues destruction before a callback can wake a consumer that requests the next frame.

- [Patched capture library](https://github.com/MagnetosphereLabs/cosmic-protocols/tree/3ad1781fefeaea5224ec6917f53ccad32bf5219b).
- [Portal 1.11.0 source](https://github.com/pop-os/xdg-desktop-portal-cosmic/tree/f448ddfb296bf7bb23517b24b2f532559a334a1c).
- [Portal 1.10.0 source](https://github.com/pop-os/xdg-desktop-portal-cosmic/tree/9d35e6300b69cf06da723a502a9a56604a022786).
- [Release build information](builds.json), [build instructions](build/README.md), and [source archive](https://github.com/MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix/releases/download/v1.1.0/source.zip).

Builds verify that the original fails both wire-order regression tests, the patch passes both, and unrelated locked dependencies remain unchanged. Build reports and SHA256 checksums accompany releases. Screen-capture testing on a target desktop is required before publishing a candidate release.

This is an unofficial downstream release. The portal and installer are distributed under [GPL-3.0-or-later](LICENSE); the modified capture library retains its [MIT license](LICENSE-MIT).
