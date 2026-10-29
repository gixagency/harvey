"""Refresh application code while retaining configuration, database and logins."""
import os
from pathlib import Path
import shutil
import sys

source = Path('/opt/harvey')
volume = Path(os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '/state'))
if not volume.is_mount():
    raise SystemExit('Attach a Railway volume at /state before starting Harvey.')
token = os.environ.get('HARVEY_ACCESS_TOKEN', '')
import re
if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
    raise SystemExit('HARVEY_ACCESS_TOKEN must be 43–128 URL-safe characters.')
root = volume / 'harvey'
root.mkdir(mode=0o700, parents=True, exist_ok=True)
for name in ('harvey', 'prompts', 'skills', 'deploy'):
    destination = root / name
    if destination.exists() and name in ('prompts', 'skills'):
        continue  # Retain the operator's trained sales knowledge.
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source / name, destination)
config = root / 'harvey.yaml'
if not config.exists():
    shutil.copy2(source / 'deploy' / 'gix.example.yaml', config)
data = root / 'data'
data.mkdir(mode=0o700, exist_ok=True)
token_file = data / 'dashboard-token'
# Never print the unlock token to deployment logs.
fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w') as out:
    out.write(token)
os.environ['HOME'] = str(volume / 'home')
os.environ['CODEX_HOME'] = str(volume / 'home' / '.codex')
Path(os.environ['CODEX_HOME']).mkdir(mode=0o700, parents=True, exist_ok=True)
os.chdir(root)
# Prepare the researched pilot exactly once, with outbound held throughout.
sys.path.insert(0, str(root))
import asyncio
from harvey.launch_setup import prepare
asyncio.run(prepare(root))
# No heartbeat is started automatically. Operator starts it in the dashboard.
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'deploy.railway_gateway:app', '--app-dir', str(root), '--host', '0.0.0.0', '--port', os.environ.get('PORT', '8080'), '--no-proxy-headers', '--no-access-log'])
