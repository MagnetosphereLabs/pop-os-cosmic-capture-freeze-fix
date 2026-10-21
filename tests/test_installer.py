import gzip
import hashlib
import json
from pathlib import Path
import pprint
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OLD = '1.10.0~1791324839~24.04~9d35e63'
NEW = '1.11.0~1792525517~24.04~f448ddf'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def elf(payload):
    return b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00' + payload

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.stock = {OLD: elf(b'original-old' * 51), NEW: elf(b'original-new' * 61)}
        self.fixed = {OLD: elf(b'patched-old' * 41), NEW: elf(b'patched-new' * 31)}
        self.version = OLD
        builds = {v: {'sha256': sha(self.fixed[v]), 'size': len(self.fixed[v]),
                      'url': 'https://example.invalid/' + v} for v in [OLD, NEW]}
        builds[NEW]['stock_sha256'] = sha(self.stock[NEW])
        source = (ROOT / 'build/installer.py.in').read_text().replace(
            'BUILDS = {} # @BUILDS@', 'BUILDS = ' + pprint.pformat(builds))
        self.helper = self.base / 'candidate.py'
        self.helper.write_text(source)
        self.m = types.ModuleType('candidate_installer')
        self.m.__file__ = str(self.helper)
        exec(compile(source, str(self.helper), 'exec'), self.m.__dict__)
        self.m.HERE = self.base / 'state'
        self.m.TARGET = self.base / 'portal'
        self.m.OS_RELEASE = self.base / 'os-release'
        self.m.OS_RELEASE.write_text('ID=pop\nVERSION_ID="24.04"\n')
        self.target = self.m.TARGET
        self.put_stock(OLD)
        self.md5file = self.base / 'md5sums'
        self.raw_run = subprocess.run
        self.m.run = self.fake_run
        self.restarts = []
        self.fail_start = False
        self.m.restart_and_verify = self.verify_start
        self.addCleanup(patch.stopall)
        patch.object(self.m.os, 'geteuid', return_value=1000).start()
        patch.object(self.m.platform, 'machine', return_value='x86_64').start()
        patch.object(self.m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'libraries resolved\n')).start()
        raw_stat = Path.stat
        target = self.target
        def package_stat(path, *args, **kwargs):
            result = raw_stat(path, *args, **kwargs)
            if path == target:
                values = {name: getattr(result, name) for name in dir(result) if name.startswith('st_')}
                values.update(st_uid=0, st_gid=0)
                return types.SimpleNamespace(**values)
            return result
        patch.object(Path, 'stat', package_stat).start()

    def put_stock(self, version):
        self.version = version
        self.target.write_bytes(self.stock[version])
        self.target.chmod(0o755)

    def fake_run(self, args, capture=False):
        args = list(map(str, args))
        if args[0] == '/usr/bin/dpkg-query':
            if '--control-path' in args:
                self.md5file.write_text(hashlib.md5(self.stock[self.version]).hexdigest() +
                                       '  ' + str(self.target).lstrip('/') + '\n')
                return subprocess.CompletedProcess(args, 0, str(self.md5file))
            return subprocess.CompletedProcess(args, 0, self.version)
        if args[0] == '/usr/bin/systemctl':
            return subprocess.CompletedProcess(args, 0, 'LoadState=loaded\nExecStart={ path=' + str(self.target) + ' ; }\n')
        if args[:2] == ['/usr/bin/sudo', '--']:
            return self.raw_run(args[2:], check=True, text=True,
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.STDOUT if capture else None)
        self.fail('Unexpected command: ' + repr(args))

    def verify_start(self, expected):
        self.assertEqual(sha(self.target.read_bytes()), expected)
        self.restarts.append(expected)
        if self.fail_start:
            self.fail_start = False
            raise RuntimeError('simulated startup failure')

    def archive(self, data=None):
        path = self.base / ('candidate-' + str(len(list(self.base.glob('*.gz')))) + '.gz')
        path.write_bytes(gzip.compress(self.fixed[self.version] if data is None else data, mtime=0))
        return path

    def install(self):
        self.m.main(['--archive', str(self.archive())])

    def backup_path(self, version):
        key = hashlib.sha256(version.encode()).hexdigest()[:20]
        pointer = self.m.HERE / 'versions' / key / 'backup-location.txt'
        return Path(pointer.read_text().strip()) / 'original-portal'

    def legacy(self, patched=True):
        self.m.HERE.mkdir()
        directory = self.m.HERE / 'backup'
        directory.mkdir()
        (directory / 'original-portal').write_bytes(self.stock[OLD])
        (directory / 'original-portal').chmod(0o755)
        manifest = {'version': OLD, 'target': str(self.target), 'package': self.m.PACKAGE,
                    'sha256': sha(self.stock[OLD]), 'candidate_sha256': sha(self.fixed[OLD])}
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        (self.m.HERE / 'backup-location.txt').write_text(str(directory) + '\n')
        if patched:
            self.target.write_bytes(self.fixed[OLD])
        return directory

    def test_original_version_install_restore(self):
        original_time = self.target.stat().st_mtime_ns
        self.install()
        self.assertEqual(self.target.read_bytes(), self.fixed[OLD])
        self.assertEqual(self.backup_path(OLD).read_bytes(), self.stock[OLD])
        self.m.main(['--uninstall'])
        self.assertEqual(self.target.read_bytes(), self.stock[OLD])
        self.assertEqual(self.target.stat().st_mtime_ns, original_time)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o755)

    def test_new_version_install_restore(self):
        self.put_stock(NEW)
        self.install()
        self.assertEqual(self.target.read_bytes(), self.fixed[NEW])
        self.m.main(['--uninstall'])
        self.assertEqual(self.target.read_bytes(), self.stock[NEW])

    def test_repeat_install_preserves_backup(self):
        self.install()
        original = self.backup_path(OLD)
        before = original.stat().st_mtime_ns
        self.m.main(['--archive', '/nonexistent'])
        self.assertEqual(original.stat().st_mtime_ns, before)
        self.assertEqual(len(self.restarts), 1)

    def test_existing_v100_patch_and_backup_migrate(self):
        legacy = self.legacy()
        self.m.main([])
        self.assertEqual(self.backup_path(OLD), legacy / 'original-portal')
        self.assertEqual(self.target.read_bytes(), self.fixed[OLD])
        self.assertEqual((self.m.HERE / 'install.py').read_text(), self.helper.read_text())
        self.m.main(['--uninstall'])
        self.assertEqual(self.target.read_bytes(), self.stock[OLD])

    def test_legacy_original_can_be_patched_again(self):
        legacy = self.legacy(patched=False)
        self.install()
        self.assertEqual(self.backup_path(OLD), legacy / 'original-portal')

    def test_upgrade_keeps_both_backups(self):
        self.install()
        old_backup = self.backup_path(OLD)
        self.put_stock(NEW)
        self.install()
        new_backup = self.backup_path(NEW)
        self.assertNotEqual(old_backup, new_backup)
        self.m.main(['--uninstall'])
        self.assertEqual(self.target.read_bytes(), self.stock[NEW])
        self.assertEqual(old_backup.read_bytes(), self.stock[OLD])
        self.assertEqual(new_backup.read_bytes(), self.stock[NEW])

    def test_legacy_backup_survives_new_package(self):
        legacy = self.legacy()
        self.put_stock(NEW)
        self.install()
        self.assertEqual((legacy / 'original-portal').read_bytes(), self.stock[OLD])
        self.assertNotEqual(self.backup_path(NEW), legacy / 'original-portal')

    def test_original_not_restored_over_new_official_package(self):
        self.install()
        self.put_stock(NEW)
        with self.assertRaisesRegex(RuntimeError, 'No backup'):
            self.m.main(['--uninstall'])
        self.assertEqual(self.target.read_bytes(), self.stock[NEW])

    def test_unsupported_package_changes_nothing(self):
        self.version = '1.12.0'
        with self.assertRaisesRegex(RuntimeError, 'Unsupported portal'):
            self.m.main([])
        self.assertFalse(self.m.HERE.exists())

    def test_modified_system_executable_is_preserved(self):
        self.target.write_bytes(b'custom portal')
        with self.assertRaisesRegex(RuntimeError, 'differs from its package'):
            self.install()
        self.assertEqual(self.target.read_bytes(), b'custom portal')

    def test_corrupt_archive_preserves_original(self):
        with self.assertRaisesRegex(RuntimeError, 'checksum or size'):
            self.m.main(['--archive', str(self.archive(b'bad data'))])
        self.assertEqual(self.target.read_bytes(), self.stock[OLD])
        self.assertEqual(self.backup_path(OLD).read_bytes(), self.stock[OLD])

    def test_missing_library_preserves_original(self):
        self.m.subprocess.run.return_value = subprocess.CompletedProcess([], 0, 'libmissing.so => not found\n')
        with self.assertRaisesRegex(RuntimeError, 'Library compatibility'):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.stock[OLD])

    def test_failed_start_restores_original(self):
        self.fail_start = True
        with self.assertRaisesRegex(RuntimeError, 'simulated startup'):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.stock[OLD])
        self.assertEqual(len(self.restarts), 2)

    def test_modified_installed_fix_is_not_overwritten_on_restore(self):
        self.install()
        self.target.write_bytes(b'new custom portal')
        with self.assertRaisesRegex(RuntimeError, 'differs from both'):
            self.m.main(['--uninstall'])
        self.assertEqual(self.target.read_bytes(), b'new custom portal')

    def test_corrupt_legacy_backup_is_preserved_and_rejected(self):
        legacy = self.legacy()
        (legacy / 'original-portal').write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError, 'Legacy backup checksum'):
            self.m.main([])
        self.assertEqual(self.target.read_bytes(), self.fixed[OLD])

    def test_current_package_changes_before_replace_are_rejected(self):
        self.install()
        self.version = NEW
        with self.assertRaisesRegex(RuntimeError, 'package version changed'):
            self.m.atomic_copy(self.backup_path(OLD), sha(self.fixed[OLD]))
        self.assertEqual(self.target.read_bytes(), self.fixed[OLD])

if __name__ == '__main__':
    unittest.main()
