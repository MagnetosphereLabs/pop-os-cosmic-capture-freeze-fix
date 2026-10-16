# Pop!_OS COSMIC Capture Freeze Fix

Fixes whole-monitor screen capture freezing caused by the `duplicate_frame` protocol error in COSMIC's screen capture client.

## Install

Close active screen captures and file dialogs, then run:

```sh
curl -fsSL https://raw.githubusercontent.com/MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix/v1.0.0/install.sh | /bin/bash
```

The installer checks compatibility, downloads the prebuilt executable, backs up the original, installs the fix, and restarts the portal service. Enter the sudo password when prompted. Start a new capture session afterward; no reboot is required.

## Compatibility

- Pop!_OS 24.04 with COSMIC, x86-64.
- `xdg-desktop-portal-cosmic` package version `1.10.0~1791324839~24.04~9d35e63`.

The fix addresses GPU-independent capture code. The [upstream bug report](https://github.com/pop-os/xdg-desktop-portal-cosmic/issues/384) includes Intel, AMD, and NVIDIA systems. The installer verifies the package version and system libraries before replacement.

## Scope

The only installed file replaced is `/usr/libexec/xdg-desktop-portal-cosmic`. The installer restarts `org.freedesktop.impl.portal.desktop.cosmic.service` to load it and verifies the running executable. If startup verification fails, it restores the original automatically.

The original executable and an offline restore helper are saved under `${XDG_STATE_HOME:-$HOME/.local/state}/pop-os-cosmic-capture-freeze-fix`. Temporary downloads are removed automatically. No other packages, drivers, compositor files, or system configuration are changed. Regular package updates remain enabled.

## Uninstall

```sh
/usr/bin/python3 "${XDG_STATE_HOME:-$HOME/.local/state}/pop-os-cosmic-capture-freeze-fix/install.py" --uninstall
```

This restores the original executable and restarts the portal. The backup is retained in `${XDG_STATE_HOME:-$HOME/.local/state}/pop-os-cosmic-capture-freeze-fix/backup`.

## Source

[fix.patch](fix.patch) moves frame destruction before the completion callbacks in `client-toolkit/src/screencopy/dispatch.rs`. This prevents a new capture frame from being requested while the previous frame still exists.

- [Capture library source](https://github.com/pop-os/cosmic-protocols/tree/c0cff4db14c37ed954983158e4055aa94c7741d9).
- [Portal source and dependency lockfile](https://github.com/pop-os/xdg-desktop-portal-cosmic/tree/9d35e6300b69cf06da723a502a9a56604a022786).
- [Patch, tests, and build scripts](https://github.com/MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix/releases/download/v1.0.0/source.zip).

The two frame-order tests fail before the patch and pass afterward. The portal source and unrelated locked dependencies remain unchanged.

This is an unofficial downstream release. The portal executable and installer are distributed under [GPL-3.0-or-later](LICENSE); the modified capture library retains its [MIT license](LICENSE-MIT).
