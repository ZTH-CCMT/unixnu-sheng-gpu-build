"""Build a provisional OS27 boot update on macOS using the original installation seed."""
import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import zlib
from pathlib import Path

LOCK = json.loads(Path(__file__).with_name('os27-update-lock.json').read_text())
TOP = Path(os.environ.get('GITHUB_WORKSPACE', Path.cwd())).resolve()
SYNTHETIC = '13579bdf'
DATA = LOCK['data']


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def checked_replace(path, checks, replacements):
    before = path.read_bytes()
    require(sha(before) == checks['before'], f'Unexpected source hash: {path}')
    after = before
    for old, new in replacements:
        require(after.count(old) == 1, f'Unexpected replacement count: {path}')
        after = after.replace(old, new, 1)
    require(sha(after) == checks['after'], f'Unexpected adapted source hash: {path}')
    if after != before:
        path.write_bytes(after)


def prepare_files(top):
    device = top / 'device'
    core = top / 'UniXNU'
    edits = LOCK['inputs']
    checked_replace(device / 'board.toml', edits['board'], [
        (b'"first_lba" = 3094592\n"last_lba" = 64007162',
         b'"partition_name" = "unixnu"\n"first_lba" = 173859584\n"last_lba" = 257745663')])
    checked_replace(device / 'drivers/ShengUfs/RootLayout.h', edits['ufs'], [
        (b'Find the partition named "userdata"', b'Find the dedicated partition named "unixnu"'),
        (b'wanted[] = "userdata";', b'wanted[] = "unixnu";'),
        (b'"duplicate userdata partition"', b'"duplicate unixnu partition"'),
        (b'"no userdata partition"', b'"no unixnu partition"'),
        (b'"userdata first block read"', b'"unixnu first block read"')])
    checked_replace(core / 'patches/mesa/turnip-frame-diagnostics.patch', edits['mesa'], [
        (b'vulkan/tu_frame_diagnostic.h\n--- /dev/null',
         b'vulkan/tu_frame_diagnostic.h\nnew file mode 100644\n--- /dev/null')])
    checked_replace(core / 'scripts/unixnu/bootimg.py', edits['bootimg'], [])
    checked_replace(core / 'scripts/build-boot-runtime.py', edits['runtime'], [])
    board = tomllib.loads((device / 'board.toml').read_text())
    runtime = board['payload']['runtime']
    require(board['userdata'] == LOCK['live_target'], 'Incorrect dedicated storage geometry')
    require(board['board']['os_profile'] == LOCK['profile'], 'Unexpected OS profile')
    require(runtime['data_gib'] == 215 and runtime['wifi_launchd_cache'], 'Unexpected runtime profile')
    require(runtime['launchd_job_environment'] == LOCK['job_environment'], 'Icon service settings missing')
    require(int(str(board['payload']['adt']['owned_memory_size']), 0) == LOCK['memory_bytes'],
            'Unexpected handoff memory window')


def check_seed(seed):
    require(digest(seed) == DATA['seed_sha256'], 'Original Data seed hash differs')
    with seed.open('rb') as file:
        magic, version, page, size, extents = struct.unpack('<8sIIQQ', file.read(32))
    require((magic, version, page, size) == (b'DBRDISK1', 1, 4096, DATA['logical_bytes']) and extents > 0,
            'Invalid original Data seed')


def check_policy_sources():
    base = TOP / 'device/scripts/policies' / LOCK['profile']
    entries = []
    bodies = []
    position = 32 + 16 * 2
    for name in ('OS', 'SystemOS'):
        body = (base / name / 'manifest.header.bin').read_bytes()
        git_blob = hashlib.sha1(f'blob {len(body)}\0'.encode() + body).hexdigest()
        require(git_blob == LOCK['root_policy_git_blobs'][name], f'{name} signed header differs')
        entries.append(struct.pack('<QQ', position, len(body)))
        bodies.append(body)
        position += len(body)
    packed = struct.pack('<8sQQQ', b'VROOTB01', 1, 2, position) + b''.join(entries + bodies)
    require(sha(packed) == LOCK['root_policies_sha256'], 'Signed installed system policy differs')


def addon_launchd(addon):
    data = addon.read_bytes()
    require(data[:8] == b'NGPUADD2', 'Unexpected runtime addon format')
    count, _, size = struct.unpack_from('<IIQ', data, 8)
    require(size == len(data) and count <= 4096, 'Invalid addon index')
    targets = {'xpc/launchd.plist', 'xpc/launchd.plist.sig'}
    files = {}
    offset = 24
    for _ in range(count):
        name_size, _, raw_size, compressed = struct.unpack_from('<IIQQ', data, offset)
        offset += 24
        require(1 <= name_size <= 160 and data[offset + name_size - 1] == 0, 'Invalid addon entry name')
        name = data[offset:offset + name_size - 1].decode()
        offset += (name_size + 7) & ~7
        require(offset + compressed <= size, 'Addon entry exceeds image')
        if name in targets:
            require(name not in files and raw_size < 8 * 1024**2, 'Duplicate or oversized launchd asset')
            content = zlib.decompress(data[offset:offset + compressed])
            require(len(content) == raw_size, 'Launchd asset size mismatch')
            files[name] = content
        offset += (compressed + 7) & ~7
    require(offset == size and files.keys() == targets, 'Addon missing signed launchd cache')
    return files


def trust_contains(trust, cdhash):
    blob = trust.read_bytes()
    count, = struct.unpack_from('<I', blob)
    offsets = list(struct.unpack_from(f'<{count}I', blob, 4)) + [len(blob)]
    for start, end in zip(offsets, offsets[1:]):
        version, _, entries = struct.unpack_from('<I16sI', blob, start)
        stride = {0: 20, 1: 22, 2: 24}.get(version)
        require(stride is not None and start + 24 + entries * stride == end, 'Unexpected trust module')
        if any(blob[at:at + 20] == cdhash for at in range(start + 24, end, stride)):
            return True
    return False


def verify_cache(runtime, addon, trust):
    report_path = runtime / 'wifi-launchd-cache.json'
    report = json.loads(report_path.read_text())
    require(report['job_environment'] == LOCK['job_environment'], 'Runtime did not apply the icon job settings')
    files = addon_launchd(addon)
    cache = files['xpc/launchd.plist']
    signature = files['xpc/launchd.plist.sig']
    require(sha(cache) == report['output_sha256'], 'Packed launchd cache differs from build receipt')
    require(sha(signature) == report['detached_signature_sha256'], 'Packed launchd signature differs')
    cdhash = bytes.fromhex(report['cdhash'])
    require(len(cdhash) == 20 and trust_contains(trust, cdhash), 'Launchd cache trust hash missing')
    jobs = plistlib.loads(cache)['LaunchDaemons']
    for label, expected in LOCK['job_environment'].items():
        matches = [job for job in jobs.values() if job.get('Label') == label]
        require(len(matches) == 1, f'Expected one packed job for {label}')
        env = matches[0]['EnvironmentVariables']
        require(all(env.get(k) == v for k, v in expected.items()), 'Packed icon service configuration differs')
    return report_path


def build(seed):
    for name, commit in LOCK['pins'].items():
        repo = TOP / name
        require(git(repo, 'rev-parse', 'HEAD') == commit, f'Wrong source commit: {name}')
        require(not git(repo, 'status', '--porcelain', '--untracked-files=no'), f'Dirty source: {name}')
        status = subprocess.check_output(['git', '-C', str(repo), 'submodule', 'status', '--recursive'], text=True)
        require(all(line.startswith(' ') for line in status.splitlines()), f'Divergent recursive dependencies: {name}')
    for name, commit in LOCK['components'].items():
        require(git(TOP / name, 'rev-parse', 'HEAD') == commit, f'Wrong driver revision: {name}')

    check_seed(seed)
    check_policy_sources()
    prepare_files(TOP)
    require(shutil.disk_usage(TOP).free >= 9_756_791_929, 'Runner disk below proven lower bound')
    require(os.environ.get('UNIXNU_UNIQUE_CHIP_ID') == SYNTHETIC, 'Cloud job must use synthetic identity')
    subprocess.run(['bash', str(TOP / 'device/scripts/package.sh'), '--os', '27',
                    '--uefi', str(TOP / 'uefi-sheng'), '--data-ramdisk', str(seed)],
                   cwd=TOP / 'device', check=True)

    sys.path.insert(0, str(TOP / 'UniXNU/scripts'))
    from unixnu.cli import parser
    from unixnu.config import Context

    ctx = Context(parser().parse_args(['build', '-D', str(TOP / 'device'), '--os', '27',
                                       '--uefi', str(TOP / 'uefi-sheng')]))
    runtime_dir = ctx.work / 'runtime'
    inputs = json.loads((runtime_dir / 'inputs.json').read_text())
    require(inputs['data_volume_uuid'].upper() == DATA['uuid'], 'Build used a different Data UUID')
    config = ctx.config_path.read_text()
    require(re.search(r'^CONFIG_XNU_OWNER_DATA_VOLUME_UUID="([^"]+)"', config, re.M)[1].upper() == DATA['uuid'],
            'Compiled Data UUID differs')
    policy = ctx.tree / 'build/sheng-source-storage/root-policies.bin'
    require(digest(policy) == LOCK['root_policies_sha256'], 'Compiled root policy differs')
    runtime_inputs = {}
    for label, name in [('data_ramdisk', 'data.dbr'), ('trust_cache', 'trust-cache.bin'), ('gpu_addon', 'gpu-addon.bin')]:
        item = inputs['inputs'][label]
        path = Path(item['path'])
        require(digest(path) == item['sha256'], f'Runtime input hash differs: {label}')
        runtime_inputs[name] = path
    check_seed(runtime_inputs['data.dbr'])
    cache_report = verify_cache(runtime_dir, runtime_inputs['gpu-addon.bin'], runtime_inputs['trust-cache.bin'])
    allowed = {
        '.config': ctx.config_path,
        'kernel/kernel.macho': ctx.work / 'kernel/kernel.macho',
        'provisional/DO-NOT-BOOT-payload.img': ctx.work / 'payload/payload.img',
        'provisional/DO-NOT-BOOT-boot.img': ctx.work / 'boot/boot.img',
        'root-policies.bin': policy,
        'sheng.dtb': ctx.tree / 'build/sheng/sheng.dtb',
        'SILICIUM_UEFI.fd': TOP / 'uefi-sheng' / ctx.board['firmware']['fd'].format(target=ctx.args.target),
        'author-package.manifest.json': ctx.work / 'package.manifest.json',
        'wifi-launchd-cache.json': cache_report,
        **runtime_inputs,
    }
    stage = TOP / 'os27-update-handoff.partial'
    stage.mkdir()
    files = {}
    for name, path in allowed.items():
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        files[name] = {'bytes': dest.stat().st_size, 'sha256': digest(dest)}
    handoff = {'status': 'PROVISIONAL_DO_NOT_BOOT_OR_FLASH', 'source_pins': LOCK['pins'],
               'synthetic_platform_seed': SYNTHETIC, 'personalization_required': True,
               'data_volume_uuid': DATA['uuid'], 'data_logical_bytes': DATA['logical_bytes'],
               'root_policies_sha256': LOCK['root_policies_sha256'],
               'reused_root_sha256': LOCK['reused_root_sha256'], 'new_installation': False, 'files': files}
    (stage / 'handoff.json').write_text(json.dumps(handoff, indent=2) + '\n')
    stage.rename(TOP / 'os27-update-handoff')
    print('Built and verified provisional boot-only update. Local personalization still required.')


if __name__ == '__main__':
    build(Path(sys.argv[1]).resolve())
