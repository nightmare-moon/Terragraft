"""Authenticated encryption for state snapshots and experimental graph values."""
from __future__ import annotations

import os
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

PREFIX = b'TGv2:'


def _keyring() -> MultiFernet:
    keys = [os.getenv('TERRAGRAFT_ENCRYPTION_KEY', '')] + [
        item.strip() for item in os.getenv('TERRAGRAFT_OLD_ENCRYPTION_KEYS', '').split(',') if item.strip()
    ]
    try:
        if not keys[0]:
            raise ValueError('missing primary key')
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys])
    except (ValueError, TypeError) as error:
        raise RuntimeError('Invalid or absent TERRAGRAFT_ENCRYPTION_KEY') from error


def ensure_encryption() -> None:
    _keyring()


def seal(value: bytes) -> bytes:
    return PREFIX + _keyring().encrypt(value)


def unseal(value: bytes) -> bytes:
    if not value.startswith(PREFIX):
        raise ValueError('Found a legacy plaintext state; migration must run before serving traffic')
    try:
        return _keyring().decrypt(value[len(PREFIX):])
    except InvalidToken as error:
        raise RuntimeError('Unable to decrypt state. Check key rotation configuration.') from error
