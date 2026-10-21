#!/usr/bin/env python3
"""Build one pinned portal package with the reviewed capture-library fix."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('CAPTURE_OUTPUT', '/out'))
WORK = Path(os.environ.get('CAPTURE_WORK', '/tmp/capture-build-work'))
PORTAL = 'f448ddfb296bf7bb23517b24b2f532559a334a1c'
BASE = 'c0cff4db14c37ed954983158e4055aa94c7741d9'
FORK = '3ad1781fefeaea5224ec6917f53ccad32bf5219b'
VERSION = '1.11.0~1792525517~24.04~f448ddf'
RELATIVE_SOURCE = Path('client-toolkit/src/screencopy/dispatch.rs')
ORIGINAL_BLOB = '3130af2aee95f20c8e2ea90c1ebb35aadc818806'
PATCHED_SHA = '195b0adbfe3f268433de831f688a00925ce4e23abd4d98b0901417fb226eb036'
STOCK_URL = ('https://apt.pop-os.org/release/pool/noble/xdg-desktop-portal-cosmic/' +
             PORTAL + '/xdg-desktop-portal-cosmic_' + VERSION + '_amd64.deb')
STOCK_DEB_SHA = '2ae6dd4bb02a545634aa9c9bceb475351e61d202a636c01f963d5bb3f9540f53'

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def run(args, cwd=None, log=None, negative=False):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    if log is None:
        subprocess.run(args, cwd=cwd, check=True)
        return
    with log.open('w') as output:
        process = subprocess.Popen(args, cwd=cwd, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in process.stdout:
            output.write(line)
            if not negative:
                print(line, end='', flush=True)
        result = process.wait()
    text = log.read_text()
    if negative:
        if result == 0 or text.count('destroy request must precede the next create_frame') < 2 or '2 failed' not in text:
            raise RuntimeError('Baseline did not reproduce both wire-order assertions; see ' + str(log))
        print('Baseline reproduced both expected ordering failures.', flush=True)
    elif result:
        raise RuntimeError('Command failed; see ' + str(log))

def clone(repo, revision, destination, depth=1):
    destination.mkdir()
    run(['git', 'init', '-q', str(destination)])
    run(['git', 'remote', 'add', 'origin', repo], destination)
    run(['git', 'fetch', '--no-tags', '--depth', str(depth), 'origin', revision], destination)
    run(['git', 'checkout', '--detach', revision], destination)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
    if actual != revision:
        raise RuntimeError('Pinned source revision mismatch.')

def normalized(document):
    result = []
    for package in document['package']:
        item = dict(package)
        if item['name'] in ('cosmic-client-toolkit', 'cosmic-protocols'):
            if item['version'] != '0.2.0':
                raise RuntimeError('Unexpected capture library version.')
            item.pop('source', None)
            item.pop('checksum', None)
        result.append(item)
    return sorted(result, key=lambda p: (p['name'], p['version'], p.get('source', '')))

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir()
    package = WORK / 'stock.deb'
    with urllib.request.urlopen(STOCK_URL, timeout=120) as response, package.open('xb') as output:
        shutil.copyfileobj(response, output)
    if digest(package) != STOCK_DEB_SHA:
        raise RuntimeError('Official package checksum mismatch.')
    stock_version = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Version'], text=True).strip()
    if stock_version != VERSION:
        raise RuntimeError('Official package version mismatch.')
    run(['dpkg-deb', '-x', str(package), str(WORK / 'stock')])
    stock_sha = digest(WORK / 'stock/usr/libexec/xdg-desktop-portal-cosmic')
    portal, protocols = WORK / 'portal', WORK / 'protocols'
    clone('https://github.com/pop-os/xdg-desktop-portal-cosmic.git', PORTAL, portal)
    clone('https://github.com/MagnetosphereLabs/cosmic-protocols.git', FORK, protocols, depth=2)
    names = subprocess.check_output(['git', 'diff', '--name-only', BASE, FORK], cwd=protocols, text=True).splitlines()
    if names != [str(RELATIVE_SOURCE)]:
        raise RuntimeError('Fork changes files outside the reviewed dispatcher.')
    source = protocols / RELATIVE_SOURCE
    production = source.read_bytes()
    if hashlib.sha256(production).hexdigest() != PATCHED_SHA or production != (ROOT / 'build/dispatch.rs').read_bytes():
        raise RuntimeError('Fork differs from the reviewed source fix.')
    original = subprocess.check_output(['git', 'show', BASE + ':' + str(RELATIVE_SOURCE)], cwd=protocols)
    blob = hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()
    if blob != ORIGINAL_BLOB:
        raise RuntimeError('Unexpected unpatched source.')
    source.write_bytes(original)
    run(['git', 'apply', '--check', str(ROOT / 'fix.patch')], protocols)
    run(['git', 'apply', str(ROOT / 'fix.patch')], protocols)
    if source.read_bytes() != production:
        raise RuntimeError('Published patch differs from the pinned fork.')
    shutil.copyfile(portal / 'Cargo.lock', protocols / 'Cargo.lock')
    suffix = ('\n#[cfg(test)]\n#[path = ' + json.dumps(str(ROOT / 'build/wire_order_tests.rs')) +
              ']\nmod regression_tests;\n').encode()
    test = ['cargo', 'test', '--release', '--manifest-path', str(protocols / 'client-toolkit/Cargo.toml'),
            '--lib', 'regression_tests', '--', '--nocapture']
    source.write_bytes(original + suffix)
    run(test, protocols, OUT / 'regression-before.log', negative=True)
    source.write_bytes(production + suffix)
    run(test[:2] + ['--locked'] + test[2:], protocols, OUT / 'regression-after.log')
    source.write_bytes(production)
    original_lock = tomllib.loads((portal / 'Cargo.lock').read_text())
    config = portal / '.cargo'
    config.mkdir(exist_ok=False)
    (config / 'config.toml').write_text(
        '[patch."https://github.com/pop-os/cosmic-protocols"]\n' +
        'cosmic-client-toolkit = { path = ' + json.dumps(str(protocols / 'client-toolkit')) + ' }\n' +
        'cosmic-protocols = { path = ' + json.dumps(str(protocols)) + ' }\n')
    metadata = subprocess.check_output(['cargo', 'metadata', '--format-version', '1'], cwd=portal, text=True)
    if normalized(original_lock) != normalized(tomllib.loads((portal / 'Cargo.lock').read_text())):
        raise RuntimeError('Unrelated locked dependencies changed.')
    (OUT / 'cargo-metadata.json').write_text(metadata)
    run(['cargo', 'build', '--locked', '--release', '--bin', 'xdg-desktop-portal-cosmic'], portal, OUT / 'build.log')
    target = Path(os.environ.get('CARGO_TARGET_DIR', str(portal / 'target')))
    binary = OUT / 'xdg-desktop-portal-cosmic'
    shutil.copyfile(target / 'release/xdg-desktop-portal-cosmic', binary)
    binary.chmod(0o755)
    linkage = subprocess.run(['ldd', '-r', str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUT / 'link-check.txt').write_text(linkage.stdout)
    if linkage.returncode or 'not found' in linkage.stdout or 'undefined symbol' in linkage.stdout:
        raise RuntimeError('Executable failed its library compatibility check.')
    asset = 'xdg-desktop-portal-cosmic-1.11.0-x86_64.gz'
    with binary.open('rb') as input_file, (OUT / asset).open('wb') as output_file:
        with gzip.GzipFile(filename='', fileobj=output_file, mode='wb', mtime=0) as stream:
            shutil.copyfileobj(input_file, stream)
    report = {
        'package_version': VERSION, 'portal_commit': PORTAL, 'protocols_base': BASE,
        'protocols_commit': FORK, 'original_git_blob': ORIGINAL_BLOB,
        'patched_source_sha256': PATCHED_SHA, 'binary_sha256': digest(binary),
        'binary_size': binary.stat().st_size, 'asset': asset, 'stock_sha256': stock_sha,
        'stock_deb_sha256': STOCK_DEB_SHA,
        'rustc': subprocess.check_output(['rustc', '--version'], text=True).strip(),
        'regression_before': 'Both expected wire-order assertion failures observed',
        'regression_after': 'Both wire-order tests passed',
        'unrelated_locked_dependencies': 'unchanged',
        'live_capture_test': 'Pending target-system verification',
    }
    (OUT / 'BUILD-REPORT.json').write_text(json.dumps(report, indent=2) + '\n')
    with zipfile.ZipFile(OUT / 'source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ['fix.patch', 'LICENSE', 'LICENSE-MIT']:
            archive.write(ROOT / name, 'source/' + name)
        for path in sorted((ROOT / 'build').glob('*')):
            if path.is_file():
                archive.write(path, 'source/build/' + path.name)
        for name, checkout in [('portal', portal), ('capture-library', protocols)]:
            data = subprocess.check_output(['git', 'archive', '--format=tar.gz', 'HEAD'], cwd=checkout)
            archive.writestr('source/' + name + '.tar.gz', data)
        archive.write(OUT / 'BUILD-REPORT.json', 'source/BUILD-REPORT.json')
        archive.write(portal / 'Cargo.lock', 'source/Cargo.lock')
    print('Candidate build, regression tests, and dependency checks passed.', flush=True)

if __name__ == '__main__':
    main()
