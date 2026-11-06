"""Synthetic V3 exact new-header allowlist tests; no source patching or device I/O."""
import argparse,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import touch_frame_kind as m
HEADERS={'device/drivers/ShengHidInput/NativeHidTouchPlan.h','device/drivers/ShengNovatekTouch/NvtShapeMetricsInline.h'}
ARGS=None
class V3HeaderTests(unittest.TestCase):
 def check_one(self,name,before=None,extra=b''):
  raw=('diff --git a/'+name+' b/'+name+'\nnew file mode 100644\n--- /dev/null\n+++ b/'+name+'\n@@ -0,0 +1 @@\n+/* synthetic */\n').encode()+extra
  with tempfile.TemporaryDirectory(dir=ARGS.out.parent) as td:
   here=Path(td);(here/'author-to-touch.patch').write_bytes(raw)
   spec={'patch_sha256':hashlib.sha256(raw).hexdigest(),'files':{name:{'before':before,'after':'1'*64}}}
   with patch.object(m,'HERE',here),patch.object(m,'SPEC',spec):return m.checked_patch()
 def test_selected_real_overlay_contains_exact_two_new_headers(self):
  self.assertTrue(HEADERS<=m.ALLOWED_RUNTIME and HEADERS<=m.NEW_HEADERS)
  self.assertTrue(HEADERS<=set(m.SPEC['files']))
  for name in HEADERS:self.assertIsNone(m.SPEC['files'][name]['before'])
  self.assertTrue(m.checked_patch())
 def test_both_exact_new_headers_accepted(self):
  for name in HEADERS:self.assertTrue(self.check_one(name))
 def test_runtime_allowlist_removal_rejects_each_header(self):
  for name in HEADERS:
   with patch.object(m,'ALLOWED_RUNTIME',m.ALLOWED_RUNTIME-{name}),self.assertRaises(RuntimeError):self.check_one(name)
 def test_newheader_allowlist_removal_rejects_each_header(self):
  for name in HEADERS:
   with patch.object(m,'NEW_HEADERS',m.NEW_HEADERS-{name}),self.assertRaises(RuntimeError):self.check_one(name)
 def test_lookalike_unlisted_header_rejected(self):
  for name in ['device/drivers/ShengHidInput/NativeHidTouchPlanOther.h','device/drivers/ShengNovatekTouch/NvtShapeMetricsOther.h']:
   with self.assertRaises(RuntimeError):self.check_one(name)
 def test_existing_C_source_cannot_be_declared_new(self):
  with self.assertRaises(RuntimeError):self.check_one('device/drivers/ShengNovatekTouch/NvtProtocol.c')
 def test_traversal_header_rejected(self):
  with self.assertRaises(RuntimeError):self.check_one('device/drivers/ShengHidInput/../NativeHidTouchPlan.h')
 def test_binary_patch_still_rejected(self):
  with self.assertRaises(RuntimeError):self.check_one(sorted(HEADERS)[0],extra=b'GIT binary patch\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'host-test-results/v3-header-allowlist-results.json');ARGS=p.parse_args();ARGS.out.parent.mkdir(parents=True,exist_ok=True)
 result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(V3HeaderTests));record={'status':'PASS_SYNTHETIC_V3_HEADER_ALLOWLIST' if result.wasSuccessful() else 'FAIL','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'no_hardware':True};ARGS.out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record));raise SystemExit(0 if result.wasSuccessful() else 1)
