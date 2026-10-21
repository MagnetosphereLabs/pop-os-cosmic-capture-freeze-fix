import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_release', ROOT / 'build/prepare-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.binary = b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00candidate'
        (self.output / 'xdg-desktop-portal-cosmic').write_bytes(self.binary)
        (self.output / release.NEW_ASSET).write_bytes(gzip.compress(self.binary, mtime=0))
        with zipfile.ZipFile(self.output / 'source.zip', 'w') as z:
            z.writestr('source/README', 'test fixture')
        self.report = {
            'package_version': release.NEW_VERSION,
            'portal_commit': 'f448ddfb296bf7bb23517b24b2f532559a334a1c',
            'protocols_commit': '3ad1781fefeaea5224ec6917f53ccad32bf5219b',
            'patched_source_sha256': '195b0adbfe3f268433de831f688a00925ce4e23abd4d98b0901417fb226eb036',
            'regression_before': 'Both expected wire-order assertion failures observed',
            'regression_after': 'Both wire-order tests passed',
            'unrelated_locked_dependencies': 'unchanged',
            'asset': release.NEW_ASSET, 'binary_sha256': hashlib.sha256(self.binary).hexdigest(),
            'binary_size': len(self.binary), 'stock_sha256': 'a' * 64,
        }
        self.write_report()

    def write_report(self):
        (self.output / 'BUILD-REPORT.json').write_text(json.dumps(self.report))

    def test_generated_release_is_consistent(self):
        release.prepare(self.output, 'MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix')
        generated = self.output / 'repository'
        self.assertEqual({p.name for p in generated.iterdir()}, {'README.md', 'install.py', 'install.sh', 'builds.json'})
        install = (generated / 'install.py').read_bytes()
        shell = (generated / 'install.sh').read_text()
        self.assertIn(hashlib.sha256(install).hexdigest(), shell)
        self.assertIn('/v1.1.0/install.py', shell)
        subprocess.run(['bash', '-n', str(generated / 'install.sh')], check=True)
        mapping = json.loads((generated / 'builds.json').read_text())['packages']
        self.assertEqual(set(mapping), {release.OLD_VERSION, release.NEW_VERSION})
        self.assertEqual(mapping[release.OLD_VERSION]['sha256'], release.OLD_SHA)
        self.assertIn('/v1.0.0/', mapping[release.OLD_VERSION]['url'])
        self.assertEqual(mapping[release.NEW_VERSION]['sha256'], self.report['binary_sha256'])
        assets = self.output / 'release-assets'
        for line in (assets / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(hashlib.sha256((assets / name).read_bytes()).hexdigest(), digest)
        with zipfile.ZipFile(assets / 'test-release.zip') as z:
            for line in z.read('SHA256SUMS').decode().splitlines():
                digest, name = line.split('  ')
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
        self.assertNotRegex((generated / 'README.md').read_text(), r'WayVR|Conda|CUDA|ChatGPT|AI-generated')

    def test_unverified_build_is_rejected(self):
        self.report['regression_after'] = 'not run'
        self.write_report()
        with self.assertRaisesRegex(ValueError, 'passing checks'):
            release.prepare(self.output, 'owner/repository')

    def test_modified_binary_is_rejected(self):
        (self.output / 'xdg-desktop-portal-cosmic').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs from its report'):
            release.prepare(self.output, 'owner/repository')

    def test_repository_argument_is_not_code(self):
        with self.assertRaisesRegex(ValueError, 'repository name'):
            release.prepare(self.output, 'owner/repo; touch file')

if __name__ == '__main__':
    unittest.main()
