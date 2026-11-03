#!/usr/bin/env python3
"""Authenticated frozen C9 watchdog-only diagnostic; no build, source patch or device action."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

POLICY_SHA = 'f7934279ba105ae7915f9aed25d73f5c507ffe11207877e403be4dda8c94f9a2'
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
    need(run['id'] == policy['run_id'] and run['head_sha'] == policy['source_commit'] and run['run_attempt'] == policy['run_attempt'] and
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
             context['GITHUB_RUN_ID'] == str(policy['run_id']) and context['GITHUB_RUN_ATTEMPT'] == str(policy['run_attempt']), 'Recovery run context mismatch')
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


def original_watchdog_gate(returncode, stdout):
    lines = [line for line in stdout.splitlines() if line.startswith('watchdog: W ')]
    # Byte-for-byte logical predicate from reviewed author29a; no looser fallback.
    passed = not (returncode or len(lines) != 1 or
                  not lines[0].startswith('watchdog: W 6004 ') or
                  ' v' not in lines[0] or 'kern' in lines[0])
    return dict(passed=passed, samples=lines, original_predicate_unchanged=True)


def run_case(name, stalled, plugin, driver, shim, root, output, variant):
    env = {key: value for key, value in os.environ.items()
           if key not in ['GH_ARTIFACT_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN'] and not key.startswith('ACTIONS_')}
    # Reproduce the author host-script additions. Remove inherited diagnostic
    # injection so each fresh process has one explicit case configuration.
    removed = {}
    for key in ['TU_DARWIN_SERVICE', 'HOSTSIM_STALL', 'HOSTSIM_TRACE', 'HOSTSIM_PAGE_SIZE',
                'HOSTSIM_SCATTER', 'HOSTSIM_CONTIGUOUS_MAX', 'HOSTSIM_FAIL_USER_UNMAP']:
        if key in env:
            removed[key] = 'removed inherited value; value deliberately not recorded'
        env.pop(key, None)
    env.update(DYLD_INSERT_LIBRARIES=str(shim), MESA_LOG='')
    if stalled:
        env.update(HOSTSIM_STALL='17', HOSTSIM_TRACE='1')
    started_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run([str(plugin), str(driver)], cwd=root, env=env,
                                capture_output=True, text=True, timeout=300)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        def decoded(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')
        stdout, stderr, returncode = decoded(error.stdout), decoded(error.stderr), None
    elapsed = time.monotonic() - started
    records = {}
    for suffix, content in [('stdout.log', stdout), ('stderr.log', stderr)]:
        raw = content.encode('utf-8')
        need(len(raw) <= 16 * CHUNK and b'\x00' not in raw and not raw.startswith(b'MTLB'),
             'Unexpected or oversized diagnostic text')
        target = output / (name + '-' + suffix)
        with target.open('xb') as stream:
            stream.write(raw)
        records[suffix] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    verdict = original_watchdog_gate(returncode, stdout) if stalled else dict(
        passed=(returncode == 0 and not timed_out), original_plugin_returncode_criterion=True)
    if timed_out:
        verdict['passed'] = False
    summary = dict(name=name, started_utc=started_utc, finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   wall_clock_seconds=elapsed, returncode=returncode, timed_out=timed_out,
                   original_timeout_seconds=300, stdin='none', cwd=str(root),
                   explicit_environment=dict(DYLD_INSERT_LIBRARIES=str(shim), MESA_LOG='',
                       TU_DARWIN_SERVICE='absent before plugin sets authored default',
                       HOSTSIM_STALL='17' if stalled else 'absent', HOSTSIM_TRACE='1' if stalled else 'absent',
                       HOSTSIM_PAGE_SIZE='absent; author29a does not set it'),
                   inherited_injection_variables_removed=removed,
                   frozen_C9_source_or_binary_modified=False, compiled_source_variant=variant,
                   added_observability='HOSTSIM_TRACE=1 and outer monotonic duration only' if stalled else 'outer monotonic duration only',
                   result=verdict, output_files=records)
    write_json(output / (name + '-case.json'), summary)
    print(json.dumps(dict(case=name, wall_clock_seconds=elapsed, returncode=returncode,
                          timed_out=timed_out, original_gate_passed=verdict['passed'])), flush=True)
    return summary


def compile_smokes(policy, root, output):
    source = Path(__file__).with_name('watchdog-ab-src')
    expected_names = {'NativeTurnipSmoke.before.h', 'NativeTurnipSmoke.monotonic.h', 'plugin_smoke.cpp',
                      'gen-turnip-smoke-shaders.py', 'smoke_fill.comp', 'smoke_triangle.frag', 'smoke_triangle.vert'}
    need(set(policy['ab_sources']) == expected_names, 'Unexpected A/B source inventory')
    for name, expected in policy['ab_sources'].items():
        path = source / name
        need(path.is_file() and not path.is_symlink() and path.stat().st_size == expected['bytes'] and
             sha(path) == expected['sha256'], 'A/B source identity mismatch: ' + name)
    original = (source / 'NativeTurnipSmoke.before.h').read_text()
    patched = original.replace('#include <dlfcn.h>', '#include <chrono>\n#include <dlfcn.h>')
    patched = patched.replace('    const bool started = pthread_create(&worker, &attr, watchedWorker, w) == 0;',
                              '    const auto watchdogStart = std::chrono::steady_clock::now();\n    const bool started = pthread_create(&worker, &attr, watchedWorker, w) == 0;')
    patched = patched.replace('for (unsigned tenths = 0; !__atomic_load_n(&w->done, __ATOMIC_ACQUIRE); ++tenths)',
                              'for (; !__atomic_load_n(&w->done, __ATOMIC_ACQUIRE);)')
    patched = patched.replace('tenths == checkpoints[next] * 10',
                              'std::chrono::steady_clock::now() - watchdogStart >= std::chrono::seconds(checkpoints[next])')
    need(patched == (source / 'NativeTurnipSmoke.monotonic.h').read_text(), 'Timer patch contains unrelated changes')
    scripts = root / 'scripts'; scripts.mkdir()
    shutil.copyfile(source / 'gen-turnip-smoke-shaders.py', scripts / 'gen-turnip-smoke-shaders.py')
    shaders = root / 'drivers/AdrenoMetal/shaders'; shaders.mkdir(parents=True)
    for name in sorted(expected_names):
        if name.startswith('smoke_'):
            shutil.copyfile(source / name, shaders / name)
    command(['glslc', '--version'], output / 'glslc-version.log')
    command(['spirv-val', '--version'], output / 'spirv-val-version.log')
    command(['brew', 'list', '--versions', 'vulkan-headers'], output / 'vulkan-headers-version.log')
    command([sys.executable, '-B', scripts / 'gen-turnip-smoke-shaders.py'], output / 'generate-public-smoke-shaders.log', 120)
    generated = root / 'build/turnip-smoke/NativeTurnipShaders.h'
    text = generated.read_text()
    need(generated.stat().st_size > 1024 and all(name in text for name in
         ['kSpv_smoke_fill_comp', 'kSpv_smoke_triangle_vert', 'kSpv_smoke_triangle_frag']), 'Generated public shaders incomplete')
    generated_sha = sha(generated)
    compiled = {}
    for variant, header_source in [('original', 'NativeTurnipSmoke.before.h'), ('monotonic', 'NativeTurnipSmoke.monotonic.h')]:
        directory = root / ('build/watchdog-' + variant); directory.mkdir()
        cpp, header = directory / 'plugin_smoke.cpp', directory / 'NativeTurnipSmoke.h'
        shutil.copyfile(source / 'plugin_smoke.cpp', cpp)
        shutil.copyfile(source / header_source, header)
        executable, dependencies = directory / 'plugin_smoke', directory / 'headers.d'
        argv = ['xcrun', 'clang++', '-std=c++17', '-O1', '-MMD', '-MF', str(dependencies),
                '-I', '/opt/homebrew/include', '-I', str(generated.parent), str(cpp), '-o', str(executable)]
        command(argv, output / ('compile-' + variant + '.log'), 120)
        dependency_text = dependencies.read_text().replace('\\\n', ' ')
        need(str(header) in dependency_text and str(generated) in dependency_text,
             'Compiler did not consume the intended variant/common shader header')
        other = root / ('build/watchdog-' + ('monotonic' if variant == 'original' else 'original')) / 'NativeTurnipSmoke.h'
        need(str(other) not in dependency_text, 'Compiler consumed opposite variant header')
        command(['/usr/bin/codesign', '--force', '--sign', '-', '--pagesize', '4096', '--identifier',
                 'org.blu-sharky.watchdog-ab.' + variant, executable], output / ('sign-' + variant + '.log'))
        command(['/usr/bin/codesign', '--verify', '--strict', executable], output / ('verify-' + variant + '.log'))
        detail = command(['/usr/bin/codesign', '--display', '--verbose=4', executable], output / ('details-' + variant + '.log'))
        cdhash = re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)
        need(cdhash is not None and re.search(r'^Page size=4096$', detail, re.M), 'Fresh smoke signature identity/granule mismatch')
        info = facts(executable); need(info['filetype'] == 2, 'Fresh smoke is not an executable')
        compiled[variant] = dict(path=executable, sha256=sha(executable), bytes=executable.stat().st_size,
            cdhash=cdhash[1], macho=info, real_codesign_strict_verified=True, compile_argv=argv,
            source_cpp_sha256=sha(cpp), source_header_sha256=sha(header), generated_shader_sha256=generated_sha,
            intended_header_confirmed_in_compiler_dependencies=True)
    need(sha(generated) == generated_sha and all(sha(source / name) == info['sha256']
         for name, info in policy['ab_sources'].items()), 'A/B sources or common shaders mutated')
    return compiled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root, output = args.work.resolve(), args.output.resolve()
    need(root.parent == output.parent and root != output and not root.exists() and not output.exists(),
         'Fresh separate sibling work and diagnostic output required')
    root.mkdir()
    output.mkdir()
    report = dict(schema='unixnu.watchdog-monotonic-fresh-AB-diagnostic.v1',
        status='WATCHDOG_DIAGNOSTIC_PENDING_NOT_INSTALL_READY', diagnostic_executed=False,
        production_sources_modified=False, frozen_binaries_modified=False, no_Rust_or_Mesa_rebuild=True, only_two_small_smokes_recompiled=True,
        installation_ready=False, hardware_GPU_execution_verified=False, cases=[], maximum_cases=3,
        full_host_qualification_claimed=False, original_watchdog_predicate_unchanged=True)
    baseline, restored = {}, {}
    code = 2
    try:
        need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'macOS ARM64 required')
        policy_path = Path(__file__).with_name('watchdog-ab-policy.json')
        need(sha(policy_path) == POLICY_SHA, 'Unreviewed watchdog policy')
        policy = json.loads(policy_path.read_text())
        need(policy['run_attempt'] == 3 and policy['original_stall_seconds'] == 17 and
             policy['original_case_timeout_seconds'] == 300 and policy['maximum_cases'] == 3,
             'Original watchdog configuration changed')
        token = os.environ.pop('GH_ARTIFACT_TOKEN', '')
        need(bool(token), 'Read-only artifact token missing')
        scratch = Path(tempfile.mkdtemp(prefix='watchdog-recovery-', dir=root.parent))
        archive = scratch / 'fixed-C9-attempt3-recovery.zip'
        def expired(signum, frame):
            raise RuntimeError('Fixed artifact reception deadline exceeded')
        previous = signal.signal(signal.SIGALRM, expired)
        signal.alarm(180)
        try:
            report['provenance'] = download(policy, token, archive)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
            token = None
        restored, missing = restore(policy, archive, root)
        need(missing == [], 'C9 recovery must have no manifested omissions')
        report['all_present_manifested_members_verified'] = True
        report['manifest_sha256'] = policy['manifest_sha256']
        report['exact_manifested_omissions'] = missing
        profile = json.loads((root / 'build/mesa-tu/builtin-build-profile.json').read_text())
        need(profile == policy['profile'], 'Recovered compiler profile changed')
        identity = profile['profile']
        need(hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
             == profile['source_id'], 'Recovered source/profile identity mismatch')
        need(command(['/usr/bin/clang++', '--version'], output / 'current-compiler.log') == identity['compiler'],
             'Current Apple compiler differs from C9 profile')
        need(command(['xcrun', '--sdk', 'macosx', '--show-sdk-version'], output / 'current-sdk.log') == '26.5',
             'Actual macOS SDK changed')
        version = command(['sw_vers', '-productVersion'], output / 'current-os.log')
        parts = [int(value) for value in version.split('.')] + [0, 0]
        packed = (parts[0] << 16) | (parts[1] << 8) | parts[2]
        need(parts[0] >= 26, 'Host older than recovered minimum macOS26')
        need(command(['brew', 'list', '--versions', 'spirv-tools'], output / 'spirv-tools-version.log')
             == 'spirv-tools ' + policy['spirv_tools_version'], 'SPIRV dependency version changed')
        dependency = Path('/opt/homebrew/opt/spirv-tools/lib/libSPIRV-Tools.dylib').resolve(strict=True)
        need(Path('/opt/homebrew/Cellar/spirv-tools/' + policy['spirv_tools_version']) in dependency.parents,
             'Unexpected SPIRV dependency path')
        command(['/usr/bin/codesign', '--verify', '--strict', dependency], output / 'dependency-codesign.log')
        dependency_facts = facts(dependency)
        expected_dependency = policy['actual_C9_SPIRV_dependency']
        need(sha(dependency) == expected_dependency['sha256'] and dependency_facts == expected_dependency['macho'],
             'Actual SPIRV dependency differs from C9 recorded bytes/profile')
        need(dependency_facts['filetype'] == 6 and len(dependency_facts['builds']) == 1 and
             dependency_facts['builds'][0][0] == 1 and dependency_facts['builds'][0][1] <= packed,
             'Invalid SPIRV Mach-O target')
        need(all(name.startswith(('/usr/lib/', '/System/Library/Frameworks/')) for name in dependency_facts['dependencies']),
             'Unreviewed transitive SPIRV dependency')
        report['current_SPIRV_dependency'] = dict(sha256=sha(dependency), macho=dependency_facts,
            codesign_strict_verified_on_this_Mac=True, actual_C9_dependency_identity_matched=True,
            exact_previous_C6_dependency_hash_available=False)
        report['cached_inputs'] = {}
        for index, (name, target) in enumerate(restored.items()):
            expected = policy['required'][name]
            executable = 'macho' in expected and expected['macho']['filetype'] == 2
            if 'macho' in expected:
                need(all(build[0] == 1 and build[1] <= packed for build in expected['macho']['builds']),
                     'Recovered executable target too new')
                command(['/usr/bin/codesign', '--verify', '--strict', target], output / ('codesign-' + str(index) + '.log'))
                details = command(['/usr/bin/codesign', '--display', '--verbose=4', target],
                                  output / ('codesign-details-' + str(index) + '.log'))
                match = re.search(r'^CDHash=([0-9a-f]{40})$', details, re.M)
                need(match is not None and match[1] == expected['macho']['cdhash'], 'Actual cached CDHash mismatch')
            target.chmod(0o555 if executable else 0o444)
            baseline[name] = sha(target)
            report['cached_inputs'][name] = dict(bytes=target.stat().st_size, sha256=baseline[name],
                frozen_before_diagnostic=True, codesign_checked_on_this_Mac='macho' in expected,
                readonly_mode='0555' if executable else '0444')
        driver = root / 'build/mesa-tu/src/freedreno/vulkan/libvulkan_freedreno.dylib'
        shim = root / 'build/turnip-darwin-host/libhostiokit.dylib'
        compiled = compile_smokes(policy, root, output)
        report['fresh_compiles'] = {k: {n: str(v) if isinstance(v, Path) else v for n, v in data.items()} for k, data in compiled.items()}
        report['comparison_scope'] = 'Fresh A/B share generated public GLSL header, compiler, options, frozen driver/shim; only timer header changes'
        report['diagnostic_executed'] = True
        original = run_case('original-watchdog', True, compiled['original']['path'], driver, shim, root, output, 'original')
        report['cases'].append(original)
        need(original['returncode'] == 0 and not original['timed_out'], 'Fresh original software sequence failed beyond watchdog criterion')
        normal = run_case('monotonic-normal', False, compiled['monotonic']['path'], driver, shim, root, output, 'monotonic')
        report['cases'].append(normal)
        stalled = run_case('monotonic-watchdog', True, compiled['monotonic']['path'], driver, shim, root, output, 'monotonic')
        report['cases'].append(stalled)
        need(len(report['cases']) == 3, 'Diagnostic case bound changed')
        need(all(sha(target) == baseline[name] for name, target in restored.items()), 'Frozen C9 inputs changed during A/B')
        report['unchanged_cached_input_hashes_reverified'] = True
        report['original_miss_reproduced'] = not original['result']['passed'] and original['result']['samples'] == []
        report['patched_original_predicate_passed'] = normal['result']['passed'] and stalled['result']['passed']
        report['causal_conclusion'] = ('ONLY_TIMER_HEADER_CHANGED_AND_ORIGINAL_MISS_REPRODUCED_PATCHED_GATE_PASSED'
            if report['original_miss_reproduced'] and report['patched_original_predicate_passed'] else
            'BASELINE_NOT_REPRODUCED_CAUSAL_COMPARISON_INCONCLUSIVE' if original['result']['passed'] else
            'PATCH_STILL_FAILS_OR_ORIGINAL_FAILURE_DIFFERS')
        if report['patched_original_predicate_passed']:
            report['status'] = 'MONOTONIC_PATCH_PASSES_ORIGINAL_GATES_HOST_DIAGNOSTIC_ONLY'
            code = 0
        else:
            report['status'] = 'MONOTONIC_PATCH_NOT_QUALIFIED_ORIGINAL_GATE_FAILED'
            code = 1
    except Exception as error:
        report['error_type'] = type(error).__name__
        report['error'] = str(error) if isinstance(error, RuntimeError) else 'Prerequisite or network diagnostic failed; request URLs and signed credentials omitted'
        report['status'] = 'WATCHDOG_DIAGNOSTIC_FAILED_NOT_INSTALL_READY'
    finally:
        if baseline:
            report['cached_input_hashes_after_attempt'] = {name: sha(target) for name, target in restored.items()}
            if any(report['cached_input_hashes_after_attempt'][name] != baseline[name] for name in baseline):
                report['status'] = 'WATCHDOG_FROZEN_INPUT_MUTATION_REFUSED'
                code = 2
        write_json(output / 'watchdog-diagnostic-report.json', report)
        allowed = {'watchdog-diagnostic-report.json', 'current-compiler.log', 'current-sdk.log', 'current-os.log',
                   'spirv-tools-version.log', 'dependency-codesign.log'}
        allowed.update('codesign-' + str(index) + '.log' for index in range(4))
        allowed.update('codesign-details-' + str(index) + '.log' for index in range(4))
        for name in ['original-watchdog', 'monotonic-normal', 'monotonic-watchdog']:
            allowed.update({name + '-stdout.log', name + '-stderr.log', name + '-case.json'})
        allowed.update({'glslc-version.log', 'spirv-val-version.log', 'vulkan-headers-version.log', 'generate-public-smoke-shaders.log'})
        for variant in ['original', 'monotonic']:
            allowed.update(prefix + '-' + variant + '.log' for prefix in ['compile', 'sign', 'verify', 'details'])
        for target in output.iterdir():
            need(target.is_file() and not target.is_symlink() and target.name in allowed and target.stat().st_size <= 16 * CHUNK,
                 'Unexpected diagnostic output refused')
            raw = target.read_bytes()
            need(b'\x00' not in raw and not raw.startswith(b'MTLB'), 'Binary payload refused from diagnostic output')
            raw.decode('utf-8')
            if target.suffix == '.json':
                need(isinstance(json.loads(raw), dict), 'Expected diagnostic metadata object')
        print(json.dumps(dict(status=report['status'], cases=len(report['cases']),
            diagnostic_executed=report['diagnostic_executed'], installation_ready=False)), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
