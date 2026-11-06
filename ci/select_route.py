# Select one exact reviewed V2 overlay, never an A/B/C fallback.
from pathlib import Path,PurePosixPath
import hashlib,json,shutil,sys
here=Path(__file__).resolve().parent
if sys.argv[1:]!=['route-v2']:raise SystemExit('Choose route-v2 only')
source=here.parent/'variants/route-v2'
spec=json.loads((source/'ROUTE.json').read_text())
if (spec['route'],spec['display_version'])!=('route-v2','V2'):raise RuntimeError('V2 route mismatch')
if spec['production_core_hashes']!={'device/drivers/ShengNovatekTouch/NvtTouchCore.c': 'dfe424e8582d392e46245951f64a7a8e61e55592fbfe181c6f3da24383ff9207', 'device/drivers/ShengNovatekTouch/NvtTouchCore.h': '6489771d5ece805a791c067656940fc2e382ec2ea5e6d644abd33b1977964b6f'}:raise RuntimeError('Reviewed V2 Core identity mismatch')
all_paths=list(source.rglob('*'))
if (here.parent/'variants').is_symlink() or source.is_symlink() or not source.resolve().is_relative_to(here.parent.resolve()) or any(p.is_symlink() for p in all_paths):raise RuntimeError('Linked/escaped route member')
actual={p.relative_to(source).as_posix() for p in all_paths if p.is_file()}
if actual!=set(spec['public_files'])|{'ROUTE.json'}:raise RuntimeError('Unlisted or missing route member')
for name,item in spec['public_files'].items():
 q=PurePosixPath(name)
 if q.is_absolute() or '..' in q.parts or '\\' in name or ':' in name:raise RuntimeError('Unsafe route member')
 p=source/name
 if not p.resolve().is_relative_to(source.resolve()) or p.is_symlink() or not p.is_file():raise RuntimeError('Linked/escaped route input')
 if p.stat().st_size!=item['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Route hash mismatch: '+name)
lock=json.loads((source/'os27-update-lock.json').read_text());fix=lock['touch_frame_kind_fix']
if (fix.get('route'),fix.get('variant'),fix.get('display_version'),fix.get('id'))!=('route-v2','aggressive','V2','touch-v2-confidence-follow-20261106-route-v2'):raise RuntimeError('Lock route/version mismatch')
if fix['patch_sha256']!=hashlib.sha256((source/'author-to-touch.patch').read_bytes()).hexdigest():raise RuntimeError('Lock patch mismatch')
for name,digest in spec['production_core_hashes'].items():
 if fix['files'][name]['after']!=digest:raise RuntimeError('V2 Core source mismatch')
for name in ('os27-update-lock.json','author-to-touch.patch','TOUCH-PATCH-NOTICE.txt','tests'):
 if (here/name).exists():raise RuntimeError('Mixed route output')
for name in ('os27-update-lock.json','author-to-touch.patch','TOUCH-PATCH-NOTICE.txt'):shutil.copyfile(source/name,here/name)
shutil.copytree(source/'tests',here/'tests')
print('Selected route-v2 / V2; exact sealed public sources, no device data.')
