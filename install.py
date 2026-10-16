#!/usr/bin/env python3
"""Install or remove the COSMIC screen capture fix."""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import fcntl
import gzip
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import platform
import tempfile
import urllib.request
import stat
import subprocess
import sys

HERE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'pop-os-cosmic-capture-freeze-fix'
EXPECTED_SHA256 = '82e042eab98889e869258dcf170112042970f81dc0d2d6a0ded9b5bc9bb0aac5'
EXPECTED_SIZE = '63947624'
BINARY_URL = 'https://github.com/MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix/releases/download/v1.0.0/xdg-desktop-portal-cosmic-x86_64.gz'
BINARY = None
OS_RELEASE = Path('/etc/os-release')
TARGET = Path('/usr/libexec/xdg-desktop-portal-cosmic')
PACKAGE = 'xdg-desktop-portal-cosmic'
VERSION = '1.10.0~1791324839~24.04~9d35e63'
UNIT = 'org.freedesktop.impl.portal.desktop.cosmic.service'
POINTER = HERE / 'backup-location.txt'

def run(args, capture=False):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None)

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def installed_version():
    return run(['/usr/bin/dpkg-query', '-W', '-f=${Version}', PACKAGE], True).stdout

def check_target():
    require(os.geteuid() != 0, 'Run this helper as your normal desktop user, not with sudo.')
    require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'This release requires Linux x86-64.')
    release = OS_RELEASE.read_text()
    require(re.search(r'^ID=[\"\']?pop[\"\']?$', release, re.M) is not None and
            re.search(r'^VERSION_ID=[\"\']?24\.04[\"\']?$', release, re.M) is not None,
            'This release supports Pop!_OS 24.04.')
    require(TARGET.is_file() and not TARGET.is_symlink(), 'Expected regular portal binary not found.')
    version = installed_version()
    require(version == VERSION, 'Unsupported portal package version: ' + version)
    properties = run(['/usr/bin/systemctl', '--user', 'show', UNIT,
                      '-p', 'LoadState', '-p', 'ExecStart'], True).stdout
    require('LoadState=loaded' in properties, 'The expected user service is not loaded; stop.')
    match = re.search(r'\bpath=([^ ;}]+)', properties)
    require(match is not None and match.group(1) == str(TARGET),
            'The service runs a different executable; stop without changing it.')
    return properties

def backup_directory():
    require(POINTER.is_file(), 'No backup is recorded for this installation.')
    directory = Path(POINTER.read_text().strip())
    require(directory.is_absolute() and directory.is_dir(), 'Backup directory is unavailable.')
    return directory

def load_backup():
    directory = backup_directory()
    manifest = json.loads((directory / 'manifest.json').read_text())
    require(manifest['target'] == str(TARGET) and manifest['version'] == VERSION,
            'The backup belongs to another target or version.')
    original = directory / 'original-portal'
    require(original.is_file() and not original.is_symlink(), 'Original binary backup is unavailable.')
    require(digest(original) == manifest['sha256'], 'Backup checksum mismatch; stop.')
    return directory, original, manifest

def backup():
    properties = check_target()
    require(not POINTER.exists(), 'A backup is already recorded; preserve it and use the existing backup.')
    metadata_file = run(['/usr/bin/dpkg-query', '--control-path', PACKAGE, 'md5sums'], True).stdout.strip()
    records = {}
    for line in Path(metadata_file).read_text().splitlines():
        checksum, name = line.split(None, 1)
        records[name] = checksum
    relative = str(TARGET).lstrip('/')
    require(relative in records, 'Package metadata does not identify the expected executable.')
    md5 = hashlib.md5()
    with TARGET.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            md5.update(chunk)
    actual_md5 = md5.hexdigest()
    require(actual_md5 == records[relative],
            'The installed executable already differs from its package; stop to preserve existing modifications.')
    before = TARGET.stat()
    require(stat.S_IMODE(before.st_mode) == 0o755 and before.st_uid == 0 and before.st_gid == 0,
            'Unexpected executable ownership or permissions; stop for review.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = HERE / 'backup'
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    original = directory / 'original-portal'
    original_digest = digest(TARGET)
    require(not original.is_symlink() and (not original.exists() or digest(original) == original_digest),
            'An existing backup differs from the original; it was preserved.')
    # Preserve ownership, permissions, timestamps, ACLs, and extended attributes.
    run(['/usr/bin/sudo', '--', '/usr/bin/cp', '--preserve=all', '--', TARGET, original])
    require(digest(original) == original_digest and digest(TARGET) == original_digest,
            'The file changed during backup; stop and preserve the backup for review.')
    manifest = {
        'target': str(TARGET), 'package': PACKAGE, 'version': VERSION,
        'sha256': original_digest, 'uid': before.st_uid, 'gid': before.st_gid,
        'mode': stat.S_IMODE(before.st_mode), 'created_utc': stamp,
        'service': UNIT, 'service_properties': properties,
    }
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with POINTER.open('x') as stream:
        stream.write(str(directory) + '\n')
    print(f'Backup saved: {directory}')

def candidate():
    binary = BINARY
    require(binary is not None and binary.is_file() and not binary.is_symlink(), 'Release download is unavailable.')
    require(binary.stat().st_size == int(EXPECTED_SIZE) and digest(binary) == EXPECTED_SHA256,
            'Release executable checksum or size mismatch.')
    with binary.open('rb') as stream:
        header = stream.read(20)
    require(header[:6] == b'\x7fELF\x02\x01' and int.from_bytes(header[18:20], 'little') == 62,
            'Release executable is not Linux x86-64 ELF.')
    return binary, {'binary_sha256': EXPECTED_SHA256}

def check():
    check_target()
    _, original, manifest = load_backup()
    require(digest(TARGET) == manifest['sha256'],
            'The installed binary changed after backup; stop rather than overwrite it.')
    binary, report = candidate()
    # Check relocations using the system loader environment.
    result = subprocess.run(['/usr/bin/ldd', '-r', str(binary)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
    (HERE / 'link-check.txt').write_text(result.stdout)
    require(result.returncode == 0 and 'not found' not in result.stdout
            and 'undefined symbol' not in result.stdout,
            'Library compatibility check failed; see ' + str(HERE / 'link-check.txt'))
    print('Backup and library compatibility verified.')
    return original, manifest, binary, report

def atomic_copy(source, expected_current):
    require(digest(TARGET) == expected_current, 'Installed executable changed; refusing to overwrite it.')
    temporary = run(['/usr/bin/sudo', '--', '/usr/bin/mktemp',
                     str(TARGET) + '.capture-fix.XXXXXX'], True).stdout.strip()
    staged = Path(temporary)
    try:
        # Preserve the original file metadata.
        # Restoring the original also restores its exact backed-up metadata.
        _, original, _ = load_backup()
        run(['/usr/bin/sudo', '--', '/usr/bin/cp', '--preserve=all', '--', original, staged])
        if source != original:
            run(['/usr/bin/sudo', '--', '/usr/bin/dd', 'if=' + str(source),
                 'of=' + str(staged), 'conv=notrunc', 'status=none'])
            # A smaller candidate must not retain the original executable's trailing bytes.
            run(['/usr/bin/sudo', '--', '/usr/bin/truncate', '-s', str(source.stat().st_size), '--', staged])
            run(['/usr/bin/sudo', '--', '/usr/bin/touch', '--reference=' + str(original), '--', staged])
        require(digest(staged) == digest(source), 'Staged executable checksum mismatch.')
        require(digest(TARGET) == expected_current, 'Installed executable changed during staging; stop.')
        run(['/usr/bin/sudo', '--', '/usr/bin/mv', '-T', '--', staged, TARGET])
    finally:
        if staged.exists():
            run(['/usr/bin/sudo', '--', '/usr/bin/rm', '--', staged])

def restart_and_verify(expected):
    run(['/usr/bin/systemctl', '--user', 'restart', UNIT])
    run(['/usr/bin/systemctl', '--user', 'is-active', '--quiet', UNIT])
    pid = run(['/usr/bin/systemctl', '--user', 'show', UNIT, '-p', 'MainPID', '--value'], True).stdout.strip()
    require(pid.isdecimal() and int(pid) > 0, 'Portal service has no main process.')
    require(digest(Path('/proc') / pid / 'exe') == expected,
            'The running portal process is not using the expected executable.')

def apply():
    original, manifest, binary, report = check()
    directory, _, _ = load_backup()
    manifest['candidate_sha256'] = report['binary_sha256']
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    try:
        atomic_copy(binary, manifest['sha256'])
        restart_and_verify(report['binary_sha256'])
    except BaseException:
        if digest(TARGET) == report['binary_sha256']:
            print('Portal startup verification failed; restoring the original executable.', file=sys.stderr)
            atomic_copy(original, report['binary_sha256'])
            restart_and_verify(manifest['sha256'])
        raise
    print('Capture fix installed. Start a new screen capture session.')

def restore():
    check_target()
    _, original, manifest = load_backup()
    current = digest(TARGET)
    if current != manifest['sha256']:
        require(current == manifest.get('candidate_sha256'),
                'The current binary differs from both the backup and candidate; stop for review.')
        atomic_copy(original, current)
    restart_and_verify(manifest['sha256'])
    print('Original portal restored and service restarted.')

def download(destination):
    request = urllib.request.Request(BINARY_URL, headers={'User-Agent': 'pop-os-cosmic-capture-freeze-fix/1.0.0'})
    print('Downloading capture fix...')
    with urllib.request.urlopen(request, timeout=60) as response:
        with gzip.GzipFile(fileobj=response) as compressed, destination.open('xb') as target:
            size = 0
            while True:
                chunk = compressed.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                require(size <= int(EXPECTED_SIZE), 'Release download exceeds its expected size.')
                target.write(chunk)
    require(destination.stat().st_size == int(EXPECTED_SIZE) and digest(destination) == EXPECTED_SHA256,
            'Release download checksum or size mismatch.')
    destination.chmod(0o755)

def main():
    global BINARY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true', help='Restore the saved original portal.')
    args = parser.parse_args()
    check_target()
    require(HERE.is_absolute(), 'XDG_STATE_HOME must be an absolute path.')
    HERE.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(HERE.stat().st_uid == os.getuid() and not HERE.is_symlink(), 'Unexpected installation state directory.')
    with (HERE / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another installation or restoration is running.')
        if args.uninstall:
            restore()
            return
        if digest(TARGET) == EXPECTED_SHA256:
            if POINTER.exists():
                load_backup()
                print('Capture fix is already installed. Original backup verified.')
            else:
                print('Capture fix is already installed. Use its existing backup to uninstall.')
            return
        # Keep a local copy for offline restoration after the bootstrap is removed.
        installer = Path(__file__).resolve()
        saved = HERE / 'install.py'
        if installer != saved:
            content = installer.read_bytes()
            staging = HERE / 'install.py.new'
            staging.write_bytes(content)
            staging.chmod(0o700)
            staging.replace(saved)
        if not POINTER.exists():
            backup()
        else:
            load_backup()
        with tempfile.TemporaryDirectory(prefix='download-', dir=HERE) as directory:
            BINARY = Path(directory) / 'portal'
            download(BINARY)
            apply()

if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'STOPPED: {exc}', file=sys.stderr)
        print('Restore command: /usr/bin/python3 ' + str(HERE / 'install.py') + ' --uninstall', file=sys.stderr)
        sys.exit(1)
