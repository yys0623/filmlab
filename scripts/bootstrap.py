"""Install the pinned upstream in an isolated Python environment (requires uv)."""
from pathlib import Path
import json
import os
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
os.chdir(root)
config=json.loads((root/'pipeline/config/default.json').read_text())
upstream=root/'vendor/spektrafilm'
def run(*args):
    subprocess.run(list(args),check=True)
if not upstream.exists():
    run('git','clone','https://github.com/andreavolpato/spektrafilm.git',str(upstream))
if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip():
    raise SystemExit('Upstream has local edits. Preserve them before pinning the checkout.')
run('git','-C',str(upstream),'checkout',config['engine_commit'])
run('uv','venv','.venv','--python','3.13.18')
python=str(root/'.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python'))
run('uv','pip','install','--python',python,'-r','pipeline/requirements.lock')
print('Ready. Run:',python,'-m pipeline.generate --jobs 3')
