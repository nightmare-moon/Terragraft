import os
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app.security import authenticate, ensure_configuration


class RequestStub:
    def __init__(self, auth):
        self.headers = {'authorization': auth}


class AuthTests(unittest.TestCase):
    def test_rbac_and_basic_auth(self):
        import base64
        with patch.dict(os.environ, {'TERRAGRAFT_ADMIN_TOKEN': 'a'*30,
                                     'TERRAGRAFT_VIEWER_TOKEN': 'v'*30}, clear=False):
            self.assertEqual(authenticate(RequestStub('Bearer '+'v'*30), 'read').role, 'viewer')
            with self.assertRaises(HTTPException) as error:
                authenticate(RequestStub('Bearer '+'v'*30), 'write')
            self.assertEqual(error.exception.status_code, 403)
            encoded = base64.b64encode(('terraform:'+'a'*30).encode()).decode()
            self.assertEqual(authenticate(RequestStub('Basic '+encoded), 'write').role, 'admin')

    def test_fail_closed(self):
        with patch.dict(os.environ, {'TERRAGRAFT_ADMIN_TOKEN': 'short'}, clear=False):
            with self.assertRaises(RuntimeError):
                ensure_configuration()
