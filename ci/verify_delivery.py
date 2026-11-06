#!/usr/bin/env python3
# Only step outcomes and artifact IDs; no credentials, artifact content or device input.
import json,os
GROUPS=('handoff','host','quarantine')
def required_groups(steps):
 build=steps.get('build_candidate',{}).get('outcome','skipped')
 host=steps.get('touch_preflight',{}).get('outcome')=='success' or steps.get('delivery_inputs',{}).get('outputs',{}).get('host_present')=='true'
 return {'handoff':build=='success','host':host,'quarantine':build=='failure'}
def acknowledged(step):
 artifact_id=step.get('outputs',{}).get('artifact-id','')
 return step.get('outcome')=='success' and isinstance(artifact_id,str) and artifact_id.isdecimal() and int(artifact_id)>0
def verify(steps):
 required=required_groups(steps);result={}
 for group in GROUPS:
  accepted=[{'try':i,'artifact_id':steps[group+'_try'+str(i)]['outputs']['artifact-id']} for i in range(1,5) if acknowledged(steps.get(group+'_try'+str(i),{}))]
  if required[group] and not accepted:raise RuntimeError('No successful finalized artifact ID for required group: '+group)
  result[group]={'required':required[group],'acknowledged_attempts':accepted}
 # This check does not convert a failed native build into a success.
 return result
if __name__=='__main__':
 result=verify(json.loads(os.environ['DELIVERY_STEPS']))
 for group in result.values():
  for attempt in group['acknowledged_attempts']:
   attempt['artifact_url']='https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']+'/artifacts/'+attempt['artifact_id']
 print(json.dumps({'status':'DELIVERY_ACKS_CONFIRMED_BUILD_OUTCOME_UNCHANGED','groups':result},sort_keys=True))
