"""Idempotent schema upgrades and one-way encryption of old Lab snapshots."""
from __future__ import annotations
from pathlib import Path
from .crypto import PREFIX, seal


def upgrade(conn):
    # Bootstraps a new database and safely upgrades existing volumes.
    # No Docker bind mount is needed (which avoids Windows host path mount issues).
    schema_dir = Path(__file__).parent.parent / 'db'
    base_schema = (schema_dir / '001_schema.sql').read_text()
    hardening_schema = (schema_dir / '002_hardening.sql').read_text()
    registry_schema = (schema_dir / '003_project_console.sql').read_text()
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(819376551)')
        conn.execute(base_schema)
        conn.execute(hardening_schema)
        conn.execute(registry_schema)
        # Legacy v0.1 snapshots were plaintext. No history of those older writes exists.
        for workspace, body in conn.execute('SELECT name,state_bytes FROM workspaces WHERE state_bytes IS NOT NULL'):
            raw = bytes(body)
            if not raw.startswith(PREFIX):
                conn.execute('UPDATE workspaces SET state_bytes=%s WHERE name=%s', (seal(raw), workspace))
        for history_id, body in conn.execute('SELECT id,state_bytes FROM state_versions WHERE state_bytes IS NOT NULL'):
            raw = bytes(body)
            if not raw.startswith(PREFIX):
                conn.execute('UPDATE state_versions SET state_bytes=%s WHERE id=%s', (seal(raw), history_id))
