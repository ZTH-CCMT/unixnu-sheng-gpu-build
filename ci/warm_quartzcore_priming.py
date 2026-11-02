#!/usr/bin/env python3
"""Frozen C6 adapted QuartzCore plus original priming diagnostics; no Rust/Mesa rebuild or producer changes."""
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

POLICY_SHA = '4b98ac5c31b3db8f6168c85d2daab86b4f60d5516d16bdc5236d788d00126c12'
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


class QDiagnosticFailure(RuntimeError):
    pass

class PDiagnosticFailure(RuntimeError):
    pass


def preserve_q_text(root, stable, output):
    """Exact source-authored text paths only; never walk cache/archive trees."""
    selected=[(stable/(mode+'.log'),'case-'+mode+'.log') for mode in ['produce','consume','uuid-miss','empty-driver']]
    selected += [(stable/'checkpoint.json','quartzcore-checkpoint.json')]
    selected += [(root/'build/ui-shader-coverage/turnip-graphics'/('last-'+mode+'.log'),'last-'+mode+'.log') for mode in ['produce','consume','uuid-miss','empty-driver']]
    selected += [(root/'build/ui-shader-coverage/turnip-graphics/quartzcore-turnip-checkpoint.json','quartzcore-latest-checkpoint.json')]
    records={}
    for source,name in selected:
        if not source.exists():continue
        need(not source.is_symlink() and source.is_file() and root in source.resolve().parents,'Unexpected diagnostic text path')
        size=source.stat().st_size
        need(size<=16*CHUNK,'Diagnostic text exceeds16MiB')
        raw=source.read_bytes()
        need(len(raw)==size and b'\x00' not in raw and not raw.startswith(b'MTLB'),'Binary payload in diagnostic text')
        raw.decode('utf-8')
        if source.suffix=='.json':need(isinstance(json.loads(raw),dict),'Expected checkpoint object')
        target=output/name
        with target.open('xb') as stream:stream.write(raw)
        records[name]=dict(bytes=size,sha256=hashlib.sha256(raw).hexdigest())
    return records


def preserve_p_text(root, stable, output):
    """Explicit original P logs/checkpoints only; never copy the cache record."""
    modes=['cold-miss','produce','consume','uuid-miss','truncated-miss','checksum-miss']
    selected=[(stable/(mode+'.log'),'P-case-'+mode+'.log') for mode in modes]
    selected += [(stable/'checkpoint.json','priming-checkpoint.json')]
    selected += [(root/'build/priming-cache/checkpoint.json','priming-latest-checkpoint.json')]
    records={}
    for source,name in selected:
        if not source.exists():continue
        need(not source.is_symlink() and source.is_file() and root in source.resolve().parents,'Unexpected P diagnostic text path')
        size=source.stat().st_size
        need(size<=16*CHUNK,'P diagnostic text exceeds16MiB')
        raw=source.read_bytes()
        need(len(raw)==size and b'\x00' not in raw and not raw.startswith((b'MTLB',b'M2VPPLC')),'Binary payload in P diagnostic text')
        raw.decode('utf-8')
        if source.suffix=='.json':need(isinstance(json.loads(raw),dict),'Expected P checkpoint object')
        with (output/name).open('xb') as stream:stream.write(raw)
        records[name]=dict(bytes=size,sha256=hashlib.sha256(raw).hexdigest())
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-plan',required=True,type=Path)
    parser.add_argument('--upstream',required=True,type=Path)
    parser.add_argument('--device',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    a=parser.parse_args()
    root,device,source,output=map(lambda p:p.resolve(),[a.upstream,a.device,a.source_plan,a.output])
    need(not output.exists() and output.parent==root.parent and root!=output,'New sibling diagnostic output required')
    output.mkdir()
    report=dict(status='QP_TEST_ADAPTER_DIAGNOSTIC_ONLY_NOT_INSTALL_READY',Q_original_checker_sha256='eae106179803091de6d065a57fd9af737184d1bae90927313255521c84fcc311',Q_adapted_checker_sha256='1f93320b33829370e39cf8b60f7cf8fbca130f1dad0a6ac8fe39c62bbcb4ffed',Q_adapter_version='q-cache-layout-runtime624bab-miss72-write48-v1',P_original_checker_sha256='825c471b2b095ccd2d0c6203e8199ab59ce9769f836aa75f433e137aa6be7422',no_Rust_or_Mesa_rebuild=True,production_sources_modified=False,hardware_GPU_execution_verified=False,installation_ready=False,diagnostic_executed=False,P_diagnostic_executed=False,P_original_script_modified=False)
    code=2
    stable=root/'build/ci-quartzcore-warm-stable'
    pstable=root/'build/ci-priming-warm-stable'
    baseline={}
    qualifier_logs=output/'original-input-logs'
    qualifier_logs.mkdir()
    try:
        need(platform.system()=='Darwin' and platform.machine()=='arm64','macOS ARM64 required')
        policy_path=Path(__file__).with_name('quartzcore-priming-policy.json')
        need(sha(policy_path)==POLICY_SHA,'Unreviewed Q-only policy')
        policy=json.loads(policy_path.read_text())
        need(sha(source/'ci/build_gpu_only.py')==policy['source_helper_sha256'] and sha(source/'ci/qualify_gpu_host.py')==policy['qualifier_sha256'],'C6 source plan identity changed')
        for path,pin in [(root,policy['expected_pins']['UniXNU']),(device,policy['expected_pins']['device'])]:
            need(command(['git','-C',path,'rev-parse','HEAD'],output/('pin-'+path.name+'.log'))==pin,'Wrong fixed source HEAD')
            need(command(['git','-C',path,'status','--porcelain'],output/('clean-'+path.name+'.log'))=='','Fresh clean source required')
        selected=list(policy['expected_pins']['components'])
        command(['git','-C',root,'submodule','update','--init','--recursive','--',*selected],output/'submodules.log',600)
        for name,pin in policy['expected_pins']['components'].items():
            need(command(['git','-C',root/name,'rev-parse','HEAD'],output/('pin-'+name.replace('/','_')+'.log'))==pin,'Wrong exact component pin')
        # Verify original device Q, then apply only the reviewed exact cache-layout adapter.
        qsource=device/'scripts/check-quartzcore-turnip-cache-host.py'
        compiler_source=device/'scripts/build-adreno-compiler-host.py'
        need(sha(qsource)==policy['quartzcore_checker_sha256'] and sha(compiler_source)==policy['device_compiler_sha256'],'Wrong device source scripts')
        token=os.environ.pop('GH_ARTIFACT_TOKEN','')
        need(bool(token),'Read-only artifact token missing')
        scratch=Path(tempfile.mkdtemp(prefix='q-recovery-',dir=root.parent))
        archive=scratch/'fixed-C6-recovery.zip'
        def expired(signum,frame):raise RuntimeError('Fixed artifact reception deadline exceeded')
        previous=signal.signal(signal.SIGALRM,expired);signal.alarm(180)
        try:report['provenance']=download(policy,token,archive)
        finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous);token=None
        restored,missing=restore(policy,archive,root)
        report['exact_optional_omissions']=missing
        profile_path=root/'build/mesa-tu/builtin-build-profile.json'
        profile=json.loads(profile_path.read_text())
        need(profile==policy['profile'],'Recovered compiler profile changed')
        identity=profile['profile']
        need(hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()==profile['source_id'],'Recorded profile source identity mismatch')
        need(command(['/usr/bin/clang++','--version'],output/'current-compiler.log')==identity['compiler'],'Current Apple compiler differs from C6')
        need(command(['xcrun','--sdk','macosx','--show-sdk-version'],output/'current-sdk.log')=='26.5','Actual Mac SDK changed')
        version=command(['sw_vers','-productVersion'],output/'current-os.log');parts=[int(v) for v in version.split('.')]+[0,0]
        packed=(parts[0]<<16)|(parts[1]<<8)|parts[2]
        need(parts[0]>=26,'Host older than recovered minimum macOS26')
        need(command(['brew','list','--versions','spirv-tools'],output/'spirv-tools-version.log')=='spirv-tools '+policy['spirv_tools_version'],'SPIRV dependency version changed')
        dependency=Path('/opt/homebrew/opt/spirv-tools/lib/libSPIRV-Tools.dylib').resolve(strict=True)
        need(Path('/opt/homebrew/Cellar/spirv-tools/'+policy['spirv_tools_version']) in dependency.parents,'Unexpected SPIRV dependency path')
        command(['/usr/bin/codesign','--verify','--strict',dependency],output/'dependency-codesign.log')
        depfacts=facts(dependency)
        need(depfacts['filetype']==6 and len(depfacts['builds'])==1 and depfacts['builds'][0][0]==1 and depfacts['builds'][0][1]<=packed,'Invalid SPIRV Mach-O target')
        need(all(n.startswith(('/usr/lib/','/System/Library/Frameworks/')) for n in depfacts['dependencies']),'Unreviewed transitive SPIRV dependency')
        report['current_SPIRV_dependency']=dict(sha256=sha(dependency),macho=depfacts,codesign_strict_verified_on_this_Mac=True,exact_previous_C6_dependency_hash_available=False)
        report['cached_inputs']={}
        for i,(name,target) in enumerate(restored.items()):
            expected=policy['required'][name]
            if 'macho' in expected:
                need(all(b[0]==1 and b[1]<=packed for b in expected['macho']['builds']),'Recovered executable target too new')
                command(['/usr/bin/codesign','--verify','--strict',target],output/('codesign-'+str(i)+'.log'))
                details=command(['/usr/bin/codesign','--display','--verbose=4',target],output/('codesign-details-'+str(i)+'.log'))
                match=re.search(r'^CDHash=([0-9a-f]{40})$',details,re.M)
                need(match is not None and match[1]==expected['macho']['cdhash'],'Actual cached CDHash mismatch')
            target.chmod(0o444)
            baseline[name]=sha(target)
            report['cached_inputs'][name]=dict(bytes=target.stat().st_size,sha256=baseline[name],frozen_before_Q=True,codesign_checked_on_this_Mac='macho' in expected)
        # Exact original compiler script source-only prefix; cut before venv,
        # dependency builds and every compiler/ninja call. No source fabrication.
        prepare=compiler_source.read_text()
        marker="if not (venv / 'bin/python').exists():"
        need(prepare.count(marker)==1,'Source-only cutoff changed')
        prefix=prepare.split(marker,1)[0]
        need(hashlib.sha256(prefix.encode()).hexdigest()==policy['mesa_source_prefix_sha256'],'Exact source-only prefix changed')
        helper=root/'scripts/.warm-q-mesa-source-only.py'
        need(not helper.exists(),'Fresh source-only helper required')
        helper.write_text(prefix)
        command([sys.executable,'-B',helper],output/'prepare-fixed-Mesa-source-only.log',360)
        need(command(['git','-C',root/'.cache/mesa-work','rev-parse','HEAD'],output/'mesa-source-pin.log')==policy['expected_pins']['Mesa'],'Wrong Mesa source view')
        need(not (root/'build/mesa-ir3/build.ninja').exists(),'Source-only preparation unexpectedly configured a build')
        qtarget=root/'scripts/check-quartzcore-turnip-cache-host.py'
        need(not qtarget.exists(),'Do not replace existing checker')
        adapter=Path(__file__).with_name('Q-checker-adapter.py')
        need(sha(adapter)==policy['adapted_quartzcore_checker_sha256'],'Unreviewed Q test adapter')
        qtarget.write_bytes(adapter.read_bytes())
        need(sha(qtarget)==policy['adapted_quartzcore_checker_sha256'],'Copied Q adapter changed')
        report['Q_adapter_scope']='One condition only: exact misses72/writes48 for fixed runtime624bab and original606f library; all functional controls unchanged'
        ptarget=root/'scripts/check-priming-cache-host.py'
        need(sha(ptarget)==policy['priming_checker_sha256'],'Original P checker changed')
        for relative,digest in {**policy['Q_sources_sha256'],**policy['P_sources_sha256']}.items():
            need(sha(root/relative)==digest,'Pinned Q/P instrument source changed')
        for name,digest in policy['runtime_patches_sha256'].items():
            need(sha(root/'drivers/AdrenoMetal/bridge/patches'/name)==digest,'Runtime patch input changed')
        # Actual checkout of the fixed base is for original P report metadata;
        # no patches/build are run here and the frozen C6 bridge remains unchanged.
        translator_spec=json.loads((root/'scripts/data/gpu-metal-vulkan-inputs.json').read_text())['translator']
        need(translator_spec['repository']==policy['runtime_repository'] and translator_spec['commit']==policy['expected_pins']['translator'],'Wrong fixed runtime source specification')
        runtime=root/'.cache/gpu-reference/metal2vulkan'
        need(not runtime.exists(),'Fresh runtime base source metadata required')
        runtime.parent.mkdir(parents=True,exist_ok=True)
        command(['git','init',runtime],output/'runtime-source-init.log')
        command(['git','-C',runtime,'remote','add','origin',policy['runtime_repository']],output/'runtime-source-origin.log')
        command(['git','-C',runtime,'fetch','--depth=1','--filter=blob:none','origin',policy['expected_pins']['translator']],output/'runtime-source-fetch.log',300)
        command(['git','-C',runtime,'checkout','--detach','FETCH_HEAD'],output/'runtime-source-checkout.log',120)
        need(command(['git','-C',runtime,'rev-parse','HEAD'],output/'runtime-source-pin.log')==policy['expected_pins']['translator'],'Runtime base source HEAD changed')
        need(command(['git','-C',runtime,'status','--porcelain'],output/'runtime-source-clean.log')=='','Runtime metadata checkout must remain unpatched')
        report['runtime_source_metadata']=dict(base_revision=policy['expected_pins']['translator'],checkout='actual unpatched base source only; no runtime build',compiled_bridge_provenance='exact frozen C6 artifact host bridge',runtime_patch_files_verified=len(policy['runtime_patches_sha256']))
        need(not stable.exists(),'Stable Q output must be fresh')
        import importlib.util
        spec=importlib.util.spec_from_file_location('original_qualification',source/'ci/qualify_gpu_host.py')
        qualifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(qualifier)
        # The reviewed original-input context enforces exact official member
        # identities, bounded read-only mount, strict owned cleanup, no upload.
        try:
            with qualifier.matching_original_input(root,qualifier_logs) as original:
                report['diagnostic_executed']=True
                env={k:v for k,v in os.environ.items() if k not in ['GH_ARTIFACT_TOKEN','GITHUB_TOKEN','GH_TOKEN'] and not k.startswith('ACTIONS_')}
                with (output/'quartzcore-direct.log').open('wb') as stream:
                    result=subprocess.run([sys.executable,'-B',qtarget,'--output',stable],cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=660)
                report['Q_exit_code']=result.returncode
                if result.returncode:raise QDiagnosticFailure('Adapted Q cache-layout checker refused; inspect preserved case-produce.log / last-produce.log')
                need((stable/'checkpoint.json').is_file(),'Original Q checker did not write checkpoint')
                report['Q_adapted_four_case_host_scope_completed']=True
        finally:
            report['preserved_source_authored_text']=preserve_q_text(root,stable,output)
        try:
            need(not pstable.exists(),'Stable P output must be fresh')
            report['P_diagnostic_executed']=True
            with (output/'priming-direct.log').open('wb') as stream:
                result=subprocess.run([sys.executable,'-B',ptarget,'--output',pstable],cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=660)
            report['P_exit_code']=result.returncode
            if result.returncode:raise PDiagnosticFailure('Original six-case P checker refused; inspect preserved P-case logs')
            need((pstable/'checkpoint.json').is_file(),'Original P checker did not write checkpoint')
            report['P_original_six_case_host_scope_completed']=True
        finally:
            report['preserved_P_source_authored_text']=preserve_p_text(root,pstable,output)
        need(sha(qtarget)==policy['adapted_quartzcore_checker_sha256'] and sha(ptarget)==policy['priming_checker_sha256'],'Q adapter or original P checker changed during diagnostic')
        need(all(sha(target)==baseline[name] for name,target in restored.items()),'Cached C6 inputs changed during diagnostic')
        report['unchanged_cached_input_hashes_reverified']=True
        report['status']='ADAPTED_Q_AND_ORIGINAL_P_HOST_SOFTWARE_PASS_NOT_FULL_QUALIFICATION_OR_INSTALL_READY'
        code=0
    except Exception as error:
        report['error_type']=type(error).__name__
        report['error']=str(error) if isinstance(error,RuntimeError) else 'Prerequisite or network diagnostic failed; request URLs and signed credentials omitted'
        report['status']='QP_TEST_ADAPTER_DIAGNOSTIC_FAILED_NOT_INSTALL_READY'
    finally:
        # Context itself writes provenance even on error; upload only bounded
        # metadata JSON, never its staged original Apple library or scratch tree.
        report['original_input_logs_only']=True
        report['source_cache_archive_original_library_uploaded']=False
        if baseline:
            report['cached_input_hashes_after_attempt']={name:sha(root/name.removeprefix('public-build/')) for name in baseline}
        write_json(output/'quartzcore-priming-diagnostic-report.json',report)
        print(json.dumps(dict(status=report['status'],diagnostic_executed=report['diagnostic_executed'],installation_ready=False)))
    return code

if __name__=='__main__':sys.exit(main())
