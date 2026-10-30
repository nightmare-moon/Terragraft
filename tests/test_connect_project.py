import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from connect_project import backend_text, validate_project, check_safe_new_project, register

class FreshProjectTests(unittest.TestCase):
    def test_backend_is_local_and_matches_runner(self):
        config=backend_text('network-dev')
        self.assertIn('http://127.0.0.1:8080/state/network-dev',config)
        self.assertIn('lock_method    = "LOCK"',config)
        self.assertNotIn('password',config)
        with self.assertRaises(ValueError):
            backend_text('../escape')
        with self.assertRaises(ValueError):
            backend_text('network',url='http://example.org')

    def test_ordinary_new_project_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'demo'
            folder.mkdir()
            (folder/'main.tf').write_text('resource "terraform_data" "test" {}')
            self.assertEqual(check_safe_new_project(folder),folder/'backend.tf')
            self.assertEqual(validate_project(folder,root),folder)

    def test_existing_state_refused(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            (folder/'main.tf').write_text('output "x" { value = 1 }')
            (folder/'terraform.tfstate').write_text('{}')
            with self.assertRaisesRegex(ValueError,'state'):
                check_safe_new_project(folder)

    def test_existing_backend_refused(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            (folder/'main.tf').write_text('terraform { backend "s3" {} }')
            with self.assertRaisesRegex(ValueError,'backend'):
                check_safe_new_project(folder)

    def test_outside_root_refused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            (Path(outside)/'main.tf').write_text('resource "terraform_data" "x" {}')
            with self.assertRaisesRegex(ValueError,'root'):
                validate_project(outside,root)

if __name__ == '__main__':
    unittest.main()
