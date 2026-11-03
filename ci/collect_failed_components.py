#!/usr/bin/env python3
"""Preserve allowlisted self-built public outputs after a failed source-only CI.
No subprocess, signing, SDK reads, dependency-tree traversal or device access.
A recovered file is evidence only: this utility never assigns a qualification PASS.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

LIMIT = 2 * 1024**3
RESERVE = 1024**2
LOG_LIMIT = 32 * 1024**2
JSON_LIMIT = 4 * 1024**2
STATUS = 'ONLY_RECOVERY_NOT_INSTALL_READY'
PINS = {
    'UniXNU': '6790e7ce6e77f67a9174fba1255e64eacf1c41ad',
    'device': '28b30285768e04008ac525c04182e245bfac441e',
    'Mesa': '85fda3b36405bcaea8bffc64aa4f2651dc90770d',
    'translator': '624bab3918de5b978e1101517abca2b4fa426565',
    'components': {
        'drivers/Adreno740': 'a9a2cbb43b89d672e2921e19721a6438b738b17f',
        'drivers/AdrenoMetal': 'a0f0287be80a5d8aef5c6b97a6cab62129e152bd',
        'kits/AdrenoPM4': '282606b528b2595bc4274ea7490b62b323f35a5f',
        'kits/ArmSmmu4K': '83969cd874503e65997ff7639f7dcf3d0a92cd17',
    },
}
# Exact author producer outputs, never a recursive build/.cache copy.
PUBLIC_FILES = (
    'build/mesa-tu/src/freedreno/vulkan/libvulkan_freedreno.dylib',
    'build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib',
    'build/mesa-tu/builtin-build-profile.json',
    'build/mesa-tu-ios/builtin-build-profile.json',
    'build/turnip-darwin-host/libhostiokit.dylib',
    'build/turnip-darwin-host/plugin_smoke',
    'build/turnip-darwin-host/vulkan_smoke',
    'build/adreno-metal-bridge/host/libadreno_metal_bridge.a',
    'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a',
    'build/adreno-metal-bridge/Cargo.lock',
    'build/mesa-ir3/src/freedreno/ir3/ir3_disasm',
    'build/mesa-ir3/src/freedreno/ir3/ir3_delay_test',
    'build/mesa-ir3/host-report.json',
    'build/ci-sdk-probe/probe',
    'build/adreno-metal-plugin/NativeAdrenoMetal.bundle/NativeAdrenoMetal',
    'build/adreno-metal-plugin/NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib',
    'build/adreno-metal-plugin/NativeAdrenoMetal.bundle/Info.plist',
    'build/adreno-metal-plugin/NativeAdrenoMetal.bundle/_CodeSignature/CodeResources',
    'build/adreno-metal-plugin/adrenoprobed',
    'build/adreno-metal-plugin/trust.json',
    'build/adreno-metal-plugin/adrenoprobed-entitlements.plist',
    'build/adreno-metal-plugin/org.blu-sharky.adrenoprobed.plist',
    'build/adreno-metal-plugin/com.apple.iomfb_fdr_loader.plist',
    'build/adreno-metal-plugin/com.apple.bluetoothd.plist',
)
PRODUCER_LOGS = (
    'build/turnip-darwin-host/smoke.log',
    'build/turnip-darwin-host/plugin_smoke.log',
    'build/turnip-darwin-host/plugin_watchdog.log',
    'build/turnip-darwin-host/deferred-normal.log',
    'build/turnip-darwin-host/deferred-busy.log',
    'build/turnip-darwin-host/deferred-fence-error.log',
    'build/turnip-darwin-host/deferred-free-error.log',
    'build/turnip-darwin-host/deferred-lease-error.log',
    'build/turnip-darwin-host/deferred-view-error.log',
    'build/turnip-darwin-host/deferred-map-cleanup-error.log',
    'build/turnip-darwin-host/deferred-pressure.log',
    'build/turnip-darwin-host/pipeline-cache-produce.log',
    'build/turnip-darwin-host/pipeline-cache-consume.log',
    'build/turnip-darwin-host/pipeline-cache-uuid-miss.log',
    'build/turnip-darwin-host/pipeline-cache-shader-miss.log',
    'build/turnip-darwin-host/pipeline-cache-report.json',
    'build/ui-shader-coverage/turnip-graphics/last-produce.log',
    'build/ui-shader-coverage/turnip-graphics/last-consume.log',
    'build/ui-shader-coverage/turnip-graphics/last-uuid-miss.log',
    'build/ui-shader-coverage/turnip-graphics/last-empty-driver.log',
    'build/ci-preserved-original-qualification/quartzcore/produce.log',
    'build/ci-preserved-original-qualification/quartzcore/consume.log',
    'build/ci-preserved-original-qualification/quartzcore/uuid-miss.log',
    'build/ci-preserved-original-qualification/quartzcore/empty-driver.log',
    'build/ci-preserved-original-qualification/priming/cold-miss.log',
    'build/ci-preserved-original-qualification/priming/produce.log',
    'build/ci-preserved-original-qualification/priming/consume.log',
    'build/ci-preserved-original-qualification/priming/uuid-miss.log',
    'build/ci-preserved-original-qualification/priming/truncated-miss.log',
    'build/ci-preserved-original-qualification/priming/checksum-miss.log',

    '.cache/mesa-ir3-configure.log', '.cache/mesa-ir3-build.log',
    '.cache/mesa-ir3-probe-configure.log',
    '.cache/mesa-ir3_disasm-test.log', '.cache/mesa-ir3_delay_test-test.log',
    '.cache/mesa-tu-host-configure.log', '.cache/mesa-tu-host-build.log',
    '.cache/mesa-tu-ios-configure.log', '.cache/mesa-tu-ios-build.log',
    'build/adreno-metal-bridge/build-ios.log',
    'build/adreno-metal-bridge/build-host.log',
)

class Refused(RuntimeError):
    pass

def need(ok, why):
    if not ok:
        raise Refused(why)

def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())

def ordinary_file(anchor, relative):
    """Check each selected path component without following links; absent is normal."""
    need(isinstance(relative, str) and '\\' not in relative and ':' not in relative,
         'Unsafe allowlist path')
    pieces = relative.split('/')
    need(all(p and p not in ('.', '..') for p in pieces), 'Unsafe allowlist component')
    current = anchor
    need(not linked(anchor) and anchor.is_dir(), 'Source anchor is not an ordinary directory')
    for index, piece in enumerate(pieces):
        current = current / piece
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        need(not linked(current), 'Selected symlink/junction refused: ' + relative)
        if index + 1 < len(pieces):
            need(stat.S_ISDIR(info.st_mode), 'Selected parent is not a directory: ' + relative)
        else:
            need(stat.S_ISREG(info.st_mode), 'Selected output is not regular: ' + relative)
    need(anchor in current.resolve(strict=True).parents, 'Selected path escaped anchor')
    return current

def source_record(path):
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

def copy_checked(source, target, snapshot):
    need(not linked(source) and source_record(source) == snapshot, 'Source changed before copy')
    target.parent.mkdir(parents=True, exist_ok=True)
    need(not target.exists(), 'Refuse existing target')
    h, count = hashlib.sha256(), 0
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        opened = os.fstat(incoming.fileno())
        need((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) == snapshot,
             'Source identity changed at open')
        for chunk in iter(lambda: incoming.read(1024**2), b''):
            count += len(chunk)
            need(count <= snapshot[2], 'Source grew during copy')
            outgoing.write(chunk)
            h.update(chunk)
    need(count == snapshot[2] and not linked(source) and source_record(source) == snapshot,
         'Source changed during copy')
    mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
    target.chmod(mode)
    return dict(bytes=count, sha256=h.hexdigest(), mode=oct(mode),
                qualification='UNKNOWN_RECOVERY_ONLY', signature_qualification='UNKNOWN_NOT_CHECKED')

def collect(root, output):
    requested_root = root.absolute()
    need(not linked(requested_root), 'Root symlink/junction refused')
    root = requested_root.resolve(strict=True)
    need(root.is_dir() and requested_root == root, 'Root must be a canonical ordinary checkout')
    workspace = root.parent
    requested_output = output.absolute()
    need(not requested_output.exists() and not linked(requested_output), 'Output must be new')
    need(requested_output.parent.resolve(strict=True) == workspace and requested_output.name not in ('.', '..'),
         'Output must be a fresh sibling of the source checkout')
    output = workspace / requested_output.name
    need(output != root, 'Do not overwrite source checkout')
    output.mkdir(exist_ok=False)
    marker = output / 'ONLY_RECOVERY_NOT_INSTALL_READY.txt'
    marker.write_text(STATUS + '\nAll files are unqualified recovery evidence. Do not install or execute from this artifact.\n', encoding='utf-8')
    manifest = dict(schema='unixnu.failed-public-components.recovery.v1', status=STATUS,
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        github_context={key: os.environ.get(key) for key in (
            'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'RUNNER_OS', 'RUNNER_ARCH')},
        github_context_is_not_independent_provenance=True, expected_source_pins=PINS,
        actual_source_pin_qualification='NOT_REPEATED_BY_COLLECTOR; bind upstream CI source checks separately',
        signatures='UNKNOWN_NOT_CHECKED', full_host_qualification=False,
        physical_GPU_execution_verified=False, installation_ready=False, reusable_without_further_review=False,
        copying_completed=False, files={}, missing=[], errors=[],
        exclusions='No SDK/OS inputs, dependency trees, RD memory dumps, caches, private keys or device data',
        command_execution=False, resigning=False)
    try:
        selected = []
        def add(anchor, relative, destination, limit=LIMIT):
            f = ordinary_file(anchor, relative)
            if f is None:
                manifest['missing'].append(relative)
                return
            snap = source_record(f)
            need(0 <= snap[2] <= limit, 'Selected file exceeds size bound: ' + relative)
            selected.append((f, destination, snap))
        for relative in PUBLIC_FILES:
            add(root, relative, 'public-build/' + relative,
                JSON_LIMIT if relative.endswith('.json') else LIMIT)
        for relative in PRODUCER_LOGS:
            add(root, relative, 'producer-logs/' + relative.replace('/', '__'), LOG_LIMIT)
        # Own CI phase logs only: one flat directory, conservative names and bounds.
        log_root = workspace / 'component-artifact/logs'
        log_parent = workspace / 'component-artifact'
        if log_parent.exists() or linked(log_parent):
            need(not linked(log_parent) and log_parent.is_dir(), 'Artifact log parent link refused')
            if log_root.exists() or linked(log_root):
                need(not linked(log_root) and log_root.is_dir(), 'Artifact log directory link refused')
                entries = list(log_root.iterdir())
                need(len(entries) <= 128, 'Too many phase log entries')
                for item in sorted(entries):
                    need(re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:log|json)', item.name) is not None,
                         'Unexpected phase log name')
                    add(workspace, 'component-artifact/logs/' + item.name, 'phase-logs/' + item.name,
                        JSON_LIMIT if item.suffix == '.json' else LOG_LIMIT)
        # If a final own manifest was written before a later failure, retain its
        # recorded SDK/compiler/source identities. Never read SDK files directly.
        add(workspace, 'component-artifact/input-output-manifest.json',
            'recorded-ci-input-output-manifest.json', JSON_LIMIT)
        destinations = [target.casefold() for _, target, _ in selected]
        need(len(destinations) == len(set(destinations)), 'Duplicate recovery destination')
        payload_bytes = sum(snap[2] for _, _, snap in selected)
        need(payload_bytes <= LIMIT - RESERVE, 'Recovery selection exceeds2GiB bound')
        need(shutil.disk_usage(workspace).free >= payload_bytes + RESERVE, 'Insufficient disk to preserve outputs')
        for f, relative, snap in selected:
            target = output.joinpath(*relative.split('/'))
            need(output in target.resolve(strict=False).parents, 'Recovery destination escaped output')
            manifest['files'][relative] = copy_checked(f, target, snap)
        manifest['payload_bytes'] = payload_bytes
        manifest['copying_completed'] = True
    except Exception as error:
        manifest['errors'].append(type(error).__name__ + ': ' + str(error))
    report = output / 'recovery-manifest.json'
    encoded = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    need(len(encoded) < RESERVE, 'Recovery metadata exceeds reserved bound')
    with report.open('xb') as stream:
        stream.write(encoded)
    # Every selected file was size-checked before copying; metadata has a1MiB reserve.
    need(sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) <= LIMIT,
         'Recovery artifact exceeded2GiB')
    print(json.dumps(dict(status=STATUS, copying_completed=manifest['copying_completed'],
                         files=len(manifest['files']), manifest=str(report), errors=manifest['errors'])))
    return 0 if manifest['copying_completed'] else 2

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        return collect(args.root, args.output)
    except Exception as error:
        print(json.dumps(dict(status=STATUS, copying_completed=False,
                              error=type(error).__name__ + ': ' + str(error))), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
