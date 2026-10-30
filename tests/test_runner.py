import hashlib
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from runner import assert_project_dir, check_http_backend, config_digest, make_tf_env, Client


class RunnerGuards(unittest.TestCase):
    def test_allowlisted_path(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root / 'stack').mkdir()
            (root / 'stack' / 'main.tf').write_text('terraform { backend "http" {} }')
            self.assertEqual(assert_project_dir(str(root/'stack'), root), (root/'stack').resolve())
            with tempfile.TemporaryDirectory() as outside:
                (Path(outside)/'main.tf').write_text('x')
                with self.assertRaises(ValueError):
                    assert_project_dir(outside, root)

    def test_requires_matching_http_backend(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            (path/'backend.tf').write_text('terraform { backend "http" {} }')
            check_http_backend(path, 'http://localhost:8080/state/demo')
            (path/'backend.tf').write_text('terraform { backend "s3" {} }')
            with self.assertRaisesRegex(ValueError,'backend'):
                check_http_backend(path, 'http://localhost:8080/state/demo')
            (path/'backend.tf').write_text('terraform { backend "http" {address="http://localhost:8080/state/other"} }')
            with self.assertRaisesRegex(ValueError,'Hardcoded'):
                check_http_backend(path, 'http://localhost:8080/state/demo')

    def test_rejects_existing_other_backend_state(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            (path/'main.tf').write_text('terraform { backend "http" {} }')
            (path/'.terraform').mkdir()
            (path/'.terraform'/'terraform.tfstate').write_text('{"backend":{"type":"s3","config":{}}}')
            with self.assertRaisesRegex(ValueError,'migrate'):
                check_http_backend(path, 'http://localhost:8080/state/demo')

    def test_configuration_digest(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            (path/'main.tf').write_text('a')
            before = config_digest(path)
            (path/'main.tf').write_text('b')
            self.assertNotEqual(before, config_digest(path))

    def test_state_env_has_correct_workspace(self):
        env=make_tf_env({}, 'token', 'http://localhost:8080','stage')
        self.assertEqual(env['TF_HTTP_LOCK_ADDRESS'], 'http://localhost:8080/state/stage')
        self.assertEqual(env['TF_HTTP_PASSWORD'], 'token')

    def test_plaintext_remote_http_rejected(self):
        with self.assertRaises(ValueError):
            Client('http://192.168.1.20:8080', 'token')
        Client('https://server.example.com', 'token')


if __name__=='__main__': unittest.main()
