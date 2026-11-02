"""Real macOS full controls with explicit reviewed Q layout and authenticated host-build reuse; imports perform no I/O.

Apple input is fetched directly from the fixed official source into a private
ephemeral directory, never uploaded. Derived cache/archive bytes stay outside
the artifact allowlist. No hardware result is claimed.
"""
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import zlib

URL = "https://updates.cdn-apple.com/2025SpringFCS/fullrestores/122-77166/DCA6CFE8-90E9-4B92-880D-3DE171798E40/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw"
MEMBER = "044-76034-038.dmg"
SIZE = 3303014400
CRC32 = 0x51e7eb35
SHA256 = "b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f"
SHA384 = "2c3abe4f7980440fb940f7831bba90467089a6970298f891f7b41124606eb49017b74b3b6fcbfdea94c43ae563e40917"
LIBRARY_SHA256 = "606f913adf520420f9b4bb666efb782a68c830f082f1e559e17b20d0d13adbc9"
LIBRARY_SIZE = 9670832
LIBRARY_PATH = Path("System/Library/Frameworks/QuartzCore.framework/default.metallib")
ARCHIVE_SIZE = 6835124840
MANIFEST_SIZE = 749588
MANIFEST_SHA256 = "199fb5de41c26d86c080b4e8e402c40309c5f42e7bda18c210451b09bcb49bf7"
ENCODED_SIZE = 1321525120
MAX_RANGE_BYTES = 8 << 20
MAX_TRANSFER_BYTES = ENCODED_SIZE + (64 << 20)
IPSW_PY_SHA256 = "29f22e2ac422bf890b64cd2dc5ed4bd508fb902498ea9aeb8bc6e4efcd7ff273"
CHECKER_SHA256 = {
    "check-turnip-darwin-host.py": "29a805edbf1905112029d7e0adca8668fa6781265a03f571f1760a566fe7732b",
    "check-quartzcore-turnip-cache-host.py": "1f93320b33829370e39cf8b60f7cf8fbca130f1dad0a6ac8fe39c62bbcb4ffed",
    "check-priming-cache-host.py": "825c471b2b095ccd2d0c6203e8199ab59ce9769f836aa75f433e137aa6be7422",
}
TEST_FREE = 5 * 1024**3 + 256 * 1024**2


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def progress(label):
    print(datetime.datetime.now(datetime.timezone.utc).isoformat() + " " + label, flush=True)


def validate_identity(manifest):
    require(manifest.get("ProductVersion") == "17.7.11", "Wrong Apple OS version")
    require(manifest.get("ProductBuildVersion") == "21H461", "Wrong Apple OS build")
    require("iPad7,1" in manifest.get("SupportedProductTypes", []), "Wrong Apple product")
    found = []
    for item in manifest.get("BuildIdentities", []):
        info = item.get("Info", {})
        if (info.get("DeviceClass") == "j120ap" and info.get("RestoreBehavior") == "Erase"
                and int(item.get("ApChipID", "0"), 16) == 0x8011
                and int(item.get("ApBoardID", "0"), 16) == 12):
            found.append(item)
    require(len(found) == 1, "Require exactly one pinned Erase build identity")
    component = found[0].get("Manifest", {}).get("Cryptex1,SystemOS", {})
    require(component.get("Info", {}).get("Path") == MEMBER, "Wrong SystemOS member")
    require(component.get("Digest") == bytes.fromhex(SHA384), "Wrong manifest SHA384")
    return component


def validate_zip_entry(entry):
    require(entry.filename == MEMBER and not entry.is_dir(), "Wrong ZIP entry")
    require(entry.file_size == SIZE, "Wrong original member size")
    require(entry.CRC == CRC32, "Wrong original member CRC")
    require(entry.compress_size == ENCODED_SIZE, "Wrong fixed encoded member size")
    require(entry.compress_type == zipfile.ZIP_DEFLATED, "Wrong fixed ZIP compression")
    require(not entry.flag_bits & 1, "Encrypted ZIP member refused")


def apple_url(url):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    require(parts.scheme == "https" and parts.username is None and parts.password is None
            and (parts.port is None or parts.port == 443)
            and (host == "cdn-apple.com" or host.endswith(".cdn-apple.com")),
            "Only official HTTPS Apple CDN requests are allowed")


class OriginalInputDeadline(RuntimeError):
    """Must not inherit OSError: pinned RangeFile retries OSError/URLError."""


@contextlib.contextmanager
def official_apple_requests():
    # All statuses/lengths are checked before RangeFile can call response.read().
    class AppleRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, newurl):
            apple_url(newurl)
            return super().redirect_request(request, response, code, message, headers, newurl)
    opener = urllib.request.build_opener(AppleRedirect())
    previous = urllib.request.urlopen
    stats = dict(reserved_bytes=0, body_read_bytes=0, range_requests=0,
                 max_range_bytes=MAX_RANGE_BYTES, max_transfer_bytes=MAX_TRANSFER_BYTES)
    last_progress = [time.monotonic()]
    class BoundedResponse:
        def __init__(self, response, expected):
            self.response, self.expected, self.consumed = response, expected, 0
        def __getattr__(self, name):
            return getattr(self.response, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.response.close()
        def read(self, size=-1):
            require(self.expected is not None, "Unexpected HEAD response body")
            want = self.expected - self.consumed + 1
            if size >= 0:
                want = min(want, size)
            data = self.response.read(want)
            self.consumed += len(data)
            stats["body_read_bytes"] += len(data)
            require(self.consumed <= self.expected
                    and stats["body_read_bytes"] <= MAX_TRANSFER_BYTES,
                    "Range response body exceeds its reserved bound")
            now = time.monotonic()
            if now - last_progress[0] >= 30:
                progress("original-input transfer running; body_bytes=" + str(stats["body_read_bytes"]))
                last_progress[0] = now
            return data
    def only_apple(request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        apple_url(url)
        method = request.get_method() if isinstance(request, urllib.request.Request) else "GET"
        if method == "HEAD":
            expected = None
        else:
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", request.get_header("Range") or "")
            require(match is not None, "Explicit bounded Range required")
            first, last = map(int, match.groups())
            expected = last - first + 1
            require(0 <= first <= last < ARCHIVE_SIZE and expected <= MAX_RANGE_BYTES,
                    "Requested Range outside bound")
            stats["reserved_bytes"] += expected
            stats["range_requests"] += 1
            require(stats["reserved_bytes"] <= MAX_TRANSFER_BYTES,
                    "Original-input transfer budget exceeded")
        kwargs["timeout"] = min(30, kwargs.get("timeout", 30))
        response = opener.open(request, *args, **kwargs)
        try:
            apple_url(response.geturl())
            if method == "HEAD":
                require(response.status == 200
                        and int(response.headers.get("Content-Length", "-1")) == ARCHIVE_SIZE,
                        "Wrong fixed archive HEAD size/status")
            else:
                require(response.status == 206, "Server ignored Range206")
                require(response.headers.get("Content-Range")
                        == f"bytes {first}-{last}/{ARCHIVE_SIZE}", "Wrong Content-Range")
                require(int(response.headers.get("Content-Length", "-1")) == expected,
                        "Wrong range Content-Length")
            return BoundedResponse(response, expected)
        except BaseException:
            response.close()
            raise
    urllib.request.urlopen = only_apple
    try:
        yield stats
    finally:
        urllib.request.urlopen = previous


@contextlib.contextmanager
def deadline(seconds):
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise OriginalInputDeadline("Original-input transfer deadline exceeded")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def extract_official_member(root, destination):
    require(sha(root / "scripts/unixnu/ipsw.py") == IPSW_PY_SHA256,
            "Pinned HTTP Range implementation changed")
    sys.path.insert(0, str(root / "scripts"))
    from unixnu.ipsw import RangeFile
    h256, h384, crc, written = hashlib.sha256(), hashlib.sha384(), 0, 0
    transfer = {}
    with official_apple_requests() as transport, deadline(1800):
        with RangeFile(URL) as remote, zipfile.ZipFile(remote) as archive:
            members = archive.infolist()
            require(len(members) < 100000, "Bounded ZIP directory")
            require(sum(x.filename == "BuildManifest.plist" for x in members) == 1,
                    "Ambiguous BuildManifest ZIP entry")
            manifest_entry = archive.getinfo("BuildManifest.plist")
            require(manifest_entry.file_size == MANIFEST_SIZE, "Wrong fixed BuildManifest size")
            manifest_bytes = archive.read(manifest_entry)
            require(hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256,
                    "Wrong fixed original BuildManifest hash")
            manifest = plistlib.loads(manifest_bytes)
            validate_identity(manifest)
            require(sum(x.filename == MEMBER for x in members) == 1,
                    "Ambiguous SystemOS ZIP entry")
            entry = archive.getinfo(MEMBER)
            validate_zip_entry(entry)
            transfer = dict(source_url=URL, product="iPad7,1", version="17.7.11",
                build="21H461", device_class="j120ap", component="Cryptex1,SystemOS",
                member=MEMBER, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                manifest_component_sha384=SHA384, zip_crc32=f"{CRC32:08x}",
                zip_encoded_bytes=entry.compress_size, zip_method=entry.compress_type)
            with archive.open(entry) as source, destination.open("xb") as target:
                for chunk in iter(lambda: source.read(8 << 20), b""):
                    written += len(chunk)
                    require(written <= SIZE, "Original member exceeds its bound")
                    target.write(chunk)
                    h256.update(chunk)
                    h384.update(chunk)
                    crc = zlib.crc32(chunk, crc)
            # ZipFile also independently checks CRC when the member reaches EOF.
    require(written == SIZE and h256.hexdigest() == SHA256 and h384.hexdigest() == SHA384
            and crc & 0xffffffff == CRC32, "Original member digest/size/CRC mismatch")
    with destination.open("rb") as source:
        header = source.read(40)
    require(header[32:36] == b"NXSB", "Expected unencrypted raw APFS SystemOS")
    return dict(**transfer, size=written, sha256=h256.hexdigest(), sha384=h384.hexdigest(),
                raw_apfs=True, AEA_decryption_required=False, original_input_uploaded=False,
                bounded_transport=dict(transport))


def hdiutil_info():
    return plistlib.loads(subprocess.check_output(
        ["hdiutil", "info", "-plist"], timeout=30))["images"]


def owned_attachment(image):
    matches = [x for x in hdiutil_info()
               if Path(x.get("image-path", "/nonexistent")).resolve() == image.resolve()]
    require(len(matches) <= 1, "Ambiguous attachment; do not guess a device")
    return matches[0] if matches else None


def detach_owned(image):
    attached = owned_attachment(image)
    if attached is None:
        return
    require(attached.get("writeable") is False, "Owned attachment unexpectedly writable")
    nodes = [x["dev-entry"] for x in attached.get("system-entities", [])
             if re.fullmatch(r"/dev/disk[0-9]+", x.get("dev-entry", ""))]
    require(nodes, "No returned whole-disk node for this exact owned image")
    subprocess.run(["hdiutil", "detach", nodes[0]], check=True, capture_output=True, timeout=60)
    require(owned_attachment(image) is None, "Owned image remains attached")


def checked_remove_owned_directory(path, parent, identity, anchor):
    # Only a directory created by this invocation may be recursively removed.
    p = path.resolve()
    st = path.lstat()
    require(not path.is_symlink() and stat.S_ISDIR(st.st_mode)
            and p.parent == parent.resolve() and p.is_relative_to(anchor.resolve())
            and (st.st_dev, st.st_ino) == identity,
            "Owned cleanup identity/path changed; leave files for review")
    shutil.rmtree(p)


@contextlib.contextmanager
def matching_original_input(root, logs):
    root = root.resolve()
    scratch_parent = root / "build/ci-original-input"
    require(scratch_parent.resolve().is_relative_to(root), "Scratch path escapes owned root")
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="systemos-", dir=scratch_parent))
    scratch_identity = (scratch.stat().st_dev, scratch.stat().st_ino)
    image, mount = scratch / MEMBER, scratch / "mount"
    mount.mkdir()
    target_root = root / ".cache/firmware/target-volumes/os-mount"
    target_identity = None
    record = dict(status="ORIGINAL_INPUT_PREPARATION_STARTED",
                  source_url=URL, library_sha256=LIBRARY_SHA256,
                  original_input_uploaded=False, cleanup_completed=False)
    try:
        require(not target_root.exists() and not target_root.is_symlink()
                and target_root.parent.resolve().is_relative_to(root),
                "Do not replace/escape an existing original-input tree")
        require(shutil.disk_usage(root).free > max(SIZE + (128 << 20),
                                                  TEST_FREE + LIBRARY_SIZE + (64 << 20)),
                "Insufficient transfer/test disk reserve")
        progress("original-input transfer START")
        record.update(extract_official_member(root, image))
        progress("original-input transfer PASS; encoded_bytes=" + str(record["zip_encoded_bytes"]))
        before = (image.stat().st_size, image.stat().st_mtime_ns)
        require(owned_attachment(image) is None, "New owned image already attached")
        attached = plistlib.loads(subprocess.check_output([
            "hdiutil", "attach", "-readonly", "-imagekey", "diskimage-class=CRawDiskImage",
            "-nobrowse", "-noautofsck", "-owners", "off", "-mountpoint", str(mount),
            "-plist", str(image)], timeout=60))
        require(any(Path(x.get("mount-point", "/nonexistent")).resolve() == mount.resolve()
                    for x in attached.get("system-entities", [])),
                "Require exact returned owned mountpoint")
        owner = owned_attachment(image)
        require(owner is not None and owner.get("writeable") is False,
                "Require actual read-only owned attachment")
        original = mount / LIBRARY_PATH
        require(original.is_file() and not original.is_symlink()
                and original.stat().st_size == LIBRARY_SIZE
                and sha(original) == LIBRARY_SHA256, "Wrong original QuartzCore library")
        target_root.mkdir(parents=True)
        target_identity = (target_root.stat().st_dev, target_root.stat().st_ino)
        target = target_root / LIBRARY_PATH
        target.parent.mkdir(parents=True)
        shutil.copyfile(original, target)
        require(sha(target) == LIBRARY_SHA256, "Staged original library copy mismatch")
        detach_owned(image)
        require((image.stat().st_size, image.stat().st_mtime_ns) == before
                and sha(image) == SHA256, "Read-only source image bytes/metadata changed")
        image.unlink()  # Only this invocation's uniquely-created source path.
        require(shutil.disk_usage(root).free > TEST_FREE,
                "Author host tests require more than5.25GiB free")
        record.update(status="MATCHING_ORIGINAL_INPUT_STAGED",
                      library_bytes=LIBRARY_SIZE, source_detached_before_tests=True)
        yield record
        record["status"] = "ORIGINAL_INPUT_HOST_TEST_SCOPE_COMPLETED"
    finally:
        # A partial hdiutil attach may exist even if attach raised; find it by
        # the unique image path, never by a guessed /dev/disk number.
        try:
            detach_owned(image)
            if target_identity is not None and target_root.exists():
                checked_remove_owned_directory(target_root, target_root.parent, target_identity, root)
            checked_remove_owned_directory(scratch, scratch_parent, scratch_identity, root)
            record["cleanup_completed"] = True
        except Exception as error:
            record["cleanup_error"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            (logs / "original-input-provenance.json").write_text(json.dumps(record, indent=2) + "\n")


def qualify_author_host(root, device, logs, run, host_reuse):
    source = device / "scripts/check-quartzcore-turnip-cache-host.py"
    target = root / "scripts/check-quartzcore-turnip-cache-host.py"
    require(not target.exists() and not target.is_symlink(),
            "Do not overwrite an existing device qualification overlay")
    require(sha(source) == "eae106179803091de6d065a57fd9af737184d1bae90927313255521c84fcc311", "Wrong original device checker source")
    adapter = Path(__file__).with_name("reviewed-quartzcore-cache-layout.py")
    require(sha(adapter) == CHECKER_SHA256[source.name], "Unreviewed Q cache layout adapter")
    shutil.copy2(adapter, target)
    checker_sources = {}
    for name, expected in CHECKER_SHA256.items():
        checker = root / "scripts" / name
        require(sha(checker) == expected, "Wrong exact author checker: " + name)
        checker_sources[name] = expected
    require(shutil.disk_usage(root).free > TEST_FREE, "Preserve author test free-space bound")
    from reuse_frozen_host import verify_reused_host_inputs
    verify_reused_host_inputs(root, host_reuse)
    require(host_reuse["host_bridge_built_in_this_run"] is False, "Host reuse mode must remain explicit")
    bridge_key = "public-build/build/adreno-metal-bridge/host/libadreno_metal_bridge.a"
    mesa_key = "public-build/build/mesa-tu/src/freedreno/vulkan/libvulkan_freedreno.dylib"
    peer_key = "public-build/build/turnip-darwin-host/libhostiokit.dylib"
    bridge_sha = host_reuse["required_inputs"][bridge_key]["sha256"]
    runtime_before = sha(root / "build/turnip-darwin-host/libhostiokit.dylib")
    require(runtime_before == host_reuse["required_inputs"][peer_key]["sha256"], "Initial recovered host runtime differs")
    (logs / "bridge-host-reused.json").write_text(json.dumps(dict(
        status="AUTHENTICATED_C6_HOST_ARCHIVE_REUSED_NOT_REBUILT",
        sha256=bridge_sha, source_provenance=host_reuse["provenance"],
        host_bridge_built_in_this_run=False), indent=2) + "\n")
    require(shutil.disk_usage(root).free > TEST_FREE, "Preserve free space after host bridge")
    # Genuine full suite: smoke, deferred BO controls, pipeline caches,
    # original QuartzCore and priming, plugin sequence and watchdog.
    run([sys.executable, "scripts/check-turnip-darwin-host.py"],
        "full-author-host-suite", 2400)
    work = root / "build/ci-preserved-original-qualification"
    require(not work.exists(), "Preserve prior qualification payloads")
    work.mkdir()
    for name, directory, timeout in [
        ("check-quartzcore-turnip-cache-host.py", "quartzcore", 660),
        ("check-priming-cache-host.py", "priming", 360),
    ]:
        require(shutil.disk_usage(root).free > TEST_FREE, "Preserve author test free-space bound")
        run([sys.executable, "scripts/" + name, "--output", work / directory],
            "preserved-" + directory + "-qualification", timeout)
    qpath, ppath = work / "quartzcore/checkpoint.json", work / "priming/checkpoint.json"
    q, p = json.loads(qpath.read_text()), json.loads(ppath.read_text())
    require(q["checker_sha256"] == CHECKER_SHA256["check-quartzcore-turnip-cache-host.py"]
            and p["checker_sha256"] == CHECKER_SHA256["check-priming-cache-host.py"],
            "Author report checker identities differ")
    require(q["original_library_sha256"] == LIBRARY_SHA256, "Wrong qualified original library")
    require(set(q["cases"]) == {"produce", "consume", "uuid-miss", "empty-driver"}
            and set(p["cases"]) == {"cold-miss", "produce", "consume", "uuid-miss",
                                   "truncated-miss", "checksum-miss"}, "Missing real controls")
    for report in [q, p]:
        require(report["physical_device_tested"] is False and report["shader_execution"] is False
                and report["hardware_ready"] is False and report["ios_execution"] is False,
                "Do not promote host-software controls into physical GPU proof")
    for name, expected in CHECKER_SHA256.items():
        require(sha(root / "scripts" / name) == expected, "Checker mutated during execution")
    # JSON checkpoints carry identities/counters only; no archive/cache binaries
    # are copied into the public artifact while contamination review is pending.
    for source, name in [(qpath, "quartzcore-host-checkpoint.json"),
                         (ppath, "priming-host-checkpoint.json")]:
        require(source.stat().st_size < 2 << 20, "Bounded qualification report")
        shutil.copy2(source, logs / name)
    verify_reused_host_inputs(root, host_reuse, allow_rebuilt_peer=True)
    runtime_after = sha(root / "build/turnip-darwin-host/libhostiokit.dylib")
    require(q["peer"]["sha256"] == p["peer_sha256"] == runtime_after,
            "Preserved Q/P did not use the freshly whole-suite-built runtime")
    require(q["driver"]["sha256"] == p["driver_sha256"] == host_reuse["required_inputs"][mesa_key]["sha256"],
            "Preserved Q/P host Mesa identity differs")
    require(q["host_bridge_sha256"] == p["host_bridge_sha256"] == bridge_sha,
            "Preserved Q/P host bridge identity differs")
    from reuse_frozen_host import reviewed_Q_adapter_record
    return dict(status="FULL_HOST_CONTROLS_PASS_REVIEWED_Q_CACHE_LAYOUT",
                test_suite_prefix_substitution=False,
                reviewed_Q_cache_layout_adapter=reviewed_Q_adapter_record(),
                original_Q_checker_executed=False,
                host_bridge_built_in_this_run=False,
                host_bridge_reuse_input_sha256=bridge_sha,
                host_runtime_before_suite_sha256=runtime_before,
                host_runtime_after_suite_sha256=runtime_after,
                cached_host_Mesa_sha256=host_reuse["required_inputs"][mesa_key]["sha256"],
                checker_sources=checker_sources, complete_suite_executed=True,
                host_suite_original_sha256="7ab580b33aa544a0e8931679884d2aa717e5663d6d9ff52ee5cda90c128862c0",
                host_suite_patched_sha256=CHECKER_SHA256["check-turnip-darwin-host.py"],
                host_suite_byte_identity_is_original=False,
                host_only_link_compatibility_applied=True,
                original_library_sha256=LIBRARY_SHA256,
                quartzcore_checkpoint_sha256=sha(qpath), priming_checkpoint_sha256=sha(ppath),
                derived_cache_archive_payloads_uploaded=False,
                hardware_GPU_execution_verified=False, shader_execution=False,
                iOS_execution=False, installation_ready=False)
