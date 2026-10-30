import os
import unittest
import base64
from unittest.mock import patch
from cryptography.fernet import InvalidToken
from app.crypto import seal, unseal, PREFIX


class CryptoTests(unittest.TestCase):
    def test_encrypted_binary_roundtrip(self):
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch.dict(os.environ, {'TERRAGRAFT_ENCRYPTION_KEY': key}, clear=False):
            original = b'{"some secret":"pass123"}'
            ciphertext = seal(original)
            self.assertTrue(ciphertext.startswith(PREFIX))
            self.assertNotIn(b'pass123', ciphertext)
            self.assertEqual(unseal(ciphertext), original)

    def test_old_key_rotation(self):
        old = base64.urlsafe_b64encode(os.urandom(32)).decode()
        new = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch.dict(os.environ, {'TERRAGRAFT_ENCRYPTION_KEY': old}, clear=False):
            ciphertext = seal(b'secret')
        with patch.dict(os.environ, {'TERRAGRAFT_ENCRYPTION_KEY': new,
                                      'TERRAGRAFT_OLD_ENCRYPTION_KEYS': old}, clear=False):
            self.assertEqual(unseal(ciphertext), b'secret')

    def test_never_accepts_legacy_plaintext(self):
        with self.assertRaises(ValueError):
            unseal(b'{"version":4}')
