"""Select one immutable generic source overlay in a fresh cloud workspace."""
from pathlib import Path
import hashlib,json,shutil,sys
here=Path(__file__).resolve().parent
if len(sys.argv)!=2 or sys.argv[1] not in ('route-a','route-b','route-c'):raise SystemExit('Choose one sealed touch route')
source=here.parent/'variants'/sys.argv[1]
spec=json.loads((source/'ROUTE.json').read_text())
if spec['route']!=sys.argv[1]:raise RuntimeError('Route mismatch')
all_paths=list(source.rglob('*'))
if any(p.is_symlink() for p in all_paths):raise RuntimeError('Linked route member')
actual={p.relative_to(source).as_posix() for p in all_paths if p.is_file()}
if actual!=set(spec['public_files'])|{'ROUTE.json'}:raise RuntimeError('Unlisted or missing route member')
lock=json.loads((source/'os27-update-lock.json').read_text())
fix=lock['touch_frame_kind_fix']
if fix.get('route')!=sys.argv[1] or fix.get('variant')!='aggressive':raise RuntimeError('Lock route mismatch')
if fix['patch_sha256']!=hashlib.sha256((source/'author-to-touch.patch').read_bytes()).hexdigest():raise RuntimeError('Lock patch mismatch')
for name,item in spec['public_files'].items():
 p=source/name
 if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(source.resolve()):raise RuntimeError('Linked route input')
 if p.stat().st_size!=item['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Route hash mismatch: '+name)
for name in ('os27-update-lock.json','author-to-touch.patch','TOUCH-PATCH-NOTICE.txt'):
 if (here/name).exists():raise RuntimeError('Mixed route output')
 shutil.copyfile(source/name,here/name)
if (here/'tests').exists():raise RuntimeError('Mixed route tests')
shutil.copytree(source/'tests',here/'tests')
print('Selected '+sys.argv[1]+': exact sealed public-source touch overlay; no device data.')
