"""Static, per-service bearer/basic token authentication and RBAC.

Configure tokens using TERRAGRAFT_ADMIN_TOKEN, TERRAGRAFT_WRITER_TOKEN and
TERRAGRAFT_VIEWER_TOKEN. Run behind HTTPS for any nonlocal use.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    name: str
    role: str


_PERMISSIONS = {
    'viewer': frozenset({'read'}),
    'writer': frozenset({'read', 'write', 'plan'}),
    'admin': frozenset({'read', 'write', 'plan', 'restore', 'admin'}),
}


def _configured_tokens() -> list[tuple[str, Principal]]:
    settings = [
        ('TERRAGRAFT_ADMIN_TOKEN', Principal('admin', 'admin')),
        ('TERRAGRAFT_WRITER_TOKEN', Principal('writer', 'writer')),
        ('TERRAGRAFT_VIEWER_TOKEN', Principal('viewer', 'viewer')),
    ]
    return [(token, principal) for var, principal in settings if (token := os.getenv(var, ''))]


def ensure_configuration() -> None:
    tokens = _configured_tokens()
    if not tokens or not any(p.role == 'admin' for _, p in tokens):
        raise RuntimeError('Configure TERRAGRAFT_ADMIN_TOKEN (python scripts/init_env.py)')
    if any(len(token) < 24 for token, _ in tokens):
        raise RuntimeError('Tokens must contain at least 24 characters')
    if len(set(t for t, _ in tokens)) != len(tokens):
        raise RuntimeError('Authentication tokens must all be distinct')


def authenticate(request: Request, capability: str = 'read') -> Principal:
    # HTTP state backends support Basic authentication via TF_HTTP_PASSWORD.
    supplied = None
    authorization = request.headers.get('authorization', '')
    if authorization.lower().startswith('bearer '):
        supplied = authorization[7:].strip()
    elif authorization.lower().startswith('basic '):
        import base64
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode('utf-8')
            supplied = decoded.partition(':')[2] if ':' in decoded else None
        except (ValueError, UnicodeDecodeError):
            supplied = None
    if supplied is None:
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Basic realm="Terragraft"'})
    for expected, principal in _configured_tokens():
        if hmac.compare_digest(supplied, expected):
            if capability not in _PERMISSIONS[principal.role]:
                raise HTTPException(403, 'Insufficient permissions')
            return principal
    raise HTTPException(401, 'Invalid credentials', headers={'WWW-Authenticate': 'Basic realm="Terragraft"'})
