"""Explicit authenticated C6 host-build reuse and reviewed Q layout; full controls and real iOS components; never install."""
import argparse, datetime, hashlib, json, os, platform, shutil, subprocess, sys, threading, time
from pathlib import Path
from verify_gpu_artifacts import check, require
from qualify_gpu_host import matching_original_input, qualify_author_host
from reuse_frozen_host import prepare_frozen_host, setup_source_tools_and_revalidate_IR3, verify_reused_host_inputs, reviewed_Q_adapter_record

MAIN = '6790e7ce6e77f67a9174fba1255e64eacf1c41ad'
DEVICE = '28b30285768e04008ac525c04182e245bfac441e'
MESA = '85fda3b36405bcaea8bffc64aa4f2651dc90770d'
TRANSLATOR = '624bab3918de5b978e1101517abca2b4fa426565'
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--device', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--source-plan', type=Path, required=True)
a = parser.parse_args()
root, device, output = a.root.resolve(), a.device.resolve(), a.output.resolve()
require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Real ARM64 macOS runner required')
require(not output.exists(), 'Use fresh output; preserve previous candidates')
output.mkdir(parents=True)
logs = output / 'logs'
logs.mkdir()
require(shutil.disk_usage(root).free  >= 8 * 1024**3, 'At least8GiB free after tools required')
artifact_token = os.environ.pop('GH_ARTIFACT_TOKEN', None)
env = dict(os.environ, CARGO_BUILD_JOBS='1', RUSTUP_TOOLCHAIN='1.98.0', PYTHONDONTWRITEBYTECODE='1')
for credential_name in ['GH_ARTIFACT_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN']:
    env.pop(credential_name, None)

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
# This fixture block is host-only; the shared watchdog timer correction is declared separately below.
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
# Exact host-only link closure: include the production preempt core as-is and
# provide the already-used host monotonic microsecond clock to diagnostics.
host_link_repairs = [
    ('scripts/check-turnip-darwin-host.py', 'host-check-turnip-darwin-host.py',
     '7ab580b33aa544a0e8931679884d2aa717e5663d6d9ff52ee5cda90c128862c0',
     '29a805edbf1905112029d7e0adca8668fa6781265a03f571f1760a566fe7732b'),
    ('drivers/Adreno740/tests/hostsim/host_gpu_service.cpp', 'host-host_gpu_service.cpp',
     '4ef75c3cf644cdc3ead973e568a580124dfe3aaf0527c93770d5ac1c1cd7810b',
     'ffa33ecae11ac485f7aa0339232169afb7206a55206cfe515284ca7052d09e7f'),
]
for relative, asset, before_sha, after_sha in host_link_repairs:
    target = root / relative
    overlay = Path(__file__).resolve().parent / asset
    require(sha(target) == before_sha and sha(overlay) == after_sha,
            'Unreviewed host link-closure source ' + relative)
    target.write_bytes(overlay.read_bytes())
    overlays[relative] = sha(target)
print(json.dumps(dict(phase='host-link-closure', scope='host tests only',
                     full_author_test_logic_preserved=True)), flush=True)
# Diagnostics only; keep the original runtime call, environment and RD acceptance.
replay_source = root / 'scripts/gen-turnip-replay.py'
replay_before = 'd61c46c63835e0da62f9515c7667a2c8ce51d840b55294cee6c72a07ce1cb096'
replay_after = 'f217b7b59a0015f22277eedd856020b024d337ed2e1ce607c2ec47c8938ef6ee'
replay_overlay = Path(__file__).resolve().parent / 'host-gen-turnip-replay.py'
require(sha(replay_source) == replay_before and sha(replay_overlay) == replay_after,
        'Unreviewed host replay diagnostics')
replay_source.write_bytes(replay_overlay.read_bytes())
overlays['scripts/gen-turnip-replay.py'] = sha(replay_source)
# Shared plugin smoke watchdog: the original sleep counter missed a real 17s
# stall. Exact clock-only correction passed the original 17s/one6004/v-frame
# host gate in a controlled A/B; no Vulkan/Turnip/bridge/kernel algorithm changes.
watchdog_path = root / 'drivers/AdrenoMetal/NativeTurnipSmoke.h'
watchdog_original = '4ad86aa579652ce980dd02a30f8b2e9c12cc98c21187cc071dcdb1b71d313c2d'
watchdog_patched = 'e6672093f9c7089f213c1cdc910614ebd78c008b15da715c9ebcdcbca9056d94'
watchdog_asset = Path(__file__).resolve().parent / 'watchdog-ab-src/NativeTurnipSmoke.monotonic.h'
require(sha(watchdog_path) == watchdog_original and sha(watchdog_asset) == watchdog_patched,
        'Unreviewed shared watchdog monotonic source correction')
watchdog_path.write_bytes(watchdog_asset.read_bytes())
overlays['drivers/AdrenoMetal/NativeTurnipSmoke.h'] = sha(watchdog_path)
watchdog_patch_record = dict(path='drivers/AdrenoMetal/NativeTurnipSmoke.h',
    original_sha256=watchdog_original, patched_sha256=watchdog_patched,
    purpose='Use steady_clock elapsed deadlines15/45/90; original17s host predicate retained',
    original_host_predicate_unchanged=True)
compiler_inputs = json.loads((root / 'scripts/data/adreno-compiler-inputs.json').read_text())
translator_inputs = json.loads((root / 'scripts/data/gpu-metal-vulkan-inputs.json').read_text())
require(compiler_inputs['mesa']['commit'] == MESA, 'Wrong Mesa compiler pin')
require(translator_inputs['translator']['commit'] == TRANSLATOR, 'Wrong translator pin')
require(artifact_token is not None, 'Fixed C6 artifact token missing')
# No generic build subprocess inherits the read-only API token.
receipt_env = dict(env, GH_ARTIFACT_TOKEN=artifact_token)
host_reuse, host_reuse_policy = prepare_frozen_host(root, a.source_plan.resolve(), logs, receipt_env)
artifact_token = None
setup_source_tools_and_revalidate_IR3(root, logs, run, env, host_reuse, host_reuse_policy)
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
# Author-supported preparation validates exact24patch source/tree and writes
# public fixture AIR/manifest, then exits before Cargo. Host archive is reused.
run([sys.executable, 'scripts/build-adreno-metal-bridge.py', '--target', 'host', '--manifest-only'],
    'bridge-host-source-manifest-only', 180)
verify_reused_host_inputs(root, host_reuse)

# All complete host control commands execute; only authenticated host-build production is reused.
with matching_original_input(root, logs) as original_input:
    host_qualification = qualify_author_host(root, device, logs, run, host_reuse)
require(original_input['cleanup_completed'], 'Owned original-input cleanup must complete')
require(sha(watchdog_path) == watchdog_patched, 'Watchdog source changed during complete host controls')
overlays['scripts/check-quartzcore-turnip-cache-host.py'] = host_qualification['checker_sources']['check-quartzcore-turnip-cache-host.py']
require((root / 'build/turnip-darwin-host/plugin_smoke').is_file(), 'Qualified host replay peer missing')
run([sys.executable, 'scripts/build-turnip-darwin.py', '--target', 'ios'],
    'turnip-ios17', 1800)
run([sys.executable, 'scripts/build-adreno-metal-plugin.py'],
    'plugin-ios17', 2400)
require(sha(watchdog_path) == watchdog_patched, 'Watchdog source changed during iOS production')
verify_reused_host_inputs(root, host_reuse, allow_rebuilt_peer=True)
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
# Explicit artifact paths only. Apple inputs and preserved derived archives/cache
# stay in root build/cache directories and are never recursively copied here.
allowed_root = {'Cargo.lock', 'mesa-requirements.txt'}
allowed_component_files = {
    'trust.json', 'adrenoprobed', 'libadreno_metal_bridge.a',
    'adrenoprobed-entitlements.plist', 'org.blu-sharky.adrenoprobed.plist',
    'com.apple.iomfb_fdr_loader.plist', 'com.apple.bluetoothd.plist',
    'NativeAdrenoMetal.bundle/NativeAdrenoMetal',
    'NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib',
    'NativeAdrenoMetal.bundle/Info.plist',
    'NativeAdrenoMetal.bundle/_CodeSignature/CodeResources',
}
for p in output.rglob('*'):
    require(not p.is_symlink(), 'Artifact symlink refused')
    if p.is_file():
        relative = p.relative_to(output)
        if relative.parts[0] == 'components':
            require(Path(*relative.parts[1:]).as_posix() in allowed_component_files,
                    'Unexpected component resource requires review: ' + str(relative))
        elif relative.parts[0] == 'logs':
            require(len(relative.parts) == 2 and p.suffix in {'.log', '.json'},
                    'Unexpected diagnostic payload')
        else:
            require(relative.as_posix() in allowed_root, 'Unexpected root artifact')
        require(p.suffix.lower() not in {'.dmg', '.ipsw', '.metallib', '.raw', '.aea',
                                        '.dbr', '.cdr', '.img', '.archive', '.cache', '.zip'},
                'Original-input or unaudited derived payload refused')
        with p.open('rb') as stream:
            require(stream.read(4) != b'MTLB', 'Metal library payload refused')
require(sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) <= 2 * 1024**3,
        'Candidate artifact exceeds2GiB bound')
output_hashes = {str(p.relative_to(output)): dict(bytes=p.stat().st_size, sha256=sha(p))
                 for p in sorted(output.rglob('*')) if p.is_file()}
manifest = dict(
    status='CANDIDATE_COMPONENTS_BUILT_SIGNED_NOT_INSTALL_READY',
    schema='unixnu.gpu-components.v6-host-reuse-q-layout-monotonic-watchdog',
    qualification='FULL_HOST_CONTROLS_PASS_REVIEWED_Q_LAYOUT_MONOTONIC_WATCHDOG_PHYSICAL_GPU_PENDING',
    host_software_qualification=dict(completed=True, status='PASS', details=host_qualification),
    original_input_qualification=dict(
        required_library='iPadOS17.7.11-21H461 QuartzCore/default.metallib',
        sha256='606f913adf520420f9b4bb666efb782a68c830f082f1e559e17b20d0d13adbc9',
        required_suite='scripts/check-quartzcore-turnip-cache-host.py',
        additional_suite='scripts/check-priming-cache-host.py',
        completed=True, provenance=original_input, original_Apple_input_uploaded=False,
        Q_checker_original_sha256=reviewed_Q_adapter_record()['original_sha256'],
        Q_checker_actual_sha256=reviewed_Q_adapter_record()['patched_sha256'],
        Q_checker_original_byte_identity=False),
    exact_sources=dict(UniXNU=MAIN, device=DEVICE, components=gitlinks, Mesa=MESA,
                       translator=TRANSLATOR, overlays=overlays),
    source_split=dict(mode='complete host controls with authenticated C6 host build reuse and reviewed Q cache layout adapter',
        build_prefix_substitution=True,
        build_prefix_substitution_scope='cached host compilation/provisioning only; no control-suite command omitted',
        test_suite_prefix_substitution=False,
        whole_host_suite=dict(sha256=host_qualification['host_suite_patched_sha256'], executed=True,
                             all_control_commands_retained=True),
        q_cache_layout_adapter=reviewed_Q_adapter_record(),
        host_build_reuse=host_reuse,
        replay_diagnostics=dict(original_sha256=replay_before, patched_sha256=sha(replay_source),
            original_runtime_call_environment_timeout_and_RD_criteria_unchanged=True),
        hostsim_VA_configuration_only=True,
        host_link_source_repairs=[dict(path=relative, original_sha256=before_sha, patched_sha256=after_sha)
                                  for relative, asset, before_sha, after_sha in host_link_repairs],
        host_fixture_compatibility=dict(original_sha256=fixture_before, patched_sha256=sha(fixture),
            role_constants_sha256=sha(host_private), default_role='explicit host unmanaged; not real OS task role'),
        plugin_Turnip_bridge_sources_modified=True,
        watchdog_monotonic_patch=watchdog_patch_record),
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
    no_device_seed_or_private_key=True,
    original_OS_inputs_fetched_temporarily_not_uploaded=True,
    derived_cache_archive_payloads_uploaded=False,
    installation_ready=False,
    hardware_GPU_execution_verified=False,
    created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(output / 'input-output-manifest.json').write_text(json.dumps(manifest, indent=2))
(output / 'REQUIRED_PENDING_PHYSICAL_GPU_QUALIFICATION.txt').write_text(
    'CANDIDATE ONLY. Full host controls passed with authenticated C6 host-build reuse, reviewed Q cache layout and a monotonic watchdog timer patch; physical GPU and installation qualification remain required.\n')
print(json.dumps(dict(status=manifest['status'], qualification=manifest['qualification'],
                     binaries=identities), indent=2))
