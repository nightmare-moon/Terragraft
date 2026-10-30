"""Binary-safe pg_dump backups on Windows/Linux (requires Docker Compose running)."""
from pathlib import Path
import subprocess
from datetime import datetime, timezone

root = Path(__file__).resolve().parent.parent
folder = root / 'backups'
folder.mkdir(exist_ok=True)
target = folder / f'terragraft-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.dump'
result = subprocess.run(['docker','compose','exec','-T','postgres','pg_dump',
                         '-U','lab','-d','terragraft','-Fc'],
                        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if result.returncode:
    raise SystemExit(result.stderr.decode(errors='replace'))
target.write_bytes(result.stdout)
print('Saved binary PostgreSQL backup:', target)
print('Store backups securely alongside your .env encryption key (separately protected).')
