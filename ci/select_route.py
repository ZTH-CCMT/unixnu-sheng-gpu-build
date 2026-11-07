# Validate this self-contained V3.1 candidate; no older variant is copied.
from pathlib import Path
import hashlib,json,sys
here=Path(__file__).resolve().parent
if sys.argv[1:]!=['route-v3p1']:raise SystemExit('Choose route-v3p1 only')
lock=json.loads((here/'os27-update-lock.json').read_text(encoding='utf-8'))
spec=lock['touch_frame_kind_fix']
if (spec.get('route'),spec.get('display_version'),spec.get('id'))!=('route-v3p1','V3.1','touch-astra-v3p1-continuous-20261107'):raise RuntimeError('Candidate route/version mismatch')
if hashlib.sha256((here/'author-to-touch.patch').read_bytes()).hexdigest()!=spec['patch_sha256']:raise RuntimeError('Candidate patch mismatch')
print('Selected self-contained route-v3p1 / V3.1; no source substitution.')
