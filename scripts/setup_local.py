"""Create local credentials and runner configuration; never overwrite an existing .env."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def setup(projects_root: str):
    root = Path(projects_root).expanduser()
    root.mkdir(parents=True,exist_ok=True)
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Projects root is not a directory')
    env_path = ROOT/'.env'
    config_path = ROOT/'.terragraft.local.json'
    if env_path.exists() or config_path.exists():
        raise ValueError('This install is already configured. Use RUN.ps1; credentials were not replaced')
    result = subprocess.run(['python',str(ROOT/'scripts'/'init_env.py')],cwd=ROOT,check=True)
    data = {'projects_root':str(root),'runner_id':'local-win11',
            'url':'http://127.0.0.1:8080'}
    config_path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print('Terragraft configured with projects root:',root)
    print('Credentials saved in .env. Protect and back up this file after creating important state.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--projects-root',required=True)
    args=parser.parse_args()
    setup(args.projects_root)


if __name__=='__main__':
    main()
