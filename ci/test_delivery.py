#!/usr/bin/env python3
import unittest
import verify_delivery as m
def step(outcome='success',artifact_id='123'):
 return {'outcome':outcome,'outputs':{'artifact-id':artifact_id}}
def success():
 return {'build_candidate':{'outcome':'success'},'touch_preflight':{'outcome':'success'},'delivery_inputs':{'outputs':{'host_present':'true'}},'handoff_try1':step(),'host_try1':step(artifact_id='124')}
class DeliveryTests(unittest.TestCase):
 def test_normal_success(self):self.assertTrue(m.verify(success())['handoff']['required'])
 def test_continue_on_error_uses_outcome_not_conclusion(self):
  s=success();s['handoff_try1']={'outcome':'failure','conclusion':'success','outputs':{'artifact-id':'123'}}
  with self.assertRaises(RuntimeError):m.verify(s)
 def test_empty_id_not_success(self):
  s=success();s['handoff_try1']=step(artifact_id='')
  with self.assertRaises(RuntimeError):m.verify(s)
 def test_nonnumeric_id_not_success(self):
  for bad in ['0','None','abc']:
   s=success();s['handoff_try1']=step(artifact_id=bad)
   with self.assertRaises(RuntimeError):m.verify(s)
 def test_fourth_try_recovers(self):
  s=success()
  for i in range(1,4):s['handoff_try'+str(i)]=step('failure','')
  s['handoff_try4']=step(artifact_id='999')
  self.assertEqual(m.verify(s)['handoff']['acknowledged_attempts'][0]['try'],4)
 def test_all_four_dns_fail_is_hard_fail(self):
  s=success()
  for i in range(1,5):s['handoff_try'+str(i)]=step('failure','')
  with self.assertRaises(RuntimeError):m.verify(s)
 def test_host_independent_of_handoff(self):
  s=success();s.pop('handoff_try1')
  self.assertTrue(m.required_groups(s)['host'])
  with self.assertRaises(RuntimeError):m.verify(s)
 def test_preflight_success_missing_host_fails(self):
  s=success();s['delivery_inputs']['outputs']['host_present']='false';s.pop('host_try1')
  with self.assertRaises(RuntimeError):m.verify(s)
 def test_failed_preflight_partial_host_required(self):
  s={'touch_preflight':{'outcome':'failure'},'delivery_inputs':{'outputs':{'host_present':'true'}}}
  with self.assertRaises(RuntimeError):m.verify(s)
 def test_early_failure_without_host_does_not_invent_artifact(self):
  self.assertFalse(any(x['required'] for x in m.verify({}).values()))
 def test_native_failure_requires_quarantine_and_preserves_failure(self):
  s={'build_candidate':{'outcome':'failure'},'quarantine_try2':step()}
  self.assertTrue(m.verify(s)['quarantine']['required']);self.assertEqual(s['build_candidate']['outcome'],'failure')
 def test_failed_quarantine_prepare_cannot_fake_delivery(self):
  s={'build_candidate':{'outcome':'failure'},'quarantine_prepare':{'outcome':'failure'}}
  with self.assertRaises(RuntimeError):m.verify(s)
if __name__=='__main__':unittest.main()
