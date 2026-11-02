"""Validate real ARM64/iOS17 Mach-O signatures from bytes, not command success."""
import hashlib, math, re, struct, subprocess
from pathlib import Path

def require(ok, why):
    if not ok:
        raise RuntimeError(why)

def check(path, expected_filetype=None):
    path = Path(path)
    raw = path.read_bytes()
    require(len(raw) >= 32, 'Short Mach-O: ' + str(path))
    magic, cpu, subtype, filetype, ncmd, cmdbytes = struct.unpack_from('<6I', raw)
    require((magic, cpu, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 0),
            'Expected ordinary ARM64, not arm64e or a script')
    if expected_filetype is not None:
        require(filetype == expected_filetype, 'Wrong Mach-O filetype')
    require(32 + cmdbytes <= len(raw) and ncmd < 4096, 'Invalid load-command extent')
    at, builds, signatures = 32, [], []
    for _ in range(ncmd):
        require(at + 8 <= 32 + cmdbytes, 'Short load command')
        kind, size = struct.unpack_from('<II', raw, at)
        require(size >= 8 and size % 8 == 0 and at + size <= 32 + cmdbytes,
                'Unbounded load command')
        if kind == 0x32:
            require(size >= 24, 'Short LC_BUILD_VERSION')
            builds.append(struct.unpack_from('<III', raw, at + 8))
        elif kind == 0x1d:
            require(size == 16, 'Short LC_CODE_SIGNATURE')
            signatures.append(struct.unpack_from('<II', raw, at + 8))
        at += size
    require(at == 32 + cmdbytes, 'Load command size mismatch')
    require(len(builds) == 1 and builds[0][0:2] == (2, 0x110000),
            'Expected LC_BUILD_VERSION iOS, minimum17.0')
    require(len(signatures) == 1, 'Missing/duplicate LC_CODE_SIGNATURE')
    off, size = signatures[0]
    require(0 < off < len(raw) and 12 <= size <= len(raw) - off,
            'Signature not in real binary')
    sig = raw[off:off + size]
    magic, total, count = struct.unpack_from('>III', sig)
    require(magic == 0xfade0cc0 and 12 <= total <= len(sig) and
            count <= 64 and 12 + 8 * count <= total, 'Invalid embedded SuperBlob')
    directories = []
    for i in range(count):
        slot, rel = struct.unpack_from('>II', sig, 12 + i * 8)
        require(rel + 8 <= total, 'Invalid signature slot')
        kind, length = struct.unpack_from('>II', sig, rel)
        require(length >= 8 and rel + length <= total, 'Signature slot overrun')
        if slot == 0:
            require(kind == 0xfade0c02 and length >= 44, 'Invalid CodeDirectory')
            directories.append(sig[rel:rel + length])
    require(len(directories) == 1, 'Missing primary CodeDirectory')
    cd = directories[0]
    version, flags, hash_offset, ident_offset, special, slots, limit = struct.unpack_from('>7I', cd, 8)
    hsize, htype, platform, page = struct.unpack_from('>4B', cd, 36)
    require(0x20100 <= version <= 0x20600 and flags & 2, 'Expected known ad-hoc CodeDirectory')
    require(page == 12 and htype == 2 and hsize == 32, 'Expected4KiB/SHA256 CodeDirectory')
    require(limit == off and limit >= 32 + cmdbytes and slots == math.ceil(limit / 4096), 'Code-slot coverage mismatch')
    require(hash_offset >= 44 + special * hsize and hash_offset + slots * hsize <= len(cd),
            'Code hashes outside CodeDirectory')
    require(0 < ident_offset < len(cd) and bytes([0]) in cd[ident_offset:], 'Missing signing identifier')
    for i in range(slots):
        digest = hashlib.sha256(raw[i * 4096:min(limit, (i + 1) * 4096)]).digest()
        require(cd[hash_offset + i * 32:hash_offset + (i + 1) * 32] == digest,
                'Real4KiB code-page hash mismatch')
    computed = hashlib.sha256(cd).digest()[:20].hex()
    r = subprocess.run(['codesign', '--verify', '--strict', str(path)],
                       capture_output=True, text=True, timeout=30)
    require(r.returncode == 0, 'Strict codesign verify failed: ' + r.stderr)
    r = subprocess.run(['codesign', '--display', '--verbose=4', str(path)],
                       capture_output=True, text=True, timeout=30)
    require(r.returncode == 0, 'codesign detail failed')
    match = re.search(r'^CDHash=([0-9a-f]{40})$', r.stdout + r.stderr, re.M)
    require(match is not None and match[1] == computed, 'Actual CDHash differs')
    require(re.search(r'^Page size=4096$', r.stdout + r.stderr, re.M) is not None,
            'Actual codesign does not report4KiB')
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                cdhash=computed, CodeDirectory_sha256=hashlib.sha256(cd).hexdigest(),
                signature_page_bytes=4096, code_pages=slots, filetype=filetype,
                platform=2, minimum_os='17.0', sdk_packed=builds[0][2],
                code_page_hashes_verified=True, codesign_strict_verified=True)
