# Select one exact reviewed V3 overlay, never an A/B/C fallback.
from pathlib import Path,PurePosixPath
import hashlib,json,shutil,sys
here=Path(__file__).resolve().parent
if sys.argv[1:]!=['route-v3']:raise SystemExit('Choose route-v3 only')
source=here.parent/'variants/route-v3'
spec=json.loads((source/'ROUTE.json').read_text())
if (spec['route'],spec['display_version'])!=('route-v3','V3'):raise RuntimeError('V3 route mismatch')
if spec['production_core_hashes']!={'device/drivers/ShengHidInput/NativeHidInput.cpp': 'd53f14c79c52cb6f01f96900a6bbeb3a48c63f881aa884ee01e66c67b03f2e89', 'device/drivers/ShengHidInput/NativeHidTouchPlan.h': 'b11592c16e451d7e37c7e3cb8505503e2737659a3c27648a64ec1016f8b2fd07', 'device/drivers/ShengNovatekTouch/NvtShapeMetricsInline.h': '9b6d755a41819e1f1666a21da183b8e8ed4da9a0f075ca9315caf6f187524ed7', 'device/drivers/ShengNovatekTouch/NvtTouchCore.c': '88905d18ffc6e10d1d275ec969e58338d7c9e9a65b84a0eb3e21c01dfed03b08', 'device/drivers/ShengNovatekTouch/NvtTouchCore.h': '5512daf4af1b713c77c13dcb71a8152aa8ed05b2a01461fd8a730f901e5680c0'}:raise RuntimeError('Reviewed V3 Core identity mismatch')
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
if (fix.get('route'),fix.get('variant'),fix.get('display_version'),fix.get('id'))!=('route-v3','aggressive','V3','touch-v3-spatial-hid-20261106-route-v3'):raise RuntimeError('Lock route/version mismatch')
if fix['patch_sha256']!=hashlib.sha256((source/'author-to-touch.patch').read_bytes()).hexdigest():raise RuntimeError('Lock patch mismatch')
for name,digest in spec['production_core_hashes'].items():
 if fix['files'][name]['after']!=digest:raise RuntimeError('V3 Core source mismatch')
for name in ('os27-update-lock.json','author-to-touch.patch','TOUCH-PATCH-NOTICE.txt','tests'):
 if (here/name).exists():raise RuntimeError('Mixed route output')
for name in ('os27-update-lock.json','author-to-touch.patch','TOUCH-PATCH-NOTICE.txt'):shutil.copyfile(source/name,here/name)
shutil.copytree(source/'tests',here/'tests')
print('Selected route-v3 / V3; exact sealed public sources, no device data.')
