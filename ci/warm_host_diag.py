#!/usr/bin/env python3
"""Authenticated fixed-artifact HOSTDIAG; gated hostshim compile only, no Mesa/Rust rebuild."""
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

POLICY_SHA = 'c09695c44c826c3f52e53c57098ddbf25fac6c0701c8b5d344aea0d2b616137f'
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
        need(sum(x.file_size for x in infos) < 128 * CHUNK, 'ZIP expanded size exceeds fixed warm bound')
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
        # Hash every PRESENT manifested output. Six exact optional hidden logs are
        # explicitly absent from the frozen GitHub archive; no required binary is waived.
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

def matches_baseline_conflict(text):
    allocations = list(re.finditer(r'hostgpu alloc (\d+) -> (-?\d+) spans-live (\d+)', text))
    maps = list(re.finditer(r'hostgpu method 3 -> (-?\d+)', text))
    return bool(allocations and allocations[0][2] == '0' and maps and maps[0][1] == '2'
                and allocations[0].start() < maps[0].start()
                and 'stage 5 result -2' in text and '6f05 6e02' in text
                and 'VK_ERROR_OUT_OF_DEVICE_MEMORY' in text)

def compile_corrected_host_shim(upstream, source, policy, output):
    upstream = upstream.resolve(strict=True)
    need(command(['git', '-C', upstream, 'rev-parse', 'HEAD'], output / 'upstream-head.log') == policy['expected_pins']['UniXNU'],
         'Wrong upstream source revision')
    need(command(['git', '-C', upstream, 'status', '--porcelain'], output / 'upstream-clean.log') == '', 'Upstream must start clean')
    components = policy['expected_pins']['components']
    command(['git', '-C', upstream, 'submodule', 'update', '--init', '--recursive', '--', *components],
            output / 'four-exact-components.log', 180)
    for index, (relative, expected) in enumerate(components.items()):
        need(command(['git', '-C', upstream / relative, 'rev-parse', 'HEAD'], output / ('component-head-' + str(index) + '.log')) == expected,
             'Wrong source component revision')
        need(command(['git', '-C', upstream / relative, 'status', '--porcelain'], output / ('component-clean-' + str(index) + '.log')) == '',
             'Dirty source component')
    kit = upstream / 'drivers/Adreno740'
    for name, expected in policy['conditional_AB']['source_proof'].items():
        need(sha(kit / name) == expected, 'Pinned source proof changed: ' + name)
    changes = [
        (kit / 'tests/XnuMemoryFixture.h', source / 'ci/host-XnuMemoryFixture.h',
         'e316a1d4606c2fa52671fb15855f1d76e2cfd827f6d91f950aaf6452d596b04e',
         '18015ab4e9bc6a276b7c5aaf09571ba84e6d5936ede5f419a211c6dbb808f55f'),
        (upstream / 'scripts/check-turnip-darwin-host.py', source / 'ci/host-check-turnip-darwin-host.py',
         '7ab580b33aa544a0e8931679884d2aa717e5663d6d9ff52ee5cda90c128862c0',
         '29a805edbf1905112029d7e0adca8668fa6781265a03f571f1760a566fe7732b'),
    ]
    for target, asset, before, after in changes:
        need(sha(target) == before and sha(asset) == after, 'Unreviewed host fixture/source overlay')
        target.write_bytes(asset.read_bytes())
    original_service = kit / 'tests/hostsim/host_gpu_service.cpp'
    need(sha(original_service) == '4ef75c3cf644cdc3ead973e568a580124dfe3aaf0527c93770d5ac1c1cd7810b' and
         sha(source / 'ci/host-gpu-service.cpp') == policy['conditional_AB']['old_C4_service_sha256'], 'Original/C4 host service identity mismatch')
    new_service = Path(__file__).with_name('host-gpu-service-va.cpp')
    need(sha(new_service) == policy['conditional_AB']['new_host_service_sha256'], 'Unreviewed host VA configuration')
    original_service.write_bytes(new_service.read_bytes())
    role = source / 'ci/host-resource-private.h'
    need(sha(role) == 'fb9dd31b1b0a82c7bc64223a8a475d1408b661fd1a3efdcca62930a5aa802292', 'Unreviewed host role constants')
    header = upstream / 'build/turnip-darwin-host/host-include/sys/resource_private.h'
    need(not header.exists(), 'Do not replace existing host header')
    header.parent.mkdir(parents=True)
    header.write_bytes(role.read_bytes())
    prefix = source / 'ci/host-link-preflight-prefix.py'
    need(sha(prefix) == 'a3f12d39dc20fa084030566c68b7ad5b2797d6539dab0a09ffe46a244d36766d', 'Unreviewed strict link prefix')
    wrapper = upstream / 'build/warm-host-link-wrapper.py'
    wrapper.write_text("from pathlib import Path\np=Path(" + repr(str(upstream / 'scripts/check-turnip-darwin-host.py')) +
        ")\nscope={'__file__':str(p),'__name__':'__warm_host_strict_link__'}\nexec(compile(" +
        repr(prefix.read_text()) + ",str(p),'exec'),scope)\n")
    # Compile/link only the reviewed host core/shim prefix. No Mesa/Rust or shader/header build.
    command([sys.executable, '-B', wrapper], output / 'corrected-host-strict-link.log', 180)
    library = upstream / 'build/turnip-darwin-host/libhostiokit.dylib'
    need(library.is_file(), 'Corrected host shim absent')
    command(['/usr/bin/codesign', '--verify', '--strict', library], output / 'corrected-shim-codesign.log')
    return library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--upstream', type=Path, help='Pinned clean source for conditional host-only strict-link A/B')
    a = parser.parse_args()
    output = a.output.resolve()
    need(not output.exists(), 'Diagnostic output must be new')
    output.mkdir(parents=True)
    report = dict(status='HOSTDIAG_ONLY_NOT_INSTALL_READY', no_Mesa_or_Rust_rebuild=True,
        production_fix_applied=False, hardware_GPU_execution_verified=False, installation_ready=False,
        old_environment_bit_identity_claimed=False, diagnostic_executed=False)
    code = 2
    try:
        need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'macOS ARM64 required')
        policy_path = Path(__file__).with_name('warm-policy.json')
        need(sha(policy_path) == POLICY_SHA, 'Unreviewed warm policy')
        policy = json.loads(policy_path.read_text())
        source = a.source_plan.resolve()
        need(sha(source / 'ci/build_gpu_only.py') == policy['source_helper_sha256'] and
             sha(source / 'ci/host-gen-turnip-replay.py') == policy['source_generator_sha256'], 'Pinned C4 source files differ')
        token = os.environ.pop('GH_ARTIFACT_TOKEN', '')
        need(bool(token), 'GitHub read-only artifact token missing')
        work = Path(tempfile.mkdtemp(prefix='hostdiag-work-', dir=output.parent))
        archive = work / 'fixed-recovery.zip'
        # Hard overall download deadline; no OSError retry can swallow it here.
        def expired(signum, frame):
            raise RuntimeError('Artifact authentication/download deadline exceeded')
        previous = signal.signal(signal.SIGALRM, expired)
        signal.alarm(180)
        try:
            report['provenance'] = download(policy, token, archive)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
            token = None
        restored, missing = restore(policy, archive, work)
        report['optional_hidden_log_omissions'] = missing
        profile_path = work / 'build/mesa-tu/builtin-build-profile.json'
        profile = json.loads(profile_path.read_text())
        need(profile == policy['profile'], 'Recovered compiler profile changed')
        identity = profile['profile']
        need(hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == profile['source_id'],
             'Compiler source/profile identity is inconsistent')
        compiler = command(['/usr/bin/clang++', '--version'], output / 'current-compiler.log')
        need(compiler == identity['compiler'], 'Current Apple compiler differs from recorded host profile')
        sdk = command(['xcrun', '--sdk', 'macosx', '--show-sdk-version'], output / 'current-sdk.log')
        need(sdk == '26.5', 'Current macOS SDK differs from recorded Mach-O SDK')
        os_version = command(['sw_vers', '-productVersion'], output / 'current-os.log')
        need(int(os_version.split('.')[0]) >= 26, 'Host is older than recorded minimum26.0')
        brew = command(['brew', 'list', '--versions', 'spirv-tools'], output / 'spirv-tools-version.log')
        need(brew == 'spirv-tools ' + policy['spirv_tools_version'], 'Unexpected SPIRV-Tools version')
        dependency = Path('/opt/homebrew/opt/spirv-tools/lib/libSPIRV-Tools.dylib').resolve(strict=True)
        need(Path('/opt/homebrew/Cellar/spirv-tools/' + policy['spirv_tools_version']) in dependency.parents,
             'SPIRV-Tools dependency escaped expected bottle prefix')
        command(['/usr/bin/codesign', '--verify', '--strict', dependency], output / 'dependency-codesign.log')
        dependency_facts = facts(dependency)
        need(dependency_facts['filetype'] == 6 and len(dependency_facts['builds']) == 1 and dependency_facts['builds'][0][0] == 1, 'SPIRV dependency must be a macOS ARM64 dylib')
        need(all(name.startswith(('/usr/lib/', '/System/Library/Frameworks/')) for name in dependency_facts['dependencies']), 'Unreviewed transitive SPIRV dependency')
        parts = [int(x) for x in os_version.split('.')] + [0, 0]
        need(dependency_facts['builds'][0][1] <= ((parts[0] << 16) | (parts[1] << 8) | parts[2]), 'SPIRV dependency minimum OS is newer than this Mac')
        report['spirv_tools_dependency'] = dict(path=str(dependency), sha256=sha(dependency), macho=dependency_facts,
            exact_previous_C4_dependency_hash_available=False, current_codesign_strict_verified=True)
        report['verified_host_binaries'] = {}
        for index, (name, target) in enumerate(restored.items()):
            expected = policy['required'][name]
            if 'macho' not in expected:
                continue
            command(['/usr/bin/codesign', '--verify', '--strict', target], output / ('codesign-verify-' + str(index) + '.log'))
            detail = command(['/usr/bin/codesign', '--display', '--verbose=4', target], output / ('codesign-detail-' + str(index) + '.log'))
            match = re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)
            need(match is not None and match[1] == expected['macho']['cdhash'], 'Actual codesign CDHash differs')
            report['verified_host_binaries'][name] = dict(sha256=sha(target), cdhash=match[1],
                codesign_strict_verified_on_this_Mac=True, macho=expected['macho'])
        # No iOS executable or tablet image exists in this required recovery subset.
        (work / 'build/turnip-smoke').mkdir(parents=True, exist_ok=True)
        scripts = work / 'scripts'
        scripts.mkdir()
        generator = scripts / 'gen-turnip-replay.py'
        generator.write_bytes((source / 'ci/host-gen-turnip-replay.py').read_bytes())
        env = {k: v for k, v in os.environ.items() if k not in ('GH_ARTIFACT_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN') and not k.startswith('ACTIONS_')}
        env['HOSTSIM_TRACE'] = '1'
        # Keep the authenticated C4 baseline read-only and separate from rebuilt output.
        for target in restored.values():
            target.chmod(0o555 if target.name in ('plugin_smoke', 'vulkan_smoke') else 0o444)
        baseline_hashes = {name: sha(target) for name, target in restored.items()}
        report['baseline_files_readonly_and_separate'] = True
        report['diagnostic_executed'] = True
        baseline_log = output / 'host-replay-baseline-trace.log'
        with baseline_log.open('wb') as stream:
            result = subprocess.run([sys.executable, '-B', generator], cwd=work, env=env,
                stdout=stream, stderr=subprocess.STDOUT, timeout=360)
        code = result.returncode
        report['baseline_exit_code'] = code
        report['runtime_exit_code'] = code
        report['only_added_runtime_diagnostic_flag'] = 'HOSTSIM_TRACE=1'
        report['same_frozen_C4_binary_hashes_executed'] = True
        report['RD_memory_dump_or_generated_header_uploaded'] = False
        report['conditional_AB_applied'] = False
        if code != 0:
            baseline_text = baseline_log.read_text(errors='replace')
            gate = matches_baseline_conflict(baseline_text)
            report['baseline_BoAlloc_success_then_BoMap_Busy_stage5_gate'] = gate
            report['failed_IOVA_value_directly_observed'] = False
            need(gate, 'Baseline differs from the specific BoAlloc0/BoMapBusy2/stage5VK-2 conflict; no correction applied')
            need(a.upstream is not None, 'Specific baseline conflict captured; source checkout needed for reviewed conditional A/B')
            new_shim = compile_corrected_host_shim(a.upstream, source, policy, output)
            # Restoring into a NEW directory never touches the frozen baseline files.
            after = work / 'after'
            after.mkdir()
            after_files, _ = restore(policy, archive, after)
            shim_key = 'public-build/build/turnip-darwin-host/libhostiokit.dylib'
            target = after_files[shim_key]
            target.write_bytes(new_shim.read_bytes())
            need(facts(target) == {k: policy['required'][shim_key]['macho'][k] for k in facts(target)}, 'Corrected shim target/dependencies changed')
            command(['/usr/bin/codesign', '--verify', '--strict', target], output / 'after-copy-shim-codesign.log')
            for name, f in after_files.items():
                if name != shim_key:
                    need(sha(f) == policy['required'][name]['sha256'], 'Cached Mesa/smoke/profile bytes changed in A/B')
            (after / 'build/turnip-smoke').mkdir(parents=True, exist_ok=True)
            after_scripts = after / 'scripts'
            after_scripts.mkdir()
            after_generator = after_scripts / 'gen-turnip-replay.py'
            after_generator.write_bytes(generator.read_bytes())
            report['conditional_AB_applied'] = True
            report['hostsim_VA_source_sha256'] = policy['conditional_AB']['new_host_service_sha256']
            report['new_host_shim_sha256'] = sha(target)
            with (output / 'host-replay-after-trace.log').open('wb') as stream:
                second = subprocess.run([sys.executable, '-B', after_generator], cwd=after, env=env,
                    stdout=stream, stderr=subprocess.STDOUT, timeout=360)
            code = second.returncode
            report['conditional_AB_applied'] = True
            report['after_exit_code'] = code
            report['runtime_exit_code'] = code
            report['hostsim_VA_source_sha256'] = policy['conditional_AB']['new_host_service_sha256']
            report['new_host_shim_sha256'] = sha(target)
            report['cached_Mesa_and_both_smokes_unchanged'] = True
            header = after / 'build/turnip-smoke/TurnipReplay.h'
            if code == 0:
                need(header.is_file() and header.stat().st_size > 256, 'Successful producer did not make real replay header')
                report['real_producer_replay_checks_passed_after_hostsim_correction'] = True
                report['replay_header'] = dict(bytes=header.stat().st_size, sha256=sha(header), uploaded=False)
            for name, target in restored.items():
                need(sha(target) == baseline_hashes[name], 'Frozen baseline was modified')
            report['frozen_baseline_preserved_after_AB'] = True
    except Exception as error:
        code = 2
        # Do not serialize exception URLs/requests: signed asset URLs and tokens stay private.
        report['failure_type'] = type(error).__name__
        report['failure_message'] = str(error) if isinstance(error, RuntimeError) else 'Prerequisite or diagnostic failed; see bounded command logs'
    finally:
        write_json(output / 'hostdiag-report.json', report)
    print(json.dumps(dict(status=report['status'], diagnostic_executed=report['diagnostic_executed'],
                          runtime_exit_code=report.get('runtime_exit_code'), failure_type=report.get('failure_type'))))
    return code

if __name__ == '__main__':
    sys.exit(main())
