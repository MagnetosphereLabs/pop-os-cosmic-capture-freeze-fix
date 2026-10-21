#!/usr/bin/env python3
"""Package a verified build and generate matching release installer files."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pprint
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = 'v1.1.0'
OLD_VERSION = '1.10.0~1791324839~24.04~9d35e63'
NEW_VERSION = '1.11.0~1792525517~24.04~f448ddf'
OLD_SHA = '82e042eab98889e869258dcf170112042970f81dc0d2d6a0ded9b5bc9bb0aac5'
NEW_ASSET = 'xdg-desktop-portal-cosmic-1.11.0-x86_64.gz'

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def readme(repository):
    return f'''# Pop!_OS COSMIC Capture Freeze Fix

Fixes screen and window capture freezing caused by COSMIC's `duplicate_frame` protocol error.

## Install

Close active screen captures and file dialogs, then run:

```sh
curl -fsSL https://raw.githubusercontent.com/{repository}/{RELEASE}/install.sh | /bin/bash
```

The installer selects the matching prebuilt executable, verifies its checksum and system libraries, backs up the original, and restarts the portal service. Enter the sudo password when prompted, then start a new capture session. No compilation or reboot is required.

## Compatibility

Pop!_OS 24.04 with COSMIC on x86-64. Supported `xdg-desktop-portal-cosmic` package versions:

| Portal package | Prebuilt executable |
| --- | --- |
| `{OLD_VERSION}` | Original verified 1.10.0 build |
| `{NEW_VERSION}` | Matching 1.11.0 build |

The installer detects the installed portal package, independently of the compositor version. Unsupported packages are left unchanged. The capture-library fix is GPU-independent.

## Backup and restore

Only `/usr/libexec/xdg-desktop-portal-cosmic` is replaced. The service `org.freedesktop.impl.portal.desktop.cosmic.service` is restarted and its running executable is verified. Failed startup verification triggers restoration of the original.

Backups and an offline restore helper are retained under `${{XDG_STATE_HOME:-$HOME/.local/state}}/pop-os-cosmic-capture-freeze-fix`. Each supported package version has its own backup. Backups made by v1.0.0 are recognized and preserved. Temporary downloads are removed automatically.

Restore the original for the currently installed package:

```sh
/usr/bin/python3 "${{XDG_STATE_HOME:-$HOME/.local/state}}/pop-os-cosmic-capture-freeze-fix/install.py" --uninstall
```

Backups survive reboots and are retained after restoration. The helper refuses to restore an older package's executable over a newer package. Regular package updates remain enabled. Other packages, drivers, compositor files, and system configuration are unchanged.

## Source and builds

[fix.patch](fix.patch) moves frame destruction before the completion callbacks in `client-toolkit/src/screencopy/dispatch.rs`. This queues destruction before a callback can wake a consumer that requests the next frame.

- [Patched capture library](https://github.com/MagnetosphereLabs/cosmic-protocols/tree/3ad1781fefeaea5224ec6917f53ccad32bf5219b).
- [Portal 1.11.0 source](https://github.com/pop-os/xdg-desktop-portal-cosmic/tree/f448ddfb296bf7bb23517b24b2f532559a334a1c).
- [Portal 1.10.0 source](https://github.com/pop-os/xdg-desktop-portal-cosmic/tree/9d35e6300b69cf06da723a502a9a56604a022786).
- [Release build information](builds.json), [build instructions](build/README.md), and [source archive](https://github.com/{repository}/releases/download/{RELEASE}/source.zip).

Builds verify that the original fails both wire-order regression tests, the patch passes both, and unrelated locked dependencies remain unchanged. Build reports and SHA256 checksums accompany releases. Screen-capture testing on a target desktop is required before publishing a candidate release.

This is an unofficial downstream release. The portal and installer are distributed under [GPL-3.0-or-later](LICENSE); the modified capture library retains its [MIT license](LICENSE-MIT).
'''

def prepare(output, repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository name.')
    report = json.loads((output / 'BUILD-REPORT.json').read_text())
    required = {
        'package_version': NEW_VERSION,
        'portal_commit': 'f448ddfb296bf7bb23517b24b2f532559a334a1c',
        'protocols_commit': '3ad1781fefeaea5224ec6917f53ccad32bf5219b',
        'patched_source_sha256': '195b0adbfe3f268433de831f688a00925ce4e23abd4d98b0901417fb226eb036',
        'regression_before': 'Both expected wire-order assertion failures observed',
        'regression_after': 'Both wire-order tests passed',
        'unrelated_locked_dependencies': 'unchanged',
        'asset': NEW_ASSET,
    }
    if any(report.get(k) != v for k, v in required.items()):
        raise ValueError('Build report does not identify the reviewed build and passing checks.')
    binary = output / 'xdg-desktop-portal-cosmic'
    if digest(binary) != report['binary_sha256'] or binary.stat().st_size != report['binary_size']:
        raise ValueError('Built executable differs from its report.')
    with gzip.open(output / NEW_ASSET, 'rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != report['binary_sha256']:
            raise ValueError('Compressed release differs from the built executable.')
    builds = {
        OLD_VERSION: {'sha256': OLD_SHA, 'size': 63947624,
                      'url': f'https://github.com/{repository}/releases/download/v1.0.0/xdg-desktop-portal-cosmic-x86_64.gz'},
        NEW_VERSION: {'sha256': report['binary_sha256'], 'size': report['binary_size'],
                      'stock_sha256': report['stock_sha256'],
                      'url': f'https://github.com/{repository}/releases/download/{RELEASE}/{NEW_ASSET}'},
    }
    installer = (ROOT / 'build/installer.py.in').read_text()
    marker = 'BUILDS = {} # @BUILDS@'
    if installer.count(marker) != 1:
        raise ValueError('Installer template marker mismatch.')
    installer = installer.replace(marker, 'BUILDS = ' + pprint.pformat(builds, sort_dicts=True))
    compile(installer, 'install.py', 'exec')
    sha = hashlib.sha256(installer.encode()).hexdigest()
    shell = f'''#!/bin/bash
set -euo pipefail
installer_url='https://raw.githubusercontent.com/{repository}/{RELEASE}/install.py'
installer_sha256='{sha}'
work_dir="$(/usr/bin/mktemp -d)"
trap '/usr/bin/rm -rf -- "$work_dir"' EXIT
/usr/bin/curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --max-time 120 \\
    "$installer_url" --output "$work_dir/install.py"
printf '%s  %s\\n' "$installer_sha256" "$work_dir/install.py" | /usr/bin/sha256sum --check --status
/usr/bin/python3 "$work_dir/install.py" "$@"
'''
    generated = output / 'repository'
    generated.mkdir(exist_ok=False)
    files = {'install.py': installer, 'install.sh': shell, 'README.md': readme(repository),
             'builds.json': json.dumps({'release': RELEASE, 'packages': builds}, indent=2) + '\n'}
    for name, content in files.items():
        (generated / name).write_text(content)
    assets = output / 'release-assets'
    assets.mkdir(exist_ok=False)
    for name in [NEW_ASSET, 'source.zip', 'BUILD-REPORT.json']:
        shutil.copyfile(output / name, assets / name)
    for name in ['install.py', 'install.sh', 'builds.json']:
        shutil.copyfile(generated / name, assets / name)
    sums = ''.join(digest(path) + '  ' + path.name + '\n' for path in sorted(assets.iterdir()))
    (assets / 'SHA256SUMS').write_text(sums)
    with zipfile.ZipFile(assets / 'test-release.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(assets.iterdir()):
            if path.name != 'test-release.zip':
                archive.write(path, path.name)
        archive.writestr('TESTING.txt',
            'For the supported 1.11.0 package, open a terminal in this extracted folder and run:\n'
            '/usr/bin/python3 install.py --archive ' + NEW_ASSET + '\n\n'
            'For the supported 1.10.0 package, run /usr/bin/python3 install.py.\n'
            'The existing verified 1.10.0 release is selected automatically.\n\n'
            'Restore the original for the installed package with:\n'
            '/usr/bin/python3 "${XDG_STATE_HOME:-$HOME/.local/state}/pop-os-cosmic-capture-freeze-fix/install.py" --uninstall\n')
    # Include the test bundle itself in the final checksum list.
    (assets / 'SHA256SUMS').write_text(sums + digest(assets / 'test-release.zip') + '  test-release.zip\n')
    print('Generated both-version installer, bootstrap checksum, release assets, and test bundle.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    prepare(args.output, args.repository)
