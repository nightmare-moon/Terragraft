"""Run once: creates local secrets using only Python standard library."""
from pathlib import Path
import os
import secrets
import base64

root = Path(__file__).resolve().parent.parent
out = root / '.env'
if out.exists():
    raise SystemExit('Refusing to overwrite existing .env. Keep your encryption key safe.')
fields = {
    'TERRAGRAFT_ADMIN_TOKEN': secrets.token_urlsafe(36),
    'TERRAGRAFT_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode('ascii'),
    'TERRAGRAFT_AGENT_TOKEN': secrets.token_urlsafe(36),
    'TERRAGRAFT_WRITER_TOKEN': secrets.token_urlsafe(36),
    'POSTGRES_PASSWORD': secrets.token_urlsafe(28),
}
out.write_text(''.join(f'{key}={value}\n' for key,value in fields.items()), encoding='utf-8')
try:
    os.chmod(out, 0o600)
except OSError:
    pass
print('Created .env. Back it up securely: losing the encryption key makes state unreadable.')
print('Use USE-TERRAGRAFT.ps1 to load Terraform backend credentials for manual CLI operations.')
