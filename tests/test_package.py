import importlib.util
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_script', ROOT / 'scripts/package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def test_archive_contains_exact_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, str(ROOT / 'scripts/package.py'), '--out', directory],
                           check=True, capture_output=True)
            archive, = Path(directory).glob('*.tar.gz')
            with tarfile.open(archive) as tar:
                self.assertEqual(set(tar.getnames()),
                                 {'bili_platform_aux/' + name for name in package.RUNTIME_FILES})
                self.assertTrue(all(member.isfile() for member in tar.getmembers()))

    def test_rejects_directory_traversal_module_name(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/package.py'), '--name', '../outside'],
                                capture_output=True)
        self.assertNotEqual(result.returncode, 0)
