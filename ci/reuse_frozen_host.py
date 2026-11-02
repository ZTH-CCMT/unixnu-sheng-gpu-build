#!/usr/bin/env python3
"""Authenticated C6 host-build reuse; retains all full-suite control commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

POLICY_SHA = '24bae8d8418a12cb542e1ebc95e95399c7c921518750b1f5027ed75bcb4c75bb'
CHUNK = 1024**2

def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            h.update(block)
    return h.hexdigest()

def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def metadata(url, token):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        need(response.status == 200, 'GitHub metadata status mismatch')
        data = response.read(2 * CHUNK + 1)
        need(len(data) <= 2 * CHUNK, 'GitHub metadata exceeds bound')
    return json.loads(data)

def download(policy, token, path):
    base = 'https://api.github.com/repos/' + policy['repository']
    run = metadata(base + '/actions/runs/' + str(policy['run_id']), token)
    need(run['id'] == policy['run_id'] and run['head_sha'] == policy['source_commit'] and run['run_attempt'] == 1 and
         run['status'] == 'completed' and run['conclusion'] == 'failure' and
         run['repository']['full_name'] == policy['repository'], 'Source run provenance mismatch')
    item = metadata(base + '/actions/artifacts/' + str(policy['artifact_id']), token)
    need(item['id'] == policy['artifact_id'] and item['name'] == policy['artifact_name'] and
         item['size_in_bytes'] == policy['archive_bytes'] and item['expired'] is False and
         item['digest'] == 'sha256:' + policy['archive_sha256'] and
         item['workflow_run']['id'] == policy['run_id'], 'Artifact provenance mismatch')
    url = base + '/actions/artifacts/' + str(policy['artifact_id']) + '/zip'
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    try:
        response = urllib.request.build_opener(NoRedirect()).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        need(error.code == 302, 'Artifact download API did not return expected redirect')
        location = error.headers.get('Location', '')
        error.close()
        parts = urllib.parse.urlsplit(location)
        need(parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password and
             parts.port in (None, 443), 'Unsafe artifact download redirect')
        # Never forward the GitHub bearer token to the API-supplied signed asset URL.
        response = urllib.request.build_opener(NoRedirect()).open(location, timeout=30)
    with response:
        need(response.status == 200, 'Artifact body response status mismatch')
        length = response.headers.get('Content-Length')
        need(length is None or int(length) == policy['archive_bytes'], 'Artifact Content-Length mismatch')
        h, count = hashlib.sha256(), 0
        with path.open('xb') as sink:
            while True:
                block = response.read(min(CHUNK, policy['archive_bytes'] - count + 1))
                if not block:
                    break
                count += len(block)
                need(count <= policy['archive_bytes'], 'Artifact body exceeds fixed bound')
                sink.write(block)
                h.update(block)
    need(count == policy['archive_bytes'] and h.hexdigest() == policy['archive_sha256'], 'Artifact ZIP digest mismatch')
    return dict(repository=policy['repository'], source_commit=run['head_sha'], run_id=run['id'],
                run_attempt=run['run_attempt'], artifact_id=item['id'], artifact_name=item['name'],
                github_digest=item['digest'], downloaded_sha256=h.hexdigest(), authenticated_API_checks=True)

def facts(path):
    raw = path.read_bytes()
    need(len(raw) >= 32, 'Short Mach-O')
    magic, cpu, subtype, filetype, count, extent = struct.unpack_from('<6I', raw)
    need((magic, cpu, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 0), 'Expected ordinary ARM64')
    need(count < 4096 and 32 + extent <= len(raw), 'Mach-O load commands outside file')
    result = dict(filetype=filetype, builds=[], dependencies=[], rpaths=[])
    offset = 32
    for _ in range(count):
        cmd, length = struct.unpack_from('<II', raw, offset)
        need(length >= 8 and length % 8 == 0 and offset + length <= 32 + extent, 'Bad Mach-O load command')
        if cmd == 0x32:
            result['builds'].append(list(struct.unpack_from('<III', raw, offset + 8)))
        if cmd in (0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023, 0x8000001c):
            nameoff = struct.unpack_from('<I', raw, offset + 8)[0]
            need(8 <= nameoff < length, 'Bad Mach-O dependency offset')
            name = raw[offset + nameoff:offset + length].split(b'\0', 1)[0].decode()
            result['rpaths' if cmd == 0x8000001c else 'dependencies'].append(name)
        offset += length
    need(offset == 32 + extent, 'Mach-O command length mismatch')
    return result

def restore(policy, archive, work):
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        need(len(infos) == len(policy['expected_zip_names']) and len(infos) < 128, 'Unexpected ZIP entry count')
        names = [x.filename for x in infos]
        need(len(set(n.casefold() for n in names)) == len(names) and set(names) == set(policy['expected_zip_names']),
             'ZIP entry set changed or collided')
        need(sum(x.file_size for x in infos) <= 2 * 1024**3, 'ZIP expanded size exceeds2GiB warm bound')
        for item in infos:
            need(item.filename == item.orig_filename and not item.filename.startswith('/') and
                 '\\' not in item.filename and ':' not in item.filename and
                 all(p not in ('', '.', '..') for p in item.filename.split('/')), 'Unsafe ZIP filename')
            need(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG) and not item.is_dir() and
                 not item.flag_bits & 1 and item.compress_type in (0, 8), 'Nonregular ZIP entry')
        raw_manifest = zf.read('recovery-manifest.json')
        need(hashlib.sha256(raw_manifest).hexdigest() == policy['manifest_sha256'], 'Recovery manifest identity changed')
        manifest = json.loads(raw_manifest)
        need(manifest['status'] == 'ONLY_RECOVERY_NOT_INSTALL_READY' and manifest['copying_completed'] is True and
             manifest['errors'] == [] and manifest['expected_source_pins'] == policy['expected_pins'], 'Recovery scope mismatch')
        context = manifest['github_context']
        need(context['GITHUB_SHA'] == policy['source_commit'] and context['GITHUB_REPOSITORY'] == policy['repository'] and
             context['GITHUB_RUN_ID'] == str(policy['run_id']) and context['GITHUB_RUN_ATTEMPT'] == '1', 'Recovery run context mismatch')
        missing = sorted(set(manifest['files']) - set(names))
        need(missing == policy['expected_optional_omissions'], 'Unexpected manifested omission')
        # Hash every present manifested output; exact optional omissions are policy-bound.
        for name, record in manifest['files'].items():
            if name in missing:
                continue
            data = zf.read(name)
            need(len(data) == record['bytes'] and hashlib.sha256(data).hexdigest() == record['sha256'], 'Present member hash mismatch')
        restored = {}
        for name, expected in policy['required'].items():
            need(name in names and name in manifest['files'], 'Missing required warm component')
            data = zf.read(name)
            need(len(data) == expected['bytes'] and hashlib.sha256(data).hexdigest() == expected['sha256'], 'Required component identity mismatch')
            relative = name.removeprefix('public-build/')
            target = work.joinpath(*relative.split('/'))
            need(work in target.resolve().parents, 'Warm extraction escaped work')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as sink:
                sink.write(data)
            target.chmod(0o755 if 'macho' in expected and expected['macho']['filetype'] == 2 else 0o644)
            if 'macho' in expected:
                actual = facts(target)
                need(actual == {k: expected['macho'][k] for k in actual}, 'Mach-O target/dependency profile changed')
            restored[name] = target
    return restored, missing

def command(argv, log, timeout=30):
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=timeout)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    need(result.returncode == 0, 'Prerequisite command failed: ' + Path(str(argv[0])).name)
    return (result.stdout + result.stderr).strip()




def prepare_frozen_host(root, source, logs, build_env):
    policy_path=Path(__file__).with_name('host-reuse-policy.json')
    need(sha(policy_path)==POLICY_SHA,'Unreviewed host-reuse policy')
    policy=json.loads(policy_path.read_text())
    need(sha(source/'ci/build_gpu_only.py')==policy['source_helper_sha256'] and sha(source/'ci/qualify_gpu_host.py')==policy['qualifier_sha256'],'Fixed C6 source plan changed')
    token=build_env.pop('GH_ARTIFACT_TOKEN',None)
    os.environ.pop('GH_ARTIFACT_TOKEN',None)
    for key in ['GITHUB_TOKEN','GH_TOKEN']:
        build_env.pop(key,None)
    need(bool(token),'Read-only fixed-artifact token missing')
    scratch=Path(tempfile.mkdtemp(prefix='frozen-C6-host-',dir=root.parent))
    archive=scratch/'recovery.zip'
    def expired(signum,frame):raise RuntimeError('Fixed artifact reception deadline exceeded')
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(180)
    try:
        try:origin=download(policy,token,archive)
        except Exception as error:
            # Never serialize signed asset URL/HTTP request/credentials.
            raise RuntimeError('Fixed C6 download failed: '+type(error).__name__) from None
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous);token=None
    restored,missing=restore(policy,archive,root)
    need(not missing,'C6 recovery must have no manifested omissions')
    profile=json.loads((root/'build/mesa-tu/builtin-build-profile.json').read_text())
    need(profile==policy['profile'],'Recovered host compiler profile changed')
    identity=profile['profile']
    need(hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()==profile['source_id'],'Recovered profile source identity mismatch')
    compiler=command(['/usr/bin/clang++','--version'],logs/'host-reuse-current-compiler.log')
    need(compiler==identity['compiler'],'Current Apple compiler differs from C6')
    sdk=command(['xcrun','--sdk','macosx','--show-sdk-version'],logs/'host-reuse-current-sdk.log')
    need(sdk=='26.5','Current macOS SDK differs from C6')
    osversion=command(['sw_vers','-productVersion'],logs/'host-reuse-current-os.log')
    numbers=[int(x) for x in osversion.split('.')]+[0,0];packed=(numbers[0]<<16)|(numbers[1]<<8)|numbers[2]
    need(numbers[0]>=26,'Current Mac older than recovered runtime')
    need(command(['brew','list','--versions','spirv-tools'],logs/'host-reuse-spirv-version.log')=='spirv-tools '+policy['spirv_tools_version'],'SPIRV dependency bottle version changed')
    dependency=Path('/opt/homebrew/opt/spirv-tools/lib/libSPIRV-Tools.dylib').resolve(strict=True)
    need(Path('/opt/homebrew/Cellar/spirv-tools/'+policy['spirv_tools_version']) in dependency.parents,'SPIRV dependency path escaped expected bottle')
    command(['/usr/bin/codesign','--verify','--strict',dependency],logs/'host-reuse-dependency-codesign.log')
    depfacts=facts(dependency)
    need(depfacts['filetype']==6 and len(depfacts['builds'])==1 and depfacts['builds'][0][0]==1 and depfacts['builds'][0][1]<=packed,'Invalid SPIRV dependency target')
    need(all(n.startswith(('/usr/lib/','/System/Library/Frameworks/')) for n in depfacts['dependencies']),'Unreviewed SPIRV transitive dependency')
    strict={}
    for i,(name,target) in enumerate(restored.items()):
        expected=policy['required'][name]
        if 'macho' in expected:
            need(expected['macho']['builds'] and all(b[0]==1 and b[1]<=packed for b in expected['macho']['builds']),'Cached target requires newer macOS')
            command(['/usr/bin/codesign','--verify','--strict',target],logs/('host-reuse-codesign-'+str(i)+'.log'))
            detail=command(['/usr/bin/codesign','--display','--verbose=4',target],logs/('host-reuse-codesign-detail-'+str(i)+'.log'))
            cd=re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
            need(cd is not None and cd[1]==expected['macho']['cdhash'],'Actual cached CodeDirectory identity differs')
            strict[name]=dict(sha256=sha(target),cdhash=cd[1],strict_verified_on_this_Mac=True)
        # Whole original host suite later recompiles this small peer in place.
        # Keep its immutable C6 identity in the authenticated ZIP and receipt.
        target.chmod(0o755 if name.endswith(('ir3_disasm','ir3_delay_test')) else 0o644 if name.endswith('libhostiokit.dylib') or name.endswith('Cargo.lock') else 0o444)
    receipt=dict(schema='unixnu.frozen-C6-host-reuse-receipt.v1',provenance=origin,policy_sha256=POLICY_SHA,
        required_inputs={name:{key:record[key] for key in ['bytes','sha256']} for name,record in policy['required'].items()},
        original_profile_sha256=policy['required']['public-build/build/mesa-tu/builtin-build-profile.json']['sha256'],original_profile_source_id=profile['source_id'],
        current_mac_sdk_version=sdk,current_apple_compiler=compiler,
        SPIRV_dependency=dict(version=policy['spirv_tools_version'],sha256=sha(dependency),macho=depfacts,codesign_strict_verified_on_this_Mac=True,exact_previous_C6_dependency_hash_available=False),
        current_codesign_verifications=strict,host_bridge_built_in_this_run=False,host_Mesa_built_in_this_run=False,host_IR3_built_in_this_run=False,
        original_Cargo_lock_sha256=policy['required']['public-build/build/adreno-metal-bridge/Cargo.lock']['sha256'],
        IR3_upstream_revalidated_this_run=False,IR3_tests={},setup_prefix_sha256=policy['mesa_setup_through_bison_prefix_sha256'])
    return receipt,policy


def setup_source_tools_and_revalidate_IR3(root,logs,run,build_env,receipt,policy):
    source=root/'scripts/build-adreno-compiler-host.py'
    need(sha(source)==policy['device_compiler_sha256'],'Original device compiler script changed')
    raw=source.read_text()
    marker="clean_env = {k: v for k, v in os.environ.items() if not k.startswith(('IR3_', 'FD_MESA_', 'NIR_', 'MESA_SHADER_'))}"
    need(raw.count(marker)==1,'Exact pre-Mesa-build setup cutoff changed')
    prefix=raw.split(marker,1)[0]
    need(hashlib.sha256(prefix.encode()).hexdigest()==policy['mesa_setup_through_bison_prefix_sha256'],'Original source/tool setup prefix changed')
    target=root/'scripts/.host-reuse-source-tool-setup.py'
    need(not target.exists(),'Source/tool setup must use a fresh owned file')
    target.write_text(prefix)
    run([sys.executable,'-B',target],'host-reuse-source-tool-setup',1200)
    need(not (root/'build/mesa-ir3/build.ninja').exists() and not (root/'build/mesa-tu/build.ninja').exists(),'Host Mesa/IR3 was unexpectedly configured')
    env={k:v for k,v in build_env.items() if not k.startswith(('IR3_','FD_MESA_','NIR_','MESA_SHADER_'))}
    env.update(PATH=str(root/'.cache/mesa-tools/bin')+':'+str(root/'.cache/mesa-venv/bin')+':'+env['PATH'],CC='/usr/bin/clang',CXX='/usr/bin/clang++',CFLAGS='',CPPFLAGS='',CXXFLAGS='',LDFLAGS='')
    results={}
    for name in ['ir3_disasm','ir3_delay_test']:
        binary=root/'build/mesa-ir3/src/freedreno/ir3'/name
        expected=policy['required']['public-build/'+str(binary.relative_to(root))]
        need(sha(binary)==expected['sha256'],'Cached IR3 tool changed before self-test')
        result=subprocess.run([str(binary)],env=env,capture_output=True,text=True,timeout=30)
        log=logs/('host-reuse-'+name+'-revalidation.log');log.write_text(result.stdout+result.stderr,encoding='utf-8',newline='\n')
        need(result.returncode==0,'Original IR3 upstream self-test returned failure')
        stdout=result.stdout.strip()
        record=dict(binary_sha256=sha(binary),stdout_bytes=len(result.stdout.encode('utf-8')),stderr_bytes=len(result.stderr.encode('utf-8')),output_sha256=hashlib.sha256(stdout.encode()).hexdigest(),log_sha256=sha(log),exit_code=result.returncode)
        if name=='ir3_disasm':
            need(stdout.endswith('PASSED!'),'Original ISA vector success marker absent')
            devices=re.findall(r'^Testing (.*?) [0-9a-f]{8}_',stdout,re.M)
            counts={device:devices.count(device) for device in sorted(set(devices))}
            need(counts=={'FD630':285,'FD730':53,'Adreno (TM) 830':6,'FD540':22,'FD420':2},'Original exact368 ISA coverage changed')
            record.update(cases=len(devices),per_source_device=counts)
        else:
            cases=len(re.findall(r'^\d+: PASS$',stdout,re.M));need(cases==12,'Original12 delay controls changed');record['cases']=cases
        results[name]=record
    receipt['IR3_tests']=results;receipt['IR3_upstream_revalidated_this_run']=True
    # Old host-report is preserved with its original build-tool identities.
    # This separate receipt reports actual current execution, never a new build.
    write_json(logs/'host-build-reuse.json',receipt)


def verify_reused_host_inputs(root,receipt,allow_rebuilt_peer=False):
    for name,record in receipt['required_inputs'].items():
        if allow_rebuilt_peer and name.endswith('libhostiokit.dylib'):continue
        target=root/name.removeprefix('public-build/')
        need(target.is_file() and not target.is_symlink() and target.stat().st_size==record['bytes'] and sha(target)==record['sha256'],'Frozen host input changed: '+name)


def reviewed_Q_adapter_record():
    return dict(path='scripts/check-quartzcore-turnip-cache-host.py',
        original_sha256='eae106179803091de6d065a57fd9af737184d1bae90927313255521c84fcc311',
        patched_sha256='1f93320b33829370e39cf8b60f7cf8fbca130f1dad0a6ac8fe39c62bbcb4ffed',
        diff_sha256='6b24fdb77cc861a242ba0bff3eccc20c2d7f3e6b6b33972730805df50064490b',
        expected_produce_artifact_misses=72, expected_produce_artifact_writes=48,
        production_sources_modified=False)
