#!/usr/bin/env python3
"""Stage generated installer files and a draft release after a verified build."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'output'
TAG = 'v1.1.0'
BRANCH = 'release/' + TAG

def run(args, capture=False, check=True):
    return subprocess.run(args, cwd=ROOT, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)

def main():
    repo = os.environ['GITHUB_REPOSITORY']
    generated = OUTPUT / 'repository'
    assets = OUTPUT / 'release-assets'
    names = ['README.md', 'install.py', 'install.sh', 'builds.json']
    existing = run(['gh', 'release', 'view', TAG, '--repo', repo,
                    '--json', 'isDraft,targetCommitish,url'], True, False)
    release = json.loads(existing.stdout) if existing.returncode == 0 else None
    if release and not release['isDraft']:
        raise RuntimeError('This release is already public; it will not be changed.')
    heads = run(['git', 'ls-remote', '--heads', 'origin', 'refs/heads/' + BRANCH], True).stdout.strip()
    if heads:
        head = heads.split()[0]
        run(['git', 'fetch', '--no-tags', 'origin', BRANCH])
        for name in names:
            current = run(['git', 'show', head + ':' + name], True).stdout
            if current != (generated / name).read_text():
                raise RuntimeError('An existing candidate differs; it was preserved. Use a new release version.')
    else:
        for name in names:
            shutil.copyfile(generated / name, ROOT / name)
        run(['git', 'config', 'user.name', 'github-actions[bot]'])
        run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'])
        run(['git', 'add', '--'] + names)
        run(['git', 'commit', '-m', 'Release v1.1.0 with matching portal builds and versioned backups'])
        # gh reads the short-lived job token from the environment; no credential is embedded in a URL.
        run(['git', '-c', 'credential.helper=!gh auth git-credential', 'push',
             'origin', 'HEAD:refs/heads/' + BRANCH])
        head = run(['git', 'rev-parse', 'HEAD'], True).stdout.strip()
    if release and release['targetCommitish'] not in (head, BRANCH):
        raise RuntimeError('Existing draft points to another source revision; it was preserved.')
    notes = OUTPUT / 'release-notes.md'
    notes.write_text('Prebuilt fix for COSMIC screen and window capture freezing with the '
                     '`duplicate_frame` protocol error.\n\n'
                     'Supports Pop!_OS 24.04 x86-64 with portal packages '
                     '`1.10.0~1791324839~24.04~9d35e63` and '
                     '`1.11.0~1792525517~24.04~f448ddf`. The installer selects the matching build, '
                     'verifies checksums and host libraries, and preserves a separate original backup '
                     'for each package version. Existing v1.0.0 backups are retained.\n\n'
                     'The 1.11.0 executable is built from its matching upstream source against the '
                     'reviewed capture-library fix. Both wire-order regression tests pass, '
                     'and unrelated locked dependencies remain unchanged.\n\n'
                     'See the README for installation and offline restoration commands.\n')
    if release is None:
        run(['gh', 'release', 'create', TAG, '--repo', repo, '--draft', '--target', head,
             '--title', TAG, '--notes-file', str(notes)])
    run(['gh', 'release', 'upload', TAG, '--repo', repo, '--clobber'] +
        [str(path) for path in sorted(assets.iterdir()) if path.is_file()])
    summary = Path(os.environ['GITHUB_STEP_SUMMARY'])
    summary.write_text('## Release candidate ready\n\n'
        '- [Open draft release](https://github.com/' + repo + '/releases).\n'
        '- Download `test-release.zip`, extract it, and open a terminal there.\n'
        '- On the supported portal 1.11.0 package, run:\n\n'
        '```bash\n/usr/bin/python3 install.py --archive xdg-desktop-portal-cosmic-1.11.0-x86_64.gz\n```\n\n'
        'Test a new screen capture. After confirming it works, publish the draft release, then '
        '[merge the release files](https://github.com/' + repo + '/compare/main...' + BRANCH + '?expand=1). '
        'The published v1.0.0 installer remains unchanged until these release files are merged.\n')
    print('Draft release and release branch prepared. Live installation remains unchanged.')

if __name__ == '__main__':
    main()
