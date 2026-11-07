"""Active V3.1 overlay checks against the real patch API, not retired helpers."""
from pathlib import Path
import argparse,hashlib,json,shutil,tempfile,unittest
from unittest.mock import patch
import touch_frame_kind as m
ARGS=None
class ActiveOverlayTests(unittest.TestCase):
 def test_new_model_coverage_headers_are_bound(self):
  for name in ('device/drivers/ShengNovatekTouch/NvtPartialMathInline.h','device/drivers/ShengNovatekTouch/NvtCoverage.h','device/package/TouchAstraProfile.h'):
   self.assertIn(name,m.SPEC['files']);self.assertIsNone(m.SPEC['files'][name]['before'])
 def test_modified_patch_is_rejected(self):
  with tempfile.TemporaryDirectory(dir=ARGS.out.parent) as td:
   root=Path(td);(root/'author-to-touch.patch').write_bytes(b'changed')
   with patch.object(m,'HERE',root),self.assertRaises(RuntimeError):m.apply_touch_patch(root)
 def test_original_source_mismatch_is_rejected(self):
  with tempfile.TemporaryDirectory(dir=ARGS.out.parent) as td:
   root=Path(td);here=root/'ci';here.mkdir();shutil.copyfile(m.HERE/'author-to-touch.patch',here/'author-to-touch.patch')
   with patch.object(m,'HERE',here),self.assertRaises(RuntimeError):m.apply_touch_patch(root)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);ARGS=p.parse_args();ARGS.out.parent.mkdir(parents=True,exist_ok=True)
 result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(ActiveOverlayTests))
 ARGS.out.write_text(json.dumps({'status':'PASS' if result.wasSuccessful() else 'FAIL','tests':result.testsRun,'hardware_verified':False},indent=2)+'\n')
 raise SystemExit(0 if result.wasSuccessful() else 1)
