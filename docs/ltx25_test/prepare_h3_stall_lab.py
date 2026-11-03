"""Prepare (never launch) an isolated one-variable H3 prefetch diagnostic."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / 'config.local.json').read_text())
LAB = ROOT / '.runtime' / 'h3-stall-lab'
SOURCE = Path(CONFIG['comfy']['root'])
DEST = LAB / 'comfyui'
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.git', '.pytest_cache')


def copy_tree(source, dest):
    shutil.copytree(source, dest, dirs_exist_ok=True, ignore=IGNORE)


DEST.mkdir(parents=True, exist_ok=True)
for file in SOURCE.iterdir():
    if file.is_file() and file.suffix in {'.py', '.json', '.ini', '.yaml', '.yml', '.toml', '.txt'}:
        shutil.copy2(file, DEST / file.name)
for name in ('alembic_db', 'api_server', 'app', 'blueprints', 'comfy', 'comfy_api',
             'comfy_api_nodes', 'comfy_config', 'comfy_execution', 'comfy_extras',
             'middleware', 'utils', 'web'):
    if (SOURCE / name).is_dir():
        copy_tree(SOURCE / name, DEST / name)
for name in ('ComfyUI-KJNodes', 'ComfyUI-PlagueKind-Nodes-only-sparse'):
    copy_tree(SOURCE / 'custom_nodes' / name, DEST / 'custom_nodes' / name)

# A separate venv reuses the already-installed packages read-only. Installs in
# this venv cannot write to either original runtime's site-packages directory.
site = LAB / '.venv' / 'Lib' / 'site-packages'
dependencies = [Path(CONFIG['comfy']['python']).parents[1] / 'Lib' / 'site-packages',
                Path(CONFIG['app']['python']).parents[1] / 'Lib' / 'site-packages']
(site / 'existing-runtime-dependencies.pth').write_text(
    '\n'.join(str(p) for p in dependencies) + '\n', encoding='utf-8')

# Copy the bridge too: all experimental source/workflow/DB writes stay in LAB.
copy_tree(ROOT / 'backend', LAB / 'backend')
copy_tree(ROOT / 'dist', LAB / 'dist')
copy_tree(ROOT / 'state' / 'h3-new-flow' / 'official', LAB / 'state' / 'h3-new-flow' / 'official')
comfy = LAB / 'backend' / 'comfy.py'
text = comfy.read_text(encoding='utf-8')
old = '"--enable-dynamic-vram", "--async-offload", "2",'
assert text.count(old) == 1
comfy.write_text(text.replace(old, '"--enable-dynamic-vram", "--disable-async-offload",'), encoding='utf-8')

config = {
    'runtime_root': str(LAB),
    'app': {'host': '127.0.0.1', 'port': 8788, 'python': str(LAB / '.venv' / 'Scripts' / 'python.exe')},
    'comfy': {'host': '127.0.0.1', 'port': 8190, 'root': str(DEST),
              'python': str(LAB / '.venv' / 'Scripts' / 'python.exe'),
              'models': CONFIG['comfy']['models'],
              **{key: str(LAB / 'state' / key) for key in ('input', 'output', 'temp', 'user')}},
    'tailscale': {'enabled': False},
}
(LAB / 'config.local.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
(LAB / 'experiment.json').write_text(json.dumps({
    'status': 'prepared_not_started', 'only_compute_change': '--disable-async-offload replaces --async-offload 2',
    'dynamic_vram': 'enabled', 'pinned_memory': 'unchanged',
    'job': 'Same opening, prompt, seed, 1.5 MP, eight seconds, six steps, Fused SLA Direct',
    'original_runtime': str(SOURCE), 'original_environment_modified': False,
    'run_condition': 'User approves stopping busy original ComfyUI; no simultaneous instances',
    'bridge_command': [str(LAB / '.venv' / 'Scripts' / 'python.exe'), '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8788'],
    'working_directory': str(LAB),
}, indent=2), encoding='utf-8')
print(json.dumps({'prepared': str(LAB), 'started': False}))
