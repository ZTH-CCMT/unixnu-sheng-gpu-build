"""Host-only package helpers. No device tools or credentials are read."""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
TOP = Path(os.environ.get('UNIXNU_CI_WORKSPACE', os.environ.get('GITHUB_WORKSPACE', HERE.parent))).resolve()
PINS = {'UniXNU':'f61fd6c1be8a18ec83c4a80bd7355cbf5d435d63','device':'ba66a66089e5bb6690d021344188ca7776932931','uefi-sheng':'66421cb7bb5694843aec8de1ca3d1de4c20cca38'}
PROFILE='ipados-27.0.1-24A446'
SYNTHETIC='13579bdf'
GIB=1024**3
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while b:=f.read(8<<20): h.update(b)
    return h.hexdigest()
def run(*args, cwd=None):
    return subprocess.run([str(a) for a in args],cwd=cwd,check=True)
def capture(*args,cwd=None):
    return subprocess.check_output([str(a) for a in args],cwd=cwd,text=True).strip()
def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2)+'\n')
def context(command='build'):
    sys.path.insert(0,str(TOP/'UniXNU/scripts'))
    from unixnu.cli import parser
    from unixnu.config import Context
    return Context(parser().parse_args([command,'-D',str(TOP/'device'),'--os','27','--uefi',str(TOP/'uefi-sheng')]))
def space(required,reason):
    free=shutil.disk_usage(TOP).free
    print(json.dumps({'disk_free_bytes':free,'required_bytes':required,'reason':reason}))
    if free<required: raise SystemExit('Insufficient current runner space: '+reason+'; no paid runner or deletion fallback is enabled.')
