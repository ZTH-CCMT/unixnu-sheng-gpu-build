"""Build source-pinned candidate GPU components on real macOS; never install."""
import argparse, datetime, hashlib, json, os, platform, shutil, subprocess, sys, threading, time
from pathlib import Path
from verify_gpu_artifacts import check, require

MAIN = '6790e7ce6e77f67a9174fba1255e64eacf1c41ad'
DEVICE = '28b30285768e04008ac525c04182e245bfac441e'
MESA = '85fda3b36405bcaea8bffc64aa4f2651dc90770d'
TRANSLATOR = '624bab3918de5b978e1101517abca2b4fa426565'
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--device', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
a = parser.parse_args()
root, device, output = a.root.resolve(), a.device.resolve(), a.output.resolve()
require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Real ARM64 macOS runner required')
require(not output.exists(), 'Use fresh output; preserve previous candidates')
output.mkdir(parents=True)
logs = output / 'logs'
logs.mkdir()
require(shutil.disk_usage(root).free  >= 8 * 1024**3, 'At least8GiB free after tools required')
env = dict(os.environ, CARGO_BUILD_JOBS='1', RUSTUP_TOOLCHAIN='1.98.0', PYTHONDONTWRITEBYTECODE='1')

def run(argv, name, timeout=1800, cwd=root):
    started = time.monotonic()
    stopped = threading.Event()
    def progress():
        while not stopped.wait(30):
            print(json.dumps(dict(phase=name, state='running', elapsed_seconds=int(time.monotonic()-started))), flush=True)
    print(json.dumps(dict(phase=name, state='started', timeout_seconds=timeout)), flush=True)
    reporter = threading.Thread(target=progress, daemon=True)
    reporter.start()
    try:
        with (logs / (name + '.log')).open('wb') as stream:
            r = subprocess.run(list(map(str, argv)), cwd=cwd, env=env,
                               stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        print(json.dumps(dict(phase=name, state='completed', exit_code=r.returncode,
                              elapsed_seconds=round(time.monotonic()-started, 3))), flush=True)
        require(r.returncode == 0, 'Failed phase ' + name + '; see bounded artifact logs')
    except BaseException:
        print(json.dumps(dict(phase=name, state='failed', elapsed_seconds=round(time.monotonic()-started, 3))), flush=True)
        raise
    finally:
        stopped.set()
        reporter.join(timeout=1)

def read(argv, cwd=root):
    return subprocess.check_output(list(map(str, argv)), cwd=cwd, env=env,
                                   text=True, timeout=30).strip()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

require(read(['git', 'rev-parse', 'HEAD']) == MAIN, 'Wrong UniXNU source')
require(read(['git', 'rev-parse', 'HEAD'], device) == DEVICE, 'Wrong device source')
require(read(['git', 'status', '--porcelain']) == '', 'Source checkout must start clean')
# Resource-only adapters call the real tool, preserving all source and build flags.
tool_adapters = root / 'build/ci-tools'
tool_adapters.mkdir(parents=True)
real_ninja, real_make = shutil.which('ninja'), shutil.which('make')
require(real_ninja and real_make, 'Real Ninja and make required')
for name, real in [('ninja', real_ninja), ('make', real_make)]:
    p = tool_adapters / name
    p.write_text('#!' + sys.executable + '\nimport os,sys\nos.execv(' + repr(real) +
                 ', [' + repr(real) + '] + sys.argv[1:] + ["-j2"])\n')
    p.chmod(0o755)
env['PATH'] = str(tool_adapters) + os.pathsep + env['PATH']

sdk = Path(read(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']))
macsdk = Path(read(['xcrun', '--sdk', 'macosx', '--show-sdk-path']))
for p in [sdk / 'SDKSettings.plist', sdk / 'usr/include/stdio.h',
          sdk / 'System/Library/Frameworks/Metal.framework/Headers/Metal.h',
          macsdk / 'System/Library/Frameworks/IOKit.framework/Headers/IOKitLib.h',
          Path('/opt/homebrew/include/vulkan/vulkan.h')]:
    require(p.is_file(), 'Missing real SDK input: ' + str(p))
for tool in ['clang', 'clang++', 'codesign', 'xcodebuild', 'glslangValidator', 'glslc',
             'spirv-val', 'cmake', 'ninja', 'cargo', 'llvm-as']:
    require(shutil.which(tool) is not None, 'Missing real build tool ' + tool)
cargo_version = read(['cargo', '--version'])
rust_version = read(['rustc', '--version'])
installed_targets = read(['rustup', 'target', 'list', '--installed', '--toolchain', '1.98.0']).splitlines()
require(cargo_version.startswith('cargo 1.98.0 '), 'Wrong effective Cargo toolchain')
require(rust_version.startswith('rustc 1.98.0 '), 'Wrong effective rustc toolchain')
require('aarch64-apple-ios' in installed_targets, 'iOS standard library target missing')
llvm_version = read(['llvm-as', '--version'])
import re
require(int(re.search(r'(?:LLVM version|version)\s+(\d+)', llvm_version)[1]) >= 21, 'LLVM21+ required')

# A real cross-link and byte-level signature check fails before long compilation.
probe_dir = root / 'build/ci-sdk-probe'
probe_dir.mkdir(parents=True)
(probe_dir / 'probe.c').write_text('int main(void) { return 0; }\n')
run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk,
     probe_dir / 'probe.c', '-o', probe_dir / 'probe'], 'real-sdk-link', 60)
run(['codesign', '--force', '--sign', '-', '--pagesize', '4096',
     probe_dir / 'probe'], 'real-sdk-sign', 30)
probe_identity = check(probe_dir / 'probe', 2)

selected = ['drivers/Adreno740', 'drivers/AdrenoMetal', 'kits/AdrenoPM4', 'kits/ArmSmmu4K']
run(['git', 'submodule', 'update', '--init', '--recursive', '--', *selected],
    'exact-component-checkouts', 600)
gitlinks = {}
for p in selected:
    row = read(['git', 'ls-tree', 'HEAD', p]).split()
    expected = row[2]
    actual = read(['git', 'rev-parse', 'HEAD'], root / p)
    require(row[0] == '160000' and actual == expected, 'Submodule gitlink mismatch ' + p)
    require(read(['git', 'status', '--porcelain'], root / p) == '', 'Dirty component ' + p)
    gitlinks[p] = actual

# Assemble only the device host compiler/probe input, keeping producer sources intact.
source = device / 'scripts/build-adreno-compiler-host.py'
target = root / 'scripts/build-adreno-compiler-host.py'
require(not target.exists(), 'Unexpected existing device compiler script')
shutil.copy2(source, target)
require(not (root / 'kits/sheng').exists(), 'Unexpected pre-existing board package')
shutil.copytree(device / 'package', root / 'kits/sheng')
overlays = {'scripts/build-adreno-compiler-host.py': sha(target)}
# The pinned host-only fixture predates APIs now used by the pinned driver.
# Hash-bound test doubles only: production kernel/plugin/Turnip/bridge stay unmodified.
fixture = root / 'drivers/Adreno740/tests/XnuMemoryFixture.h'
fixture_before = 'e316a1d4606c2fa52671fb15855f1d76e2cfd827f6d91f950aaf6452d596b04e'
fixture_after = '18015ab4e9bc6a276b7c5aaf09571ba84e6d5936ede5f419a211c6dbb808f55f'
fixture_overlay = Path(__file__).resolve().parent / 'host-XnuMemoryFixture.h'
require(sha(fixture) == fixture_before, 'Pinned host fixture changed')
require(sha(fixture_overlay) == fixture_after, 'Unreviewed host fixture overlay')
fixture.write_bytes(fixture_overlay.read_bytes())
host_private = root / 'build/turnip-darwin-host/host-include/sys/resource_private.h'
require(not host_private.exists(), 'Fresh host private-header shim required')
private_overlay = Path(__file__).resolve().parent / 'host-resource-private.h'
private_sha = 'fb9dd31b1b0a82c7bc64223a8a475d1408b661fd1a3efdcca62930a5aa802292'
require(sha(private_overlay) == private_sha, 'Unreviewed host role-constant fixture')
host_private.parent.mkdir(parents=True, exist_ok=True)
host_private.write_bytes(private_overlay.read_bytes())
overlays['drivers/Adreno740/tests/XnuMemoryFixture.h'] = sha(fixture)
overlays['build/turnip-darwin-host/host-include/sys/resource_private.h'] = sha(host_private)
print(json.dumps(dict(phase='host-fixture-compatibility', original_sha256=fixture_before,
                     patched_sha256=sha(fixture), scope='host test fixture only')), flush=True)
# Complete the author's host-only software peer link, with exact input identities.
peer_source = root / 'scripts/check-turnip-darwin-host.py'
expected_blob = '57d153282f45b0410870d5022870cb2d317ae74c'
require(read(['git', 'hash-object', peer_source]) == expected_blob, 'Original host peer source changed')
require(sha(peer_source) == '7ab580b33aa544a0e8931679884d2aa717e5663d6d9ff52ee5cda90c128862c0', 'Original host script bytes changed')
peer_overlay = Path(__file__).resolve().parent / 'host-check-turnip-darwin-host.py'
peer_after = '29a805edbf1905112029d7e0adca8668fa6781265a03f571f1760a566fe7732b'
require(sha(peer_overlay) == peer_after, 'Unreviewed host Preempt build list')
peer_source.write_bytes(peer_overlay.read_bytes())
service = root / 'drivers/Adreno740/tests/hostsim/host_gpu_service.cpp'
service_before = '4ef75c3cf644cdc3ead973e568a580124dfe3aaf0527c93770d5ac1c1cd7810b'
service_after = '198d5e3ce6c2b2d9af1dd14f257e4a89e672e67873a92bee2e5f7090038c361e'
service_overlay = Path(__file__).resolve().parent / 'host-gpu-service.cpp'
require(sha(service) == service_before and sha(service_overlay) == service_after, 'Host clock overlay identity mismatch')
service.write_bytes(service_overlay.read_bytes())
overlays['scripts/check-turnip-darwin-host.py'] = sha(peer_source)
overlays['drivers/Adreno740/tests/hostsim/host_gpu_service.cpp'] = sha(service)
# A genuine Mac SDK compile+strict link before the long Mesa/Turnip builds.
# This exact prefix omits only the unused Turnip existence guard; no fake file is created.
preflight_source = Path(__file__).resolve().parent / 'host-link-preflight-prefix.py'
require(sha(preflight_source) == 'a3f12d39dc20fa084030566c68b7ad5b2797d6539dab0a09ffe46a244d36766d', 'Unreviewed early Mac link preflight')
preflight_wrapper = root / 'build/ci-host-link-preflight-wrapper.py'
preflight_wrapper.write_text("from pathlib import Path\np=Path(" + repr(str(peer_source)) +
    ")\nscope={'__file__':str(p),'__name__':'__ci_host_strict_link_preflight__'}\n" +
    "exec(compile(" + repr(preflight_source.read_text()) + ",str(p),'exec'),scope)\n")
run([sys.executable, preflight_wrapper], 'real-mac-host-peer-link-preflight', 180)
# Diagnostics only: retain the exact original runtime invocation and RD validation.
replay_source = root / 'scripts/gen-turnip-replay.py'
replay_before = 'd61c46c63835e0da62f9515c7667a2c8ce51d840b55294cee6c72a07ce1cb096'
replay_after = 'f217b7b59a0015f22277eedd856020b024d337ed2e1ce607c2ec47c8938ef6ee'
replay_overlay = Path(__file__).resolve().parent / 'host-gen-turnip-replay.py'
require(sha(replay_source) == replay_before and sha(replay_overlay) == replay_after,
        'Unreviewed host replay diagnostics')
replay_source.write_bytes(replay_overlay.read_bytes())
overlays['scripts/gen-turnip-replay.py'] = sha(replay_source)
compiler_inputs = json.loads((root / 'scripts/data/adreno-compiler-inputs.json').read_text())
translator_inputs = json.loads((root / 'scripts/data/gpu-metal-vulkan-inputs.json').read_text())
require(compiler_inputs['mesa']['commit'] == MESA, 'Wrong Mesa compiler pin')
require(translator_inputs['translator']['commit'] == TRANSLATOR, 'Wrong translator pin')
run([sys.executable, 'scripts/build-adreno-compiler-host.py'], 'prepare-mesa-host-tools', 1800)
require(read(['git', 'rev-parse', 'HEAD'], root / '.cache/mesa-work') == MESA, 'Mesa pin differs')

m2v = root / '.cache/gpu-reference/metal2vulkan'
require(not m2v.exists(), 'Fresh source-only translator required')
m2v.parent.mkdir(parents=True, exist_ok=True)
run(['git', 'init', m2v], 'translator-init', 30)
run(['git', '-C', m2v, 'remote', 'add', 'origin',
     translator_inputs['translator']['repository']], 'translator-origin', 30)
run(['git', '-C', m2v, 'fetch', '--depth=1', '--filter=blob:none', 'origin', TRANSLATOR],
    'translator-exact-fetch', 600)
run(['git', '-C', m2v, 'checkout', '--detach', 'FETCH_HEAD'], 'translator-checkout', 60)
require(read(['git', 'rev-parse', 'HEAD'], m2v) == TRANSLATOR, 'Translator pin differs')
run([sys.executable, 'scripts/build-turnip-darwin.py', '--target', 'host'],
    'turnip-host', 1800)

# The original replay generator needs the host software peer. Its default whole
# qualification script also needs original QuartzCore.metallib, which is deliberately
# absent here. Execute ONLY the exact pinned build prefix; no test-suite PASS claim.
require(sha(peer_source) == peer_after, 'Patched host peer source changed')
marker = "\nenv = dict(os.environ, DYLD_INSERT_LIBRARIES=str(shim), MESA_LOG='')\n"
text = peer_source.read_text()
require(text.count(marker) == 1, 'Pinned host-peer split marker changed')
prefix = text.split(marker, 1)[0]
prefix_file = root / 'build/ci-host-replay-peer-prefix.py'
prefix_file.write_text(prefix)
# __file__ must stay at scripts/ level because the unmodified prefix computes ROOT.
wrapper = root / 'build/ci-host-replay-peer-wrapper.py'
wrapper.write_text("import runpy\nfrom pathlib import Path\np=Path(" + repr(str(peer_source)) +
                   ")\nscope={'__file__':str(p),'__name__':'__ci_host_peer_build_only__'}\n" +
                   "exec(compile(" + repr(prefix) + ",str(p),'exec'),scope)\n")
run([sys.executable, wrapper], 'host-replay-peer-build-only', 600)
require((root / 'build/turnip-darwin-host/plugin_smoke').is_file(), 'Host replay peer missing')
run([sys.executable, 'scripts/gen-turnip-replay.py'],
    'host-replay-smoke-before-ios', 360)
run([sys.executable, 'scripts/build-turnip-darwin.py', '--target', 'ios'],
    'turnip-ios17', 1800)
run([sys.executable, 'scripts/build-adreno-metal-plugin.py'],
    'plugin-ios17', 2400)
producer = root / 'build/adreno-metal-plugin'
bundle = producer / 'NativeAdrenoMetal.bundle'
trust = json.loads((producer / 'trust.json').read_text())
identities = {
    'plugin': check(bundle / 'NativeAdrenoMetal', 8),
    'turnip': check(bundle / 'libvulkan_freedreno.dylib', 6),
    'probe_daemon': check(producer / 'adrenoprobed', 2),
}
for key, field in [('plugin', 'cdhash'), ('turnip', 'turnip_cdhash'), ('probe_daemon', 'daemon_cdhash')]:
    require(identities[key]['cdhash'] == trust[field], 'trust.json CDHash mismatch ' + key)
# Bundle resource seal in addition to Mach-O CodeDirectory page hashes.
run(['codesign', '--verify', '--strict', bundle], 'bundle-resource-seal', 30)
for p in producer.rglob('*'):
    require(not p.is_symlink(), 'Unexpected output symlink')
parts = output / 'components'
parts.mkdir()
shutil.copytree(bundle, parts / bundle.name)
shutil.copy2(producer / 'trust.json', parts / 'trust.json')
shutil.copy2(producer / 'adrenoprobed', parts / 'adrenoprobed')
for p in producer.glob('*.plist'):
    shutil.copy2(p, parts / p.name)
bridge = root / 'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a'
require(bridge.is_file() and bridge.stat().st_size > 4096, 'Missing real bridge archive')
shutil.copy2(bridge, parts / bridge.name)
lock = root / 'build/adreno-metal-bridge/Cargo.lock'
require(lock.is_file(), 'Actual resolved Cargo.lock missing')
shutil.copy2(lock, output / 'Cargo.lock')
(output / 'mesa-requirements.txt').write_text((root / 'scripts/requirements-adreno-compiler.txt').read_text())
for p in list((root / '.cache').glob('*.log')) + list((root / 'build/adreno-metal-bridge').glob('*.log')):
    if p.stat().st_size <= 32 * 1024**2:
        shutil.copy2(p, logs / ('producer-' + p.name))
require(sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) <= 2 * 1024**3,
        'Candidate artifact exceeds2GiB bound')
output_hashes = {str(p.relative_to(output)): dict(bytes=p.stat().st_size, sha256=sha(p))
                 for p in sorted(output.rglob('*')) if p.is_file()}
manifest = dict(
    status='CANDIDATE_COMPONENTS_BUILT_SIGNED_NOT_INSTALL_READY',
    qualification='REQUIRED_PENDING_ORIGINAL_INPUT',
    original_input_qualification=dict(
        required_library='iPadOS17.7.11-21H461 QuartzCore/default.metallib',
        sha256='606f913adf520420f9b4bb666efb782a68c830f082f1e559e17b20d0d13adbc9',
        required_suite='scripts/check-quartzcore-turnip-cache-host.py',
        additional_suite='scripts/check-priming-cache-host.py',
        completed=False,
        reason='No original Apple OS input is fetched/uploaded by this source-only job'),
    exact_sources=dict(UniXNU=MAIN, device=DEVICE, components=gitlinks, Mesa=MESA,
                       translator=TRANSLATOR, overlays=overlays),
    source_split=dict(original_script_blob=expected_blob,
        prefix_sha256=hashlib.sha256(prefix.encode()).hexdigest(),
        mode='host software peer compilation only; original complete suite NOT run',
        replay_diagnostics=dict(original_sha256=replay_before, patched_sha256=sha(replay_source),
            original_command_environment_timeout_and_RD_validation_unchanged=True,
            early_host_replay_smoke_passed=True),
        host_link_compatibility=dict(original_script_blob=expected_blob, patched_script_sha256=sha(peer_source),
            original_service_sha256=service_before, patched_service_sha256=sha(service),
            early_Mac_strict_link_passed=True, early_prefix_sha256=sha(preflight_source)),
        host_fixture_compatibility=dict(original_sha256=fixture_before, patched_sha256=sha(fixture),
            role_constants_sha256=sha(host_private), default_role='explicit host unmanaged; not real OS task role'),
        plugin_Turnip_bridge_sources_modified=False),
    toolchain=dict(platform=platform.platform(), sdk=str(sdk),
        sdk_version=read(['xcrun', '--sdk', 'iphoneos', '--show-sdk-version']),
        sdk_settings_sha256=sha(sdk / 'SDKSettings.plist'),
        macos_sdk=str(macsdk), xcode=read(['xcodebuild', '-version']),
        llvm=llvm_version, rust=rust_version, cargo=cargo_version, rustup_toolchain=env['RUSTUP_TOOLCHAIN'],
        rust_installed_targets=installed_targets, LLVM_CONFIG_PATH_required=False,
        brew=read(['brew', 'list', '--versions', 'llvm', 'ninja', 'cmake', 'glslang',
                   'shaderc', 'spirv-tools', 'vulkan-headers', 'bison', 'pkgconf', 'rustup']),
        cargo_lock_sha256=sha(lock),
        real_signature_probe=probe_identity,
        concurrency=dict(cargo_jobs=1, real_ninja=real_ninja, real_make=real_make,
                         adapter_max_jobs=2)),
    binaries=identities, outputs=output_hashes,
    no_device_seed_private_key_or_OS_images=True,
    hardware_GPU_execution_verified=False,
    created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(output / 'input-output-manifest.json').write_text(json.dumps(manifest, indent=2))
(output / 'REQUIRED_PENDING_ORIGINAL_INPUT.txt').write_text(
    'CANDIDATE ONLY. Complete original-input and physical GPU qualification before installation.\n')
print(json.dumps(dict(status=manifest['status'], qualification=manifest['qualification'],
                     binaries=identities), indent=2))
