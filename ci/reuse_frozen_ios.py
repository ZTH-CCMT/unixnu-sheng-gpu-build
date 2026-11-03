"""Authenticated v6 iOS build-input reuse. No Cargo/Mesa fallback or runtime patch."""
import hashlib, importlib.util, json, os, platform, shutil, signal, sys, tempfile
from pathlib import Path

POLICY_SHA = '27525374cb022f3cfb17c72049a943a0003776f7b2f351d1e6caa857e8c1a3fc'
CALLBACK_SHA = 'c6e4039baea329f7c96a8e2cc277ff9c9f202691f73bafb2001a3655570307b3'
IO_HELPER_SHA = 'ba2794d0ed4717505ef6e0edd8fdd579c1ce128f6f334f02eb00cb85daae586f'
TURNIP = 'public-build/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib'
BRIDGE = 'public-build/build/adreno-metal-bridge/ios/libadreno_metal_bridge.a'
PROFILE = 'public-build/build/mesa-tu-ios/builtin-build-profile.json'
PLUGIN_BEFORE = 'f778be6956f3c4ce28a6f13c4a57aa326350985ace5225faf8ff9f9e809f5d33'
PLUGIN_AFTER = '95a5209bd5755a907b537550ae86abaa991b3d77061bdb1a16d23ef9a7ea07ef'
OLD_CALL = "subprocess.run(['python3', ROOT / 'scripts/build-adreno-metal-bridge.py', '--target', BRIDGE_TARGET], check=True)"
NEW_CALL = "subprocess.run(['python3', ROOT / 'scripts/verify-reused-ios-bridge.py', '--target', BRIDGE_TARGET], check=True)"

def need(ok, reason):
    if not ok: raise RuntimeError(reason)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2), b''): h.update(block)
    return h.hexdigest()

def policy():
    p=Path(__file__).with_name('ios-reuse-policy.json')
    need(sha(p)==POLICY_SHA, 'Unreviewed iOS reuse policy')
    return json.loads(p.read_bytes())

def io_helper():
    p=Path(__file__).with_name('reuse_frozen_host.py')
    need(sha(p)==IO_HELPER_SHA, 'Reviewed host IO helper changed')
    spec=importlib.util.spec_from_file_location('reviewed_io_for_ios_reuse',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def verify_frozen_ios_inputs(root, receipt):
    root=Path(root).resolve(strict=True);p=policy();io=io_helper()
    need(receipt['status']=='AUTHENTICATED_V6_IOS_BUILD_INPUTS_REUSED_NOT_REBUILT' and
         receipt['policy_sha256']==POLICY_SHA and receipt['required_inputs']==p['required'] and
         receipt['ios_Turnip_built_in_this_run'] is False and receipt['ios_bridge_built_in_this_run'] is False,
         'iOS reuse receipt scope changed')
    origin=receipt['provenance']
    need(origin['repository']==p['repository'] and origin['source_commit']==p['source_commit'] and
         origin['run_id']==p['run_id'] and origin['run_attempt']==p['run_attempt'] and
         origin['artifact_id']==p['artifact_id'] and origin['github_digest']=='sha256:'+p['archive_sha256'] and
         origin['downloaded_sha256']==p['archive_sha256'] and origin['authenticated_API_checks'] is True,
         'iOS source provenance changed')
    for name,record in p['required'].items():
        target=root/name.removeprefix('public-build/')
        need(target.is_file() and not target.is_symlink() and target.stat().st_size==record['bytes'] and sha(target)==record['sha256'],
             'Authenticated iOS build input changed')
    driver=root/TURNIP.removeprefix('public-build/')
    need(io.facts(driver)==p['required'][TURNIP]['macho'], 'Raw iOS Turnip target changed')
    bridge=root/BRIDGE.removeprefix('public-build/')
    with bridge.open('rb') as stream: need(stream.read(8)==b'!<arch>\n','iOS bridge is not the reviewed AR')
    profile=json.loads((root/PROFILE.removeprefix('public-build/')).read_bytes())
    need(profile==p['ios_profile'] and hashlib.sha256(json.dumps(profile['profile'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==profile['source_id'],
         'iOS compiler profile changed')
    lock=root/'build/adreno-metal-bridge/Cargo.lock'
    need(lock.is_file() and sha(lock)==p['Cargo_lock_sha256'], 'Current host/iOS Cargo lock mismatch')
    for relative,expected in p['current_GOP_headers'].items():
        need(sha(root/relative)==expected,'Pinned GOP dependency header changed')
    return True

def prepare_frozen_ios(root, logs, artifact_token):
    root=Path(root).resolve(strict=True);logs=Path(logs).resolve(strict=True)
    need(platform.system()=='Darwin' and platform.machine()=='arm64','Real macOS ARM64 required')
    p=policy();io=io_helper()
    need(p['run_attempt']==1 and bool(artifact_token),'Fixed v6 attempt1 artifact token required')
    sdk=io.command(['xcrun','--sdk','iphoneos','--show-sdk-version'],logs/'ios-reuse-current-sdk.log')
    compiler=io.command(['/usr/bin/clang++','--version'],logs/'ios-reuse-current-compiler.log')
    need(sdk==p['iphoneos_sdk_version'] and compiler==p['ios_profile']['profile']['compiler'],'iOS source/current toolchain mismatch')
    scratch=Path(tempfile.mkdtemp(prefix='ios-reuse-source-',dir=root.parent))
    archive=scratch/'fixed-v6-attempt1.zip'
    def expired(signum,frame): raise RuntimeError('Fixed iOS artifact reception deadline exceeded')
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(180)
    try: provenance=io.download(p,artifact_token,archive)
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous);artifact_token=None
    restored,missing=io.restore(p,archive,root)
    need(missing==[] and set(restored)==set(p['required']),'iOS restore incomplete')
    # Exact SHA binds the complete375-member archive independently parsed twice.
    # No claim that a member parser or a final iOS link ran in this function.
    bridge=restored[BRIDGE]
    with bridge.open('rb') as stream: need(stream.read(8)==b'!<arch>\n','Bridge AR magic differs')
    receipt=dict(schema='unixnu.frozen-v6-ios-build-reuse-receipt.v1',
        status='AUTHENTICATED_V6_IOS_BUILD_INPUTS_REUSED_NOT_REBUILT',
        provenance=provenance,policy_sha256=POLICY_SHA,required_inputs=p['required'],
        source_recovery_manifest_sha256=p['manifest_sha256'],
        ios_profile_sha256=p['required'][PROFILE]['sha256'],ios_profile_source_id=p['ios_profile']['source_id'],
        Cargo_lock_sha256=p['Cargo_lock_sha256'],current_iphoneos_sdk_version=sdk,current_apple_compiler=compiler,
        ios_Turnip_built_in_this_run=False,ios_bridge_built_in_this_run=False,
        raw_iOS_Turnip_signature='NONE_IN_SOURCE_EXPECTED_FINAL_BUNDLE_COPY_MUST_BE_SIGNED_THIS_RUN',
        ios_bridge_AR_target_inventory=p['ios_bridge_AR_target_inventory'],
        independent_AR_target_review_sha256=p['independent_AR_target_review_sha256'],
        AR_member_target_inventory_bound_by_exact_archive_SHA=True,AR_member_parser_reexecuted_this_run=False,
        hardware_GPU_execution_verified=False,installation_ready=False)
    verify_frozen_ios_inputs(root,receipt)
    for target in restored.values(): target.chmod(0o444)
    io.write_json(root/'build/ci-ios-reuse-receipt.json',receipt)
    io.write_json(logs/'ios-build-reuse.json',receipt)
    return receipt

def apply_plugin_bridge_reuse(root):
    root=Path(root).resolve(strict=True);p=policy()
    builder=root/'scripts/build-adreno-metal-plugin.py'
    need(sha(builder)==PLUGIN_BEFORE,'Original plugin build script changed')
    original=builder.read_text()
    need(original.count(OLD_CALL)==1,'Bridge build invocation is not the reviewed single command')
    patched=original.replace(OLD_CALL,NEW_CALL,1).encode()
    need(hashlib.sha256(patched).hexdigest()==PLUGIN_AFTER,'Plugin build-only replacement differs')
    callback=Path(__file__).with_name('verify_reused_ios_bridge.py')
    policy_source=Path(__file__).with_name('ios-reuse-policy.json')
    need(sha(callback)==CALLBACK_SHA and sha(policy_source)==POLICY_SHA,'iOS reuse callback/policy changed')
    targets=[(callback,root/'scripts/verify-reused-ios-bridge.py'),(policy_source,root/'scripts/ios-reuse-policy.json')]
    for source,target in targets:
        need(not target.exists() and not target.is_symlink(),'Refuse existing adapter target')
        with target.open('xb') as sink: sink.write(source.read_bytes())
    builder.write_bytes(patched)
    return {'scripts/build-adreno-metal-plugin.py':PLUGIN_AFTER,
            'scripts/verify-reused-ios-bridge.py':CALLBACK_SHA,
            'scripts/ios-reuse-policy.json':POLICY_SHA}
