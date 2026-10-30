"""Central project registry + durable, approval-gated Terraform job queue.

Only a separately authenticated, allowlisted host runner executes Terraform.
No shell expressions or arbitrary commands are accepted by this API.
"""
from __future__ import annotations

import hmac
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from .security import authenticate

router = APIRouter()
_WORKSPACE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
_RUNNER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')
_DIGEST = re.compile(r'^[a-f0-9]{64}$')
ACTIVE = ('queued','running_plan','plan_ready','approved','running_apply','needs_reconciliation')


def db():
    return psycopg.connect(os.environ['DATABASE_URL'])


def agent_auth(request: Request):
    token = os.environ.get('TERRAGRAFT_AGENT_TOKEN', '')
    auth = request.headers.get('authorization', '')
    supplied = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    if not token or len(token) < 24:
        raise HTTPException(503, 'Agent token not configured. Reinstall or repair the local configuration using INSTALL.ps1')
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(401, 'Invalid runner token')


def audit(conn, workspace, actor, event, detail=None):
    conn.execute('INSERT INTO audit_events(workspace,actor,event_type,detail) VALUES (%s,%s,%s,%s)',
                 (workspace, actor, event, Jsonb(detail or {})))


def project_record(row):
    return dict(zip(('id','name','workspace','runner_id','local_path','engine','enabled','created_at'),
                    (str(row[0]), *row[1:7], row[7].isoformat())))


def run_record(row):
    keys = ('id','project_id','status','requestor','approver','plan_digest','config_digest',
            'plan_has_changes','output_text','error_message','created_at','approved_at','finished_at')
    values = (str(row[0]), str(row[1]), *row[2:10],
              row[10].isoformat(), row[11].isoformat() if row[11] else None,
              row[12].isoformat() if row[12] else None)
    return dict(zip(keys, values))


class ProjectNew(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    workspace: str
    runner_id: str
    local_path: str = Field(min_length=2, max_length=1024)
    engine: str = 'terraform'

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError('Project name cannot be blank')
        return value.strip()

    @field_validator('workspace')
    @classmethod
    def valid_workspace(cls, value):
        if not _WORKSPACE.fullmatch(value):
            raise ValueError('Workspace must use letters, digits, underscores, or hyphens')
        return value

    @field_validator('runner_id')
    @classmethod
    def valid_runner(cls, value):
        if not _RUNNER.fullmatch(value):
            raise ValueError('Invalid runner id')
        return value

    @field_validator('engine')
    @classmethod
    def valid_engine(cls, value):
        if value not in ('terraform', 'tofu'):
            raise ValueError('Engine must be terraform or tofu')
        return value

    @field_validator('local_path')
    @classmethod
    def valid_path(cls, value):
        if '\x00' in value or '\r' in value or '\n' in value:
            raise ValueError('Invalid path')
        return value.strip()


@router.get('/console', include_in_schema=False)
def console():
    return FileResponse(Path(__file__).parent / 'static' / 'console.html', headers={
        'Cache-Control':'no-store',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"})


@router.get('/api/projects')
def projects(request: Request):
    authenticate(request, 'admin')
    with db() as conn:
        rows = conn.execute('SELECT id,name,workspace,runner_id,local_path,engine,enabled,created_at FROM managed_projects ORDER BY name').fetchall()
    return {'projects': [project_record(row) for row in rows]}


@router.post('/api/projects', status_code=201)
def register_project(payload: ProjectNew, request: Request):
    principal = authenticate(request, 'admin')
    new_id = uuid.uuid4()
    try:
        with db() as conn:
            with conn.transaction():
                conn.execute('INSERT INTO workspaces(name) VALUES(%s) ON CONFLICT DO NOTHING', (payload.workspace,))
                conn.execute('''INSERT INTO managed_projects
                    (id,name,workspace,runner_id,local_path,engine,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                    (new_id, payload.name.strip(), payload.workspace, payload.runner_id,
                     payload.local_path, payload.engine, principal.name))
                audit(conn, payload.workspace, principal.name, 'project.register',
                      {'project_id':str(new_id),'name':payload.name,'runner':payload.runner_id})
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, 'Project name or workspace already registered')
    return {'id':str(new_id), 'workspace':payload.workspace,
            'note':'Registration does not create or migrate Terraform state. Runner validates the local path.'}


class ToggleProject(BaseModel):
    enabled: bool


@router.patch('/api/projects/{project_id}')
def toggle_project(project_id: uuid.UUID, payload: ToggleProject, request: Request):
    principal = authenticate(request, 'admin')
    with db() as conn:
        with conn.transaction():
            row = conn.execute('''UPDATE managed_projects SET enabled=%s WHERE id=%s RETURNING workspace''',
                               (payload.enabled, project_id)).fetchone()
            if not row:
                raise HTTPException(404, 'Project not found')
            audit(conn, row[0], principal.name, 'project.enable' if payload.enabled else 'project.disable')
    return {'enabled':payload.enabled}


def _expire_stale(conn):
    # An expired apply must NEVER be retried automatically: its cloud-side outcome is unknown.
    conn.execute("""UPDATE managed_runs SET status='needs_reconciliation',
        error_message='Runner heartbeat expired during apply; reconcile cloud/state before new operations',
        finished_at=now() WHERE status='running_apply' AND lease_until<now()""")
    conn.execute("""UPDATE managed_runs SET status='failed',
        error_message='Runner heartbeat expired during plan',finished_at=now()
        WHERE status='running_plan' AND lease_until<now()""")


@router.post('/api/projects/{project_id}/plan', status_code=201)
def request_plan(project_id: uuid.UUID, request: Request):
    principal = authenticate(request, 'admin')
    run_id = uuid.uuid4()
    with db() as conn:
        with conn.transaction():
            _expire_stale(conn)
            project = conn.execute('SELECT workspace,enabled FROM managed_projects WHERE id=%s FOR UPDATE',
                                   (project_id,)).fetchone()
            if not project:
                raise HTTPException(404, 'Project not found')
            workspace, enabled = project
            if not enabled:
                raise HTTPException(409, 'Project disabled')
            exists = conn.execute('SELECT id FROM managed_runs WHERE project_id=%s AND status=ANY(%s)',
                                  (project_id, list(ACTIVE))).fetchone()
            if exists:
                raise HTTPException(409, f'Project has an active/blocked run: {exists[0]}')
            conn.execute('INSERT INTO managed_runs(id,project_id,status,requestor) VALUES(%s,%s,%s,%s)',
                         (run_id, project_id, 'queued', principal.name))
            audit(conn, workspace, principal.name, 'run.queued', {'run_id':str(run_id)})
    return {'run_id':str(run_id),'status':'queued'}


@router.get('/api/runs')
def list_runs(request: Request, project_id: uuid.UUID | None = None, limit: int = 60):
    authenticate(request, 'admin')
    with db() as conn:
        with conn.transaction():
            _expire_stale(conn)
            sql = '''SELECT id,project_id,status,requestor,approver,plan_digest,config_digest,
                     plan_has_changes,output_text,error_message,created_at,approved_at,finished_at
                     FROM managed_runs'''
            if project_id:
                rows = conn.execute(sql+' WHERE project_id=%s ORDER BY created_at DESC LIMIT %s',
                                    (project_id, min(max(limit,1),200))).fetchall()
            else:
                rows = conn.execute(sql+' ORDER BY created_at DESC LIMIT %s',
                                    (min(max(limit,1),200),)).fetchall()
    return {'runs':[run_record(row) for row in rows]}


class Approve(BaseModel):
    digest: str
    confirmation: str


@router.post('/api/runs/{run_id}/approve')
def approve_run(run_id: uuid.UUID, payload: Approve, request: Request):
    principal = authenticate(request, 'admin')
    with db() as conn:
        with conn.transaction():
            row = conn.execute('''SELECT p.workspace,r.status,r.plan_digest
                  FROM managed_runs r JOIN managed_projects p ON p.id=r.project_id
                  WHERE r.id=%s FOR UPDATE OF r''', (run_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Run not found')
            workspace, status, digest = row
            if status != 'plan_ready':
                raise HTTPException(409, 'Run is not awaiting approval')
            if not digest or not hmac.compare_digest(payload.digest, digest):
                raise HTTPException(409, 'Plan digest changed. Reload before approving')
            if payload.confirmation != workspace:
                raise HTTPException(400, 'Type the exact workspace name to approve')
            conn.execute("UPDATE managed_runs SET status='approved',approver=%s,approved_at=now() WHERE id=%s",
                         (principal.name, run_id))
            audit(conn, workspace, principal.name, 'run.approve', {'run_id':str(run_id),'digest':digest})
    return {'status':'approved'}


@router.post('/api/runs/{run_id}/cancel')
def cancel_run(run_id: uuid.UUID, request: Request):
    principal = authenticate(request, 'admin')
    with db() as conn:
        with conn.transaction():
            row = conn.execute('''SELECT p.workspace,r.status FROM managed_runs r
                    JOIN managed_projects p ON p.id=r.project_id WHERE r.id=%s FOR UPDATE OF r''',
                    (run_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Run not found')
            if row[1] not in ('queued','plan_ready','approved'):
                raise HTTPException(409, 'Cannot cancel a running operation. Reconcile if agent is lost.')
            conn.execute("UPDATE managed_runs SET status='canceled',finished_at=now() WHERE id=%s", (run_id,))
            audit(conn, row[0], principal.name, 'run.cancel', {'run_id':str(run_id)})
    return {'status':'canceled'}


class ResolveRequest(BaseModel):
    confirmation: str
    notes: str = Field(min_length=10, max_length=1000)


@router.post('/api/runs/{run_id}/resolve')
def resolve_run(run_id: uuid.UUID, payload: ResolveRequest, request: Request):
    principal = authenticate(request, 'admin')
    with db() as conn:
        with conn.transaction():
            row = conn.execute('''SELECT p.workspace,r.status FROM managed_runs r
                JOIN managed_projects p ON p.id=r.project_id WHERE r.id=%s FOR UPDATE OF r''',
                (run_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Run not found')
            if row[1] != 'needs_reconciliation' or payload.confirmation != row[0]:
                raise HTTPException(409, 'Requires reconciliation state and exact workspace confirmation')
            conn.execute("UPDATE managed_runs SET status='failed',error_message=%s,finished_at=now() WHERE id=%s",
                         ('Manually reconciled: '+payload.notes, run_id))
            audit(conn, row[0], principal.name, 'run.reconcile', {'run_id':str(run_id), 'notes':payload.notes})
    return {'status':'failed'}


class Claim(BaseModel):
    runner_id: str


@router.post('/api/runner/claim')
def claim_job(payload: Claim, request: Request):
    agent_auth(request)
    with db() as conn:
        with conn.transaction():
            _expire_stale(conn)
            row = conn.execute('''SELECT r.id,r.status,p.id,p.name,p.workspace,p.runner_id,p.local_path,p.engine,
                                r.plan_digest,r.config_digest
                FROM managed_runs r JOIN managed_projects p ON p.id=r.project_id
                WHERE p.runner_id=%s AND p.enabled AND r.status IN ('queued','approved')
                ORDER BY r.created_at LIMIT 1 FOR UPDATE OF r SKIP LOCKED''',
                (payload.runner_id,)).fetchone()
            if not row:
                return {'job':None}
            run_id, status, project_id, name, ws, runner_id, path, engine, plan_digest, config_digest = row
            phase = 'plan' if status == 'queued' else 'apply'
            claim_token = uuid.uuid4()
            conn.execute('''UPDATE managed_runs SET status=%s,claim_token=%s,
                lease_until=now()+interval '90 seconds', started_at=coalesce(started_at,now())
                WHERE id=%s''', ('running_'+phase, claim_token, run_id))
            audit(conn, ws, 'runner:'+payload.runner_id, 'run.claim', {'run_id':str(run_id),'phase':phase})
    return {'job':{'run_id':str(run_id),'claim_token':str(claim_token),'phase':phase,
                   'project_id':str(project_id),'name':name,'workspace':ws,'runner_id':runner_id,
                   'local_path':path,'engine':engine,'plan_digest':plan_digest,
                   'config_digest':config_digest}}


class RunnerProgress(BaseModel):
    claim_token: uuid.UUID
    output_text: str = Field(default='', max_length=100_000)


@router.post('/api/runner/{run_id}/heartbeat')
def heartbeat(run_id: uuid.UUID, payload: RunnerProgress, request: Request):
    agent_auth(request)
    with db() as conn:
        with conn.transaction():
            row = conn.execute('''UPDATE managed_runs SET lease_until=now()+interval '90 seconds'
               WHERE id=%s AND claim_token=%s AND status IN ('running_plan','running_apply')
               AND lease_until>=now() RETURNING id''', (run_id,payload.claim_token)).fetchone()
            if not row:
                raise HTTPException(409, 'Lease lost; stop the runner and reconcile before new operations')
    return {'ok':True}


class Finish(BaseModel):
    claim_token: uuid.UUID
    exit_code: int
    output_text: str = Field(default='', max_length=100_000)
    plan_digest: str | None = None
    config_digest: str | None = None
    has_changes: bool | None = None
    error_message: str = Field(default='', max_length=2000)


@router.post('/api/runner/{run_id}/finish')
def finish_job(run_id: uuid.UUID, payload: Finish, request: Request):
    agent_auth(request)
    if payload.plan_digest is not None and not _DIGEST.fullmatch(payload.plan_digest):
        raise HTTPException(400,'Invalid digest')
    if payload.config_digest is not None and not _DIGEST.fullmatch(payload.config_digest):
        raise HTTPException(400,'Invalid config digest')
    with db() as conn:
        with conn.transaction():
            row = conn.execute('''SELECT r.status,p.workspace FROM managed_runs r
                    JOIN managed_projects p ON p.id=r.project_id
                    WHERE r.id=%s AND r.claim_token=%s AND r.lease_until>=now() FOR UPDATE OF r''',
                    (run_id,payload.claim_token)).fetchone()
            if not row:
                raise HTTPException(409, 'Runner claim is no longer valid')
            previous, workspace = row
            if previous == 'running_plan':
                if payload.exit_code == 0 and payload.has_changes is False:
                    status = 'succeeded'
                elif payload.exit_code == 2 and payload.plan_digest and payload.config_digest and payload.has_changes is True:
                    status = 'plan_ready'
                else:
                    status = 'failed'
            elif previous == 'running_apply':
                status = 'succeeded' if payload.exit_code == 0 else 'needs_reconciliation'
            else:
                raise HTTPException(409, 'Run not in progress')
            conn.execute('''UPDATE managed_runs SET status=%s,output_text=%s,error_message=%s,
                    plan_digest=COALESCE(%s,plan_digest),config_digest=COALESCE(%s,config_digest),
                    plan_has_changes=COALESCE(%s,plan_has_changes),claim_token=NULL,lease_until=NULL,
                    finished_at=CASE WHEN %s IN ('succeeded','failed','needs_reconciliation') THEN now() ELSE NULL END
                    WHERE id=%s''', (status,payload.output_text[-100_000:],payload.error_message,
                                    payload.plan_digest,payload.config_digest,payload.has_changes,status,run_id))
            audit(conn,workspace,'runner','run.finish',{'run_id':str(run_id),'phase':previous,
                                                       'result':status,'exit_code':payload.exit_code})
    return {'status':status}
