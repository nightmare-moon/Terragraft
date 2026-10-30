"""Terragraft Windows host runner. ONLY terraform init/plan/saved-plan apply are allowed.

Runs locally: Docker cannot access arbitrary Windows project directories.
Start once from the installation folder with --root pointing to an allowlisted folder.
Do not run against untrusted Terraform repositories: providers and provisioners execute code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
MAX_OUTPUT = 70_000


def read_env(path=ROOT / '.env'):
    settings = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            settings[key] = value
    return settings


class Client:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        if not self.url.startswith(('http://127.0.0.1:', 'http://localhost:', 'https://')):
            raise ValueError('Refusing nonlocal plaintext HTTP connection. Use HTTPS for remote servers')

    def call(self, path, payload):
        request = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(), method='POST',
                    headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)


def assert_project_dir(path: str, root: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError('Registered project path must be absolute on the runner computer')
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError('Project path is not a directory')
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError:
        raise ValueError('Project path is outside the configured allowlisted root')
    if not list(resolved.glob('*.tf')) and not list(resolved.glob('*.tf.json')):
        raise ValueError('No .tf or .tf.json files found in project directory')
    return resolved


def check_http_backend(project: Path, url: str):
    """Fail closed on non-http backend or mismatched existing backend metadata.

    This is a basic guard, not a complete HCL parser; terraform init validates syntax.
    Do not move existing Terraform states automatically.
    """
    sources = '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                        for p in list(project.glob('*.tf')) if p.is_file())
    blocks = re.findall(r'backend\s+"([^"]+)"\s*\{([^{}]*)\}', sources, re.DOTALL)
    if len(blocks) != 1 or blocks[0][0] != 'http':
        raise ValueError('Project requires exactly one terraform { backend "http" {} } block; no automatic migration')
    configured = re.search(r'\baddress\s*=\s*"([^"]+)"', blocks[0][1])
    if configured and configured.group(1).rstrip('/') != url:
        raise ValueError('Hardcoded backend address differs from registered workspace; edit backend.tf first')
    metadata = project / '.terraform' / 'terraform.tfstate'
    if metadata.is_file():
        state = json.loads(metadata.read_text(encoding='utf-8'))
        backend = state.get('backend')
        if backend and (backend.get('type') != 'http' or
                        (backend.get('config') or {}).get('address', '').rstrip('/') != url):
            raise ValueError('Existing .terraform backend metadata points elsewhere. Back up/migrate explicitly first')


def config_digest(project: Path) -> str:
    digest = hashlib.sha256()
    includes = ('.tf', '.tf.json', '.tfvars', '.tfvars.json', '.terraform.lock.hcl')
    files = sorted((p for p in project.iterdir() if p.is_file() and p.name.endswith(includes)),
                   key=lambda p:p.name)
    for file in files:
        digest.update(file.name.encode())
        digest.update(b'\x00')
        digest.update(file.read_bytes())
        digest.update(b'\x00')
    return digest.hexdigest()


def sha256(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hash_.update(chunk)
    return hash_.hexdigest()


def make_tf_env(original, token, url, workspace):
    target = f'{url.rstrip("/")}/state/{workspace}'
    result = original.copy()
    result.update(TF_HTTP_USERNAME='terraform', TF_HTTP_PASSWORD=token,
                  TF_HTTP_ADDRESS=target, TF_HTTP_LOCK_ADDRESS=target,
                  TF_HTTP_UNLOCK_ADDRESS=target, TF_HTTP_LOCK_METHOD='LOCK',
                  TF_HTTP_UNLOCK_METHOD='UNLOCK', TF_IN_AUTOMATION='true', TF_INPUT='false')
    # Avoid inheriting settings pointing at another workspace.
    return result


def execute(command: list[str], workdir: Path, env: dict, client: Client,
            job: dict, timeout_seconds=1800):
    """Capture bounded output, renew server lease, and avoid shell=True."""
    print('Executing:', command[0], command[1], 'in', workdir, flush=True)
    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8', errors='replace') as logfile:
        proc = subprocess.Popen(command, cwd=workdir, env=env, stdout=logfile, stderr=subprocess.STDOUT,
                                shell=False, stdin=subprocess.DEVNULL, text=True)
        start, heartbeat_at, lost = time.monotonic(), time.monotonic(), False
        while proc.poll() is None:
            time.sleep(1)
            now = time.monotonic()
            if now - heartbeat_at >= 15:
                try:
                    client.call(f"/api/runner/{job['run_id']}/heartbeat", {'claim_token':job['claim_token']})
                except Exception as error:
                    print('Runner heartbeat failed; stopping child; manual reconciliation may be required:', error,
                          file=sys.stderr, flush=True)
                    lost = True
                    proc.terminate()
                    break
                heartbeat_at = now
            if now - start > timeout_seconds:
                proc.terminate()
                break
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        logfile.seek(0)
        text = logfile.read()[-MAX_OUTPUT:]
    if lost:
        raise RuntimeError('Lost runner lease while Terraform was running: check state and cloud resources')
    if time.monotonic()-start > timeout_seconds:
        raise RuntimeError('Terraform command timed out. Reconcile before retrying.')
    return proc.returncode, text


def run_job(client: Client, job: dict, root: Path, settings: dict, plan_dir: Path):
    phase = job['phase']
    tf = job['engine']
    if not shutil.which(tf):
        raise ValueError(f'{tf} is not installed or missing from PATH')
    target = f"{client.url}/state/{job['workspace']}"
    project = assert_project_dir(job['local_path'], root)
    check_http_backend(project, target)
    env = make_tf_env(os.environ, settings.get('TERRAGRAFT_WRITER_TOKEN') or settings['TERRAGRAFT_ADMIN_TOKEN'],
                      client.url, job['workspace'])
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plan_dir / (job['run_id']+'.tfplan')
    if phase == 'plan':
        init_args = [tf, 'init','-reconfigure','-input=false','-no-color',
                     '-backend-config=address='+target,
                     '-backend-config=lock_address='+target,
                     '-backend-config=unlock_address='+target,
                     '-backend-config=lock_method=LOCK',
                     '-backend-config=unlock_method=UNLOCK']
        init_code, init_output = execute(init_args, project, env, client, job, timeout_seconds=600)
        if init_code:
            return {'exit_code':init_code,'output_text':init_output,'error_message':'terraform init failed'}
        config = config_digest(project)
        code, out = execute([tf,'plan','-input=false','-no-color','-lock-timeout=30s',
                             '-detailed-exitcode','-out='+str(plan_file)],project,env,client,job)
        output = (init_output[-5000:]+'\n'+out)[-MAX_OUTPUT:]
        if code == 2 and plan_file.is_file():
            return {'exit_code':2,'output_text':output,'plan_digest':sha256(plan_file),
                    'config_digest':config,'has_changes':True}
        if plan_file.exists(): plan_file.unlink()
        return {'exit_code':code,'output_text':output,'has_changes':False,
                'error_message':'' if code == 0 else 'Terraform plan failed'}
    if phase == 'apply':
        if not plan_file.is_file() or sha256(plan_file) != job['plan_digest']:
            raise RuntimeError('Saved plan file missing/modified. Cancel and request a fresh plan.')
        if config_digest(project) != job['config_digest']:
            raise RuntimeError('Root Terraform configuration changed since planning. Reconcile and re-plan.')
        code, output = execute([tf,'apply','-input=false','-no-color','-lock-timeout=30s',
                                str(plan_file)], project, env, client, job)
        if code == 0:
            plan_file.unlink(missing_ok=True)
        return {'exit_code':code,'output_text':output,
                'error_message':'' if code == 0 else 'Apply failed; inspect actual resources/state before retrying'}
    raise ValueError('Unsupported job phase')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='Trusted parent folder containing Terraform projects')
    parser.add_argument('--runner-id', default='local-win11')
    parser.add_argument('--url', default='http://localhost:8080')
    parser.add_argument('--once', action='store_true', help='Poll once and quit (useful for troubleshooting)')
    args = parser.parse_args()
    settings = read_env()
    client = Client(args.url, settings['TERRAGRAFT_AGENT_TOKEN'])
    root = Path(args.root).resolve(strict=True)
    if not root.is_dir(): raise SystemExit('--root must be a directory')
    plan_dir = Path.home() / '.terragraft' / 'plans' / args.runner_id
    print('Terragraft runner',args.runner_id,'ready. Allowlisted root:',root,flush=True)
    print('Projects must have terraform { backend "http" {} }. No automatic state migration.',flush=True)
    while True:
        try:
            job = client.call('/api/runner/claim', {'runner_id':args.runner_id})['job']
            if job:
                print('Claimed', job['phase'], 'for',job['name'],job['run_id'],flush=True)
                try:
                    outcome = run_job(client, job, root, settings, plan_dir)
                except Exception as error:
                    # Failed apply must enter needs_reconciliation; never rerun automatically.
                    outcome = {'exit_code':1,'output_text':'','error_message':str(error)[:1800]}
                    print('Operation failed:',error,file=sys.stderr,flush=True)
                try:
                    result = client.call(f"/api/runner/{job['run_id']}/finish",
                                         {'claim_token':job['claim_token'],**outcome})
                    print('Run status:',result['status'],flush=True)
                except Exception as error:
                    print('Cannot report status; check API and reconcile run:',error,file=sys.stderr,flush=True)
            elif not args.once:
                time.sleep(3)
        except (urllib.error.URLError, ValueError, KeyError) as error:
            print('Runner connection/config error:',error,file=sys.stderr,flush=True)
            if not args.once: time.sleep(8)
        if args.once: break


if __name__ == '__main__':
    main()
