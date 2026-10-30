"""Terragraft Standalone v1.0.

Safe Terraform/OpenTofu HTTP backend + independent experimental graph transaction API.
Graph transactions DO NOT execute provider changes or implement state fragment merging
for an existing single Terraform workspace. Separate backend workspaces can run in parallel.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from .crypto import ensure_encryption, seal, unseal
from .graph_engine import conflicting_versions, impacted_resources, prerequisite_resources, valid_resource_address
from .migration import upgrade
from .security import authenticate, ensure_configuration, Principal
from .state_parser import extract_graph
from .project_console import router as project_console_router

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://lab:lab_only_change_me@localhost:5432/terragraft')
MAX_STATE = 30_000_000


def db():
    return psycopg.connect(DATABASE_URL)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_configuration()
    ensure_encryption()
    with db() as conn:
        upgrade(conn)
    yield


app = FastAPI(title='Terragraft Lab', version='1.0.0', lifespan=lifespan,
              description='Whole-state HTTP backend + centralized project console + experimental graph transactions')


def _audit(conn, workspace: str, actor: str, event: str, detail: dict | None = None):
    # Never log plaintext state or graph resource values into the audit log.
    conn.execute('''INSERT INTO audit_events(workspace,actor,event_type,detail)
                    VALUES (%s,%s,%s,%s)''', (workspace, actor, event, Jsonb(detail or {})))


def _workspace_row(conn, workspace):
    conn.execute('INSERT INTO workspaces(name) VALUES (%s) ON CONFLICT DO NOTHING', (workspace,))
    return conn.execute('''SELECT state_bytes,lineage,serial,lock_info
                           FROM workspaces WHERE name=%s FOR UPDATE''', (workspace,)).fetchone()


def _lock_id(info):
    value = info.get('ID') if isinstance(info, dict) else None
    return value if isinstance(value, str) and value else None


def _assert_lock(lock_info, request_id):
    held = _lock_id(lock_info)
    if held and held != request_id:
        raise HTTPException(423, detail={'error': 'workspace locked', 'lock': lock_info})
    if request_id and held != request_id:
        raise HTTPException(409, 'Request lock ID is not currently held')


def _validate_state(body: bytes):
    if len(body) > MAX_STATE:
        raise HTTPException(413, 'State snapshot exceeds 30MB limit')
    try:
        state = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid JSON state')
    if not isinstance(state, dict) or state.get('version') != 4:
        raise HTTPException(400, 'Expected raw Terraform state version 4')
    serial = state.get('serial')
    lineage = state.get('lineage')
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 0:
        raise HTTPException(400, 'Invalid state serial')
    if not isinstance(lineage, str) or not lineage:
        raise HTTPException(400, 'Invalid state lineage')
    return state, serial, lineage


def _save_graph(conn, workspace, state):
    nodes, edges = extract_graph(state)
    conn.execute('DELETE FROM resource_edges WHERE workspace=%s', (workspace,))
    conn.execute('DELETE FROM resource_nodes WHERE workspace=%s', (workspace,))
    for node in nodes:
        conn.execute('''INSERT INTO resource_nodes(workspace,address,provider,resource_type,mode)
                        VALUES (%s,%s,%s,%s,%s)''',
                     (workspace, node['address'], node['provider'], node['resource_type'], node['mode']))
    for source, target in edges:
        conn.execute('''INSERT INTO resource_edges(workspace,source_address,target_address)
                        VALUES (%s,%s,%s)''', (workspace, source, target))


def _archive(conn, workspace, snapshot, lineage, serial, actor, action):
    # Every event records the resulting encrypted snapshot. Retain old versions.
    row = conn.execute('''INSERT INTO state_versions(workspace,state_bytes,lineage,serial,action,actor)
                          VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''',
                       (workspace, snapshot, lineage, serial, action, actor)).fetchone()
    return row[0]


@app.get('/ui', include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent / 'static' / 'index.html',
                        headers={'Cache-Control': 'no-store', 'Content-Security-Policy':
                                 "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"})


@app.get('/health')
def health():
    with db() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok', 'version': '1.0.0'}


@app.get('/api/me')
def whoami(request: Request):
    principal = authenticate(request, 'read')
    return {'identity': principal.name, 'role': principal.role}


@app.get('/state/{workspace}')
def get_state(workspace: str, request: Request):
    authenticate(request, 'read')
    with db() as conn:
        row = conn.execute('SELECT state_bytes FROM workspaces WHERE name=%s', (workspace,)).fetchone()
    if not row or row[0] is None:
        raise HTTPException(404, 'State not initialized')
    return Response(content=unseal(bytes(row[0])), media_type='application/json',
                    headers={'Cache-Control': 'no-store'})


@app.post('/state/{workspace}')
async def put_state(workspace: str, request: Request):
    principal = authenticate(request, 'write')
    body = await request.body()
    state, serial, lineage = _validate_state(body)
    with db() as conn:
        with conn.transaction():
            old_body, old_lineage, old_serial, lock_info = _workspace_row(conn, workspace)
            _assert_lock(lock_info, request.query_params.get('ID'))
            if old_lineage and old_lineage != lineage:
                raise HTTPException(409, 'Lineage mismatch')
            if old_serial is not None and serial < old_serial:
                raise HTTPException(409, 'Stale state serial')
            if old_serial is not None and serial == old_serial:
                if unseal(bytes(old_body)) == body:
                    return Response(status_code=200)  # idempotent retry
                raise HTTPException(409, 'Same serial with a conflicting snapshot')
            encrypted = seal(body)
            conn.execute('''UPDATE workspaces SET state_bytes=%s,lineage=%s,serial=%s,
                            updated_at=now() WHERE name=%s''', (encrypted, lineage, serial, workspace))
            _save_graph(conn, workspace, state)
            version = _archive(conn, workspace, encrypted, lineage, serial, principal.name, 'push')
            _audit(conn, workspace, principal.name, 'state.push', {'serial': serial, 'history_id': version})
    return Response(status_code=200)


@app.delete('/state/{workspace}')
def delete_state(workspace: str, request: Request):
    principal = authenticate(request, 'write')
    with db() as conn:
        with conn.transaction():
            old_body, _, _, lock_info = _workspace_row(conn, workspace)
            _assert_lock(lock_info, request.query_params.get('ID'))
            if old_body is None:
                return Response(status_code=404)
            conn.execute('''UPDATE workspaces SET state_bytes=NULL,lineage=NULL,serial=NULL,
                            updated_at=now() WHERE name=%s''', (workspace,))
            conn.execute('DELETE FROM resource_edges WHERE workspace=%s', (workspace,))
            conn.execute('DELETE FROM resource_nodes WHERE workspace=%s', (workspace,))
            version = _archive(conn, workspace, None, None, None, principal.name, 'delete')
            _audit(conn, workspace, principal.name, 'state.delete', {'history_id': version})
    return Response(status_code=200)


@app.api_route('/state/{workspace}', methods=['LOCK'])
async def lock_state(workspace: str, request: Request):
    principal = authenticate(request, 'write')
    try:
        info = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, 'Invalid lock JSON')
    if not isinstance(info, dict) or not _lock_id(info):
        raise HTTPException(400, 'Lock requires ID')
    with db() as conn:
        with conn.transaction():
            _, _, _, held = _workspace_row(conn, workspace)
            if held is not None:
                return Response(content=json.dumps(held), status_code=423, media_type='application/json')
            conn.execute('UPDATE workspaces SET lock_info=%s WHERE name=%s', (Jsonb(info), workspace))
            _audit(conn, workspace, principal.name, 'state.lock', {'lock_id': _lock_id(info)})
    return Response(status_code=200)


@app.api_route('/state/{workspace}', methods=['UNLOCK'])
async def unlock_state(workspace: str, request: Request):
    principal = authenticate(request, 'write')
    try:
        info = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, 'Invalid lock JSON')
    with db() as conn:
        with conn.transaction():
            _, _, _, held = _workspace_row(conn, workspace)
            if held is None or _lock_id(held) != _lock_id(info):
                return Response(content=json.dumps(held or {}), status_code=409, media_type='application/json')
            conn.execute('UPDATE workspaces SET lock_info=NULL WHERE name=%s', (workspace,))
            _audit(conn, workspace, principal.name, 'state.unlock', {'lock_id': _lock_id(info)})
    return Response(status_code=200)


@app.get('/api/graph/{workspace}')
def get_graph(workspace: str, request: Request):
    authenticate(request, 'read')
    with db() as conn:
        nodes = conn.execute('''SELECT address,resource_type,provider,mode FROM resource_nodes
                                WHERE workspace=%s ORDER BY address''', (workspace,)).fetchall()
        edges = conn.execute('''SELECT source_address,target_address FROM resource_edges
                                WHERE workspace=%s ORDER BY source_address,target_address''', (workspace,)).fetchall()
        metadata_rows = conn.execute('SELECT address FROM resource_versions WHERE workspace=%s AND NOT deleted',
                                     (workspace,)).fetchall()
        lease_rows = conn.execute('''SELECT address,holder::text,expires_at FROM resource_leases
                                    WHERE workspace=%s AND expires_at>now()''', (workspace,)).fetchall()
    result_nodes = [{'address': a, 'type': t, 'provider': p, 'mode': m} for a, t, p, m in nodes]
    indexed = {n['address'] for n in result_nodes}
    result_nodes += [{'address': address, 'type': 'metadata', 'provider': '', 'mode': 'experimental'}
                     for (address,) in metadata_rows if address not in indexed]
    return {'workspace': workspace,
            'nodes': result_nodes,
            'edges': [{'from': a, 'depends_on': b} for a, b in edges],
            'leases': [{'address': a, 'owner': h, 'expires_at': e.isoformat()} for a, h, e in lease_rows]}


@app.get('/api/history/{workspace}')
def state_history(workspace: str, request: Request, limit: int = 50):
    authenticate(request, 'read')
    with db() as conn:
        rows = conn.execute('''SELECT id,serial,lineage,action,actor,created_at
                               FROM state_versions WHERE workspace=%s ORDER BY id DESC LIMIT %s''',
                            (workspace, min(max(limit, 1), 200))).fetchall()
    return {'versions': [{'id': r[0], 'serial': r[1], 'lineage': r[2], 'action': r[3],
                          'actor': r[4], 'created_at': r[5].isoformat()} for r in rows]}


class RestoreRequest(BaseModel):
    history_id: int = Field(gt=0)
    expected_current_serial: int | None = Field(default=None, ge=0)
    # Restores are unsafe when there is a live lock; never auto force-unlock.


@app.post('/api/restore/{workspace}')
def restore_state(workspace: str, payload: RestoreRequest, request: Request):
    principal = authenticate(request, 'restore')
    with db() as conn:
        with conn.transaction():
            _, current_lineage, current_serial, lock_info = _workspace_row(conn, workspace)
            if lock_info is not None:
                raise HTTPException(423, 'Cannot restore while Terraform holds a workspace lock')
            if current_serial != payload.expected_current_serial:
                raise HTTPException(409, 'Expected current serial does not match; refresh history')
            row = conn.execute('''SELECT state_bytes,lineage FROM state_versions
                                  WHERE workspace=%s AND id=%s''', (workspace, payload.history_id)).fetchone()
            if not row or row[0] is None:
                raise HTTPException(404, 'Restorable snapshot not found')
            archived, original_lineage = row
            if current_lineage and original_lineage != current_lineage:
                raise HTTPException(409, 'Historical lineage mismatch')
            state = json.loads(unseal(bytes(archived)))
            # A recovered state MUST move the serial forward, not reset it backward.
            state['serial'] = max(current_serial if current_serial is not None else -1,
                                  int(state['serial'])) + 1
            body = json.dumps(state, separators=(',', ':'), ensure_ascii=False).encode()
            encrypted = seal(body)
            conn.execute('''UPDATE workspaces SET state_bytes=%s,lineage=%s,serial=%s,
                            updated_at=now() WHERE name=%s''',
                         (encrypted, original_lineage, state['serial'], workspace))
            _save_graph(conn, workspace, state)
            version = _archive(conn, workspace, encrypted, original_lineage, state['serial'],
                               principal.name, 'restore')
            _audit(conn, workspace, principal.name, 'state.restore',
                   {'from_history_id': payload.history_id, 'history_id': version, 'serial': state['serial']})
    return {'restored_to': version, 'serial': state['serial'],
            'warning': 'Restores metadata only; verify real cloud objects and run a fresh plan'}


@app.get('/api/audit/{workspace}')
def audit_events(workspace: str, request: Request, limit: int = 100):
    authenticate(request, 'read')
    with db() as conn:
        rows = conn.execute('''SELECT id,actor,event_type,detail,created_at FROM audit_events
                               WHERE workspace=%s ORDER BY id DESC LIMIT %s''',
                            (workspace, min(max(limit, 1), 300))).fetchall()
    return {'events': [{'id': n, 'actor': a, 'event': k, 'detail': d, 'at': t.isoformat()}
                       for n, a, k, d, t in rows]}


@app.get('/api/metrics')
def metrics(request: Request):
    authenticate(request, 'read')
    with db() as conn:
        w, r, o, leases = conn.execute('''SELECT
            (SELECT count(*) FROM workspaces),
            (SELECT count(*) FROM resource_nodes),
            (SELECT count(*) FROM graph_operations),
            (SELECT count(*) FROM resource_leases WHERE expires_at>now())''').fetchone()
    return {'workspaces': w, 'indexed_resources': r, 'graph_operations': o, 'active_graph_leases': leases}


# Graph transaction API: metadata-only graph values, NOT Terraform state provider snapshots.
class PlanRequest(BaseModel):
    workspace: str = Field(min_length=1, max_length=128)
    label: str = Field(default='graph-change', min_length=1, max_length=160)
    read_set: list[str] = Field(default_factory=list, max_length=250)
    write_set: list[str] = Field(min_length=1, max_length=250)
    ttl_seconds: int = Field(default=120, ge=10, le=3600)
    protect_dependents: bool = True

    @model_validator(mode='after')
    def check_addresses(self):
        if any(not valid_resource_address(a) for a in self.read_set + self.write_set):
            raise ValueError('Resource addresses must be nonempty and at most 512 characters')
        return self


class CommitRequest(BaseModel):
    # Dict values are opaque metadata blobs, never Terraform raw state. Null = deletion.
    changes: dict[str, Any] = Field(min_length=1, max_length=250)


class RecoveryRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def _tx_locks(conn, workspace: str, resources: list[str]):
    # Transaction-scoped advisory locks guard absent-row creation as well as updates.
    # Hash collisions only cause extra contention (never permit conflicting changes).
    for address in sorted(set(resources)):
        key = int.from_bytes(hashlib.sha256(f'{workspace}\x00{address}'.encode()).digest()[:8], 'big', signed=True)
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (key,))


def _versions(conn, workspace: str, resources: list[str]) -> dict[str, int]:
    if not resources:
        return {}
    rows = conn.execute('''SELECT address,version FROM resource_versions
                           WHERE workspace=%s AND address=ANY(%s)''', (workspace, resources)).fetchall()
    return {address: next((version for a, version in rows if a == address), 0) for address in resources}


def _live_operation(conn, identifier: uuid.UUID):
    row = conn.execute('''SELECT workspace,actor,status,read_set,write_set,lock_set,
                                 expected_versions,fences,expires_at
                          FROM graph_operations WHERE id=%s FOR UPDATE''', (identifier,)).fetchone()
    if not row:
        raise HTTPException(404, 'Unknown graph operation')
    return row


def _owner_guard(actor: str, principal: Principal):
    if actor != principal.name and principal.role != 'admin':
        raise HTTPException(403, 'Operation belongs to another principal')


def _release_operation_leases(conn, workspace: str, identifier):
    conn.execute('DELETE FROM resource_leases WHERE workspace=%s AND holder=%s', (workspace, identifier))


@app.post('/api/operations/plan')
def plan_graph(payload: PlanRequest, request: Request):
    principal = authenticate(request, 'plan')
    reads, writes = set(payload.read_set), set(payload.write_set)
    identifier = uuid.uuid4()
    expiry = datetime.now(timezone.utc) + timedelta(seconds=payload.ttl_seconds)
    with db() as conn:
        with conn.transaction():
            # Workspaces are inserted once; this does not hold the row during an apply.
            conn.execute('INSERT INTO workspaces(name) VALUES (%s) ON CONFLICT DO NOTHING', (payload.workspace,))
            base = conn.execute('SELECT serial FROM workspaces WHERE name=%s', (payload.workspace,)).fetchone()[0]
            edges = conn.execute('''SELECT source_address,target_address FROM resource_edges
                                    WHERE workspace=%s''', (payload.workspace,)).fetchall()
            protected = impacted_resources(writes, edges, payload.protect_dependents)
            # Capture versions for known prerequisites as well as explicit reads.
            reads |= prerequisite_resources(writes, edges)
            locks = sorted(protected)
            # Block an overlapping operation until an incident is reconciled.
            incidents = conn.execute('''SELECT id::text,write_set FROM graph_operations
                WHERE workspace=%s AND status='recovery_required' ''', (payload.workspace,)).fetchall()
            for incident_id, incident_writes in incidents:
                if protected & set(incident_writes):
                    raise HTTPException(409, detail={'recovery_required': incident_id,
                                                     'message': 'Resolve outstanding recovery before starting'})
            _tx_locks(conn, payload.workspace, locks)
            versions = _versions(conn, payload.workspace, sorted(reads | protected))
            fences = {}
            for address in locks:
                # Expired rows can be claimed; new ownership always advances fence.
                row = conn.execute('''INSERT INTO resource_leases(workspace,address,holder,fence,expires_at)
                    VALUES (%s,%s,%s,nextval('resource_fence_seq'),%s)
                    ON CONFLICT (workspace,address) DO UPDATE
                       SET holder=EXCLUDED.holder,fence=EXCLUDED.fence,expires_at=EXCLUDED.expires_at
                       WHERE resource_leases.expires_at<=now()
                    RETURNING fence''', (payload.workspace, address, identifier, expiry)).fetchone()
                if row is None:
                    raise HTTPException(409, detail={'conflict': address, 'message': 'Resource already reserved'})
                fences[address] = row[0]
            conn.execute('''INSERT INTO graph_operations
                (id,workspace,actor,label,status,read_set,write_set,lock_set,expected_versions,fences,expires_at,base_state_serial)
                VALUES (%s,%s,%s,%s,'planned',%s,%s,%s,%s,%s,%s,%s)''',
                (identifier, payload.workspace, principal.name, payload.label,
                 Jsonb(sorted(reads)), Jsonb(sorted(writes)), Jsonb(locks), Jsonb(versions),
                 Jsonb(fences), expiry, base))
            _audit(conn, payload.workspace, principal.name, 'graph.plan',
                   {'operation_id': str(identifier), 'reads': len(reads), 'writes': len(writes), 'locked': len(locks)})
    return {'operation_id': str(identifier), 'workspace': payload.workspace, 'status': 'planned',
            'read_versions': versions, 'locked_resources': locks, 'fences': fences,
            'expires_at': expiry.isoformat(),
            'note': 'Metadata graph transaction only; no Terraform plan or cloud provider action'}


@app.post('/api/operations/{identifier}/heartbeat')
def heartbeat_graph(identifier: uuid.UUID, request: Request, ttl_seconds: int = 120):
    principal = authenticate(request, 'plan')
    if not 10 <= ttl_seconds <= 3600:
        raise HTTPException(422, 'TTL must be between 10 and 3600 seconds')
    expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with db() as conn:
        with conn.transaction():
            workspace, actor, status, _, _, locks, _, fences, until = _live_operation(conn, identifier)
            _owner_guard(actor, principal)
            if status != 'planned' or until <= datetime.now(timezone.utc):
                raise HTTPException(409, 'Operation no longer active')
            # Fencing check for every held resource. All updates roll back together.
            for address in locks:
                result = conn.execute('''UPDATE resource_leases SET expires_at=%s
                    WHERE workspace=%s AND address=%s AND holder=%s AND fence=%s AND expires_at>now()''',
                    (expiry, workspace, address, identifier, fences[address]))
                if result.rowcount != 1:
                    raise HTTPException(409, 'Lost a lease; operation must be recovered')
            conn.execute('UPDATE graph_operations SET expires_at=%s WHERE id=%s', (expiry, identifier))
    return {'operation_id': str(identifier), 'expires_at': expiry.isoformat()}


@app.post('/api/operations/{identifier}/commit')
def commit_graph(identifier: uuid.UUID, payload: CommitRequest, request: Request):
    principal = authenticate(request, 'plan')
    with db() as conn:
        with conn.transaction():
            workspace, actor, status, reads, writes, locks, expected, fences, until = _live_operation(conn, identifier)
            _owner_guard(actor, principal)
            if status != 'planned' or until <= datetime.now(timezone.utc):
                raise HTTPException(409, 'Operation inactive or expired')
            if set(payload.changes) != set(writes):
                raise HTTPException(422, 'Changes must exactly match the planned write_set')
            if any(not valid_resource_address(address) for address in payload.changes):
                raise HTTPException(422, 'Invalid resource address')
            _tx_locks(conn, workspace, locks)
            for address in locks:
                current = conn.execute('''SELECT 1 FROM resource_leases WHERE workspace=%s AND address=%s
                    AND holder=%s AND fence=%s AND expires_at>now()''',
                    (workspace, address, identifier, fences[address])).fetchone()
                if not current:
                    raise HTTPException(409, f'Lost lease on {address}; commit refused')
            base_row = conn.execute('SELECT base_state_serial FROM graph_operations WHERE id=%s',
                                    (identifier,)).fetchone()
            current_serial = conn.execute('SELECT serial FROM workspaces WHERE name=%s',
                                          (workspace,)).fetchone()[0]
            if current_serial != base_row[0]:
                raise HTTPException(409, 'Terraform state changed since this graph plan; replan required')
            observed = _versions(conn, workspace, list(expected))
            mismatches = conflicting_versions(expected, observed)
            if mismatches:
                raise HTTPException(409, detail={'conflicts': mismatches, 'message': 'Optimistic version check failed'})
            applied = {}
            for address in sorted(writes):
                value = payload.changes[address]
                raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
                if len(raw) > 1_000_000:
                    raise HTTPException(413, 'Graph metadata value exceeds 1MB')
                version = conn.execute('SELECT nextval(\'graph_version_seq\')').fetchone()[0]
                conn.execute('''INSERT INTO resource_versions
                    (workspace,address,version,encrypted_value,deleted,updated_at)
                    VALUES (%s,%s,%s,%s,%s,now())
                    ON CONFLICT(workspace,address) DO UPDATE
                    SET version=EXCLUDED.version, encrypted_value=EXCLUDED.encrypted_value,
                        deleted=EXCLUDED.deleted,updated_at=now()''',
                    (workspace, address, version, seal(raw) if value is not None else None, value is None))
                conn.execute('''INSERT INTO graph_value_history
                    (workspace,address,version,encrypted_value,deleted,operation_id)
                    VALUES (%s,%s,%s,%s,%s,%s)''',
                    (workspace, address, version, seal(raw) if value is not None else None, value is None, identifier))
                applied[address] = version
            conn.execute('''UPDATE graph_operations SET status='committed',finished_at=now() WHERE id=%s''', (identifier,))
            _release_operation_leases(conn, workspace, identifier)
            _audit(conn, workspace, principal.name, 'graph.commit',
                   {'operation_id': str(identifier), 'resource_versions': applied})
    return {'operation_id': str(identifier), 'status': 'committed', 'resource_versions': applied,
            'note': 'No Terraform state snapshot or cloud resource was mutated'}


@app.post('/api/operations/{identifier}/abort')
def abort_graph(identifier: uuid.UUID, request: Request):
    principal = authenticate(request, 'plan')
    with db() as conn:
        with conn.transaction():
            workspace, actor, status, *_ = _live_operation(conn, identifier)
            _owner_guard(actor, principal)
            if status != 'planned':
                raise HTTPException(409, f'Operation is already {status}')
            conn.execute('''UPDATE graph_operations SET status='aborted',finished_at=now() WHERE id=%s''', (identifier,))
            _release_operation_leases(conn, workspace, identifier)
            _audit(conn, workspace, principal.name, 'graph.abort', {'operation_id': str(identifier)})
    return {'status': 'aborted'}


@app.post('/api/operations/{identifier}/recovery-required')
def mark_recovery(identifier: uuid.UUID, payload: RecoveryRequest, request: Request):
    principal = authenticate(request, 'plan')
    with db() as conn:
        with conn.transaction():
            workspace, actor, status, *_ = _live_operation(conn, identifier)
            _owner_guard(actor, principal)
            if status != 'planned':
                raise HTTPException(409, 'Only active operations can be marked for recovery')
            conn.execute('''UPDATE graph_operations SET status='recovery_required',notes=%s,
                            finished_at=now() WHERE id=%s''', (payload.reason, identifier))
            _release_operation_leases(conn, workspace, identifier)
            _audit(conn, workspace, principal.name, 'graph.recovery_required',
                   {'operation_id': str(identifier), 'reason': payload.reason})
    return {'status': 'recovery_required', 'action': 'Review provider effects; reconcile before retry'}


@app.get('/api/operations/{workspace}')
def operations(workspace: str, request: Request, limit: int = 50):
    authenticate(request, 'read')
    with db() as conn:
        rows = conn.execute('''SELECT id::text,label,actor,status,write_set,created_at,expires_at,notes
                               FROM graph_operations WHERE workspace=%s ORDER BY created_at DESC LIMIT %s''',
                            (workspace, min(max(limit, 1), 200))).fetchall()
    return {'operations': [{'id': i, 'label': label, 'actor': actor,
                            'status': 'expired' if status == 'planned' and expires <= datetime.now(timezone.utc) else status,
                            'write_set': ws, 'created_at': created.isoformat(),
                            'expires_at': expires.isoformat(), 'notes': notes}
                           for i, label, actor, status, ws, created, expires, notes in rows]}


@app.get('/api/resources/{workspace}')
def resource_versions(workspace: str, request: Request):
    authenticate(request, 'read')
    with db() as conn:
        rows = conn.execute('''SELECT address,version,deleted,updated_at FROM resource_versions
                               WHERE workspace=%s ORDER BY address''', (workspace,)).fetchall()
    return {'resources': [{'address': a, 'version': v, 'deleted': deleted, 'updated_at': t.isoformat()}
                          for a, v, deleted, t in rows]}


@app.get('/api/resources/{workspace}/{address:path}')
def resource_value(workspace: str, address: str, request: Request):
    authenticate(request, 'read')
    with db() as conn:
        row = conn.execute('''SELECT version,encrypted_value,deleted FROM resource_versions
                              WHERE workspace=%s AND address=%s''', (workspace, address)).fetchone()
    if not row or row[2]:
        raise HTTPException(404, 'Graph resource metadata not found')
    return {'address': address, 'version': row[0], 'value': json.loads(unseal(bytes(row[1])))}


class ReconcileRequest(BaseModel):
    resolution: str = Field(min_length=8, max_length=1000)


@app.post('/api/operations/{identifier}/reconcile')
def reconcile_graph(identifier: uuid.UUID, payload: ReconcileRequest, request: Request):
    principal = authenticate(request, 'admin')
    with db() as conn:
        with conn.transaction():
            workspace, _, status, *_ = _live_operation(conn, identifier)
            if status != 'recovery_required':
                raise HTTPException(409, 'Operation is not awaiting recovery')
            conn.execute("UPDATE graph_operations SET status='reconciled',notes=%s WHERE id=%s",
                         (payload.resolution, identifier))
            _audit(conn, workspace, principal.name, 'graph.reconciled',
                   {'operation_id': str(identifier), 'resolution': payload.resolution})
    return {'status': 'reconciled', 'operator_note': payload.resolution}


@app.get('/api/resource-history/{workspace}/{address:path}')
def graph_resource_history(workspace: str, address: str, request: Request, limit: int = 50):
    authenticate(request, 'read')
    with db() as conn:
        rows = conn.execute('SELECT id,version,deleted,created_at FROM graph_value_history WHERE workspace=%s AND address=%s ORDER BY id DESC LIMIT %s',
                            (workspace, address, min(max(limit, 1), 200))).fetchall()
    return {'history': [{'id': n, 'version': v, 'deleted': deleted, 'created_at': t.isoformat()}
                        for n, v, deleted, t in rows]}


app.include_router(project_console_router)
