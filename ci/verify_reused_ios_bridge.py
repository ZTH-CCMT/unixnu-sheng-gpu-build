#!/usr/bin/env python3
"""Build-only exact bridge-reuse check; never invokes Cargo or compiles code."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
POLICY_SHA='27525374cb022f3cfb17c72049a943a0003776f7b2f351d1e6caa857e8c1a3fc'
def need(ok,why):
    if not ok: raise SystemExit(why)
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''): h.update(block)
    return h.hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',required=True,choices=['ios']);parser.parse_args()
    p=ROOT/'scripts/ios-reuse-policy.json'
    need(sha(p)==POLICY_SHA,'Unreviewed fixed iOS reuse policy')
    policy=json.loads(p.read_bytes())
    receipt=json.loads((ROOT/'build/ci-ios-reuse-receipt.json').read_bytes())
    need(receipt['schema']=='unixnu.frozen-v6-ios-build-reuse-receipt.v1' and
         receipt['status']=='AUTHENTICATED_V6_IOS_BUILD_INPUTS_REUSED_NOT_REBUILT' and
         receipt['policy_sha256']==POLICY_SHA and receipt['required_inputs']==policy['required'] and
         receipt['ios_Turnip_built_in_this_run'] is False and receipt['ios_bridge_built_in_this_run'] is False,
         'Authenticated iOS reuse receipt required; no Cargo fallback')
    origin=receipt['provenance']
    need(origin['repository']==policy['repository'] and origin['source_commit']==policy['source_commit'] and
         origin['run_id']==policy['run_id'] and origin['run_attempt']==1 and origin['artifact_id']==policy['artifact_id'] and
         origin['downloaded_sha256']==policy['archive_sha256'] and origin['github_digest']=='sha256:'+policy['archive_sha256'] and
         origin['authenticated_API_checks'] is True,'Wrong iOS source artifact')
    for name,record in policy['required'].items():
        target=ROOT/name.removeprefix('public-build/')
        need(target.is_file() and not target.is_symlink() and target.stat().st_size==record['bytes'] and
             sha(target)==record['sha256'],'Frozen iOS library/profile changed; refusing build fallback')
    bridge=ROOT/'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a'
    with bridge.open('rb') as stream:need(stream.read(8)==b'!<arch>\n','Bridge AR container changed')
    need(receipt['ios_bridge_AR_target_inventory']==policy['ios_bridge_AR_target_inventory'],'Reviewed AR target proof changed')
    need(sha(ROOT/'build/adreno-metal-bridge/Cargo.lock')==policy['Cargo_lock_sha256'],'Cargo source identity differs')
    print('PASS: authenticated iOS bridge reused, not rebuilt; final plugin link/signature still required',sha(bridge))
if __name__=='__main__':main()
