"""Copy only named generic cloud build evidence after a failed CI gate.

This produces a quarantine, never a normal handoff or a boot authorization.
No source tree recursion, prior artifacts, environment dump, or device data.
"""
import hashlib
import json
import os
import re
import shutil
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def collect(top, ci):
    top, ci = Path(top).resolve(), Path(ci).resolve()
    lock_path = ci / 'os27-update-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf8'))
    if lock['profile'] != 'ipados-27.0.1-24A446':
        raise RuntimeError('Unexpected quarantine build profile')
    variant = lock['touch_frame_kind_fix']['variant']
    if variant not in ('testing', 'aggressive'):
        raise RuntimeError('Unexpected quarantine variant')
    if os.environ.get('UNIXNU_UNIQUE_CHIP_ID') != '13579bdf':
        raise RuntimeError('Quarantine is limited to synthetic cloud identity')
    work = top / 'UniXNU/out/sheng' / lock['profile'] / 'sheng_ipados27'
    source_build = work / 'tree/build/sheng-source-drivers'
    # Every entry is an explicit single file. Missing entries remain missing.
    allowed = {
        'kernel/kernel.macho': work / 'kernel/kernel.macho',
        'provisional/DO-NOT-BOOT-payload.img': work / 'payload/payload.img',
        'provisional/DO-NOT-BOOT-boot.img': work / 'boot/boot.img',
        'metadata/author-package.manifest.json': work / 'package.manifest.json',
        'metadata/touch-source-binding.json': work / 'runtime/touch-source-binding.json',
        'metadata/source-driver-report.json': source_build / 'report.json',
        'metadata/BootLog.command.json': work / 'tree/build/sheng-source-storage/BootLog.command.json',
        'metadata/os27-update-lock.json': lock_path,
        'metadata/TOUCH-PATCH-NOTICE.txt': ci / 'TOUCH-PATCH-NOTICE.txt',
    }
    for stem in ('NativeHidInput', 'TouchProbe', 'NvtProtocol', 'NvtTouchCore', 'NvtPartialObservation', 'NvtCoverage'):
        for suffix in ('command.json', 'inputs.json', 'log'):
            allowed['metadata/' + stem + '.' + suffix] = source_build / (stem + '.' + suffix)
    allowed['metadata/touch-link-evidence.json'] = work / 'tree/build/native-legacy-display/touch-link-evidence.json'
    allowed['logs/kernel.log'] = work / 'logs/kernel.log'
    for stem in ('NvtPartialObservation', 'NvtCoverage'):
        allowed['objects/' + stem + '.o'] = source_build / (stem + '.o')
    # Fixed license names, not a directory walk.
    for name in ('Apache-2.0.txt', 'UniXNU-sheng-BSD-2-Clause-Patent.txt',
                 'ShengHidInput-BSD-2-Clause-Patent.txt', 'ShengNovatekTouch-NOTICE.txt'):
        allowed['LICENSES/' + name] = ci / 'licenses' / name
    for name in ('LICENSE.QualcommAtheros_ath10k', 'WCN7850-Notice.txt'):
        allowed['LICENSES/' + name] = top / 'wifi-firmware-licenses/LICENSES' / name
    out = top / 'os27-touch-quarantine-UNAPPROVED_DO_NOT_BOOT'
    if out.exists():
        raise RuntimeError('Quarantine output already exists; refusing to mix runs')
    out.mkdir()
    copied, missing, rejected = {}, [], []
    for name, source in allowed.items():
        if not source.exists():
            missing.append(name)
            continue
        resolved = source.resolve()
        # Reject a linked file or linked ancestor and any escape from this job.
        chain = source
        linked = False
        while chain != top and chain != chain.parent:
            linked = linked or chain.is_symlink()
            chain = chain.parent
        if not source.is_file() or linked or not resolved.is_relative_to(top):
            rejected.append(name)
            continue
        dest = out / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        copied[name] = {'bytes': dest.stat().st_size, 'sha256': digest(dest)}
    def public_field(key, pattern):
        value = os.environ.get(key, '')
        if value and not re.fullmatch(pattern, value):
            raise RuntimeError('Invalid public cloud receipt field: ' + key)
        return value
    receipt = {
        'schema': 'unixnu.touch-two-variants.failed-build-quarantine.v1',
        'status': 'FAILED_BUILD_UNAPPROVED_DO_NOT_BOOT_OR_FLASH',
        'variant': variant, 'build_profile': lock['profile'],
        'repository': public_field('GITHUB_REPOSITORY', r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'),
        'run_id': public_field('GITHUB_RUN_ID', r'[0-9]+'),
        'run_attempt': public_field('GITHUB_RUN_ATTEMPT', r'[0-9]+'),
        'commit_sha': public_field('GITHUB_SHA', r'[a-fA-F0-9]{40}'),
        'synthetic_platform_seed': '13579bdf', 'personalization_required': True,
        'hardware_verified': False, 'source_gate_pass': False,
        'normal_handoff_authorized': False, 'lock_sha256': digest(lock_path),
        'files': copied, 'missing': missing, 'rejected': rejected,
        'note': 'The original failing CI step remains failed. These files are evidence only; no approval is implied.'
    }
    (out / 'UNAPPROVED-DO-NOT-BOOT.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
    (out / 'DO-NOT-BOOT.txt').write_text(
        'FAILED BUILD QUARANTINE. UNAPPROVED. DO NOT BOOT OR FLASH.\n'
        'Raw/FAT/boot may be incomplete or invalid. Fresh independent review and local personalization are mandatory.\n',
        encoding='utf8')
    print(json.dumps({'status': receipt['status'], 'variant': variant,
                      'copied_files': len(copied), 'missing_files': len(missing), 'rejected_files': len(rejected)}))
    return receipt


if __name__ == '__main__':
    collect(Path(os.environ.get('GITHUB_WORKSPACE', Path.cwd())), Path(__file__).resolve().parent)
