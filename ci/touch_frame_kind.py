"""Apply the reviewed touch-only overlay; compile actual modules before native build."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
LOCK=json.loads((HERE/'os27-update-lock.json').read_text())
SPEC=LOCK['touch_frame_kind_fix']
def digest(b):return hashlib.sha256(b).hexdigest()
def require(ok,why):
 if not ok:raise RuntimeError(why)
def apply_touch_patch(top):
 top=Path(top).resolve();patch=HERE/'author-to-touch.patch'
 require(digest(patch.read_bytes())==SPEC['patch_sha256'],'Touch patch digest mismatch')
 for rel,item in SPEC['files'].items():
  require(rel.startswith(('device/package/','device/drivers/ShengNovatekTouch/','device/drivers/ShengHidInput/')),'Overlay outside touch source')
  p=top/rel;require(p.resolve().is_relative_to(top) and not p.is_symlink(),'Escaped source')
  if item['before'] is None:require(not p.exists(),'New overlay file already exists: '+rel)
  else:require(p.is_file() and digest(p.read_bytes())==item['before'],'Author source differs: '+rel)
 subprocess.run(['git','apply','--check',str(patch)],cwd=top,check=True)
 subprocess.run(['git','apply',str(patch)],cwd=top,check=True)
 for rel,item in SPEC['files'].items():require(digest((top/rel).read_bytes())==item['after'],'Patched source differs: '+rel)
def preflight(top):
 top=Path(top).resolve();parent=Path(os.environ.get('RUNNER_TEMP',HERE/'preflight-work')).resolve();parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='astra-contract-',dir=parent) as name:
  temp=Path(name)
  for rel,item in SPEC['files'].items():
   if item['before'] is None:continue
   p=temp/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(top/rel,p)
  # Untouched source dependencies are also copied and pinned by the runner result.
  for source in sorted((top/'device/drivers/ShengNovatekTouch').glob('*')):
   if source.suffix not in ('.c','.h'):continue
   rel=source.relative_to(top);p=temp/rel
   if not p.exists():p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,p)
  apply_touch_patch(temp);shutil.copytree(HERE/'tests',temp/'tests')
  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(parent),TMP=str(parent),TEMP=str(parent))
  subprocess.run([sys.executable,'-B',str(temp/'tests/run_astra_tests.py'),'--root',str(temp),'--out',str(Path(os.environ.get('ASTRA_PREFLIGHT_OUT',str(HERE/'host-test-results/astra-v3p1-contracts'))).resolve())],check=True,env=env)
if __name__=='__main__':
 require(sys.argv[1:]==['--preflight'],'Expected --preflight')
 preflight(Path(os.environ.get('GITHUB_WORKSPACE',Path.cwd())))
