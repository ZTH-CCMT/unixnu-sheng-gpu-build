"""Apply the six-file hash-locked touch lifecycle v3 patch; run small host preflights."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "os27-update-lock.json").read_text())
HEADER = "device/package/TouchLifecycle.h"
FILES = {
    "device/drivers/ShengNovatekTouch/NvtProtocol.h",
    "device/drivers/ShengNovatekTouch/NvtProtocol.c",
    "device/drivers/ShengNovatekTouch/Test/nvt-protocol.c",
    "device/package/TouchProbe.cpp", "device/package/BootLog.c", HEADER,
}


def require(ok, message):
    if not ok: raise RuntimeError(message)


def sha(data): return hashlib.sha256(data).hexdigest()


def spec():
    value = LOCK["touch_frame_kind_fix"]
    require(value["id"] == "finger-only-thp-touch-lifecycle-v3" and value["policy_version"] == 3,
            "Not the reviewed v3 lifecycle policy")
    require(set(value["files"]) == FILES, "Touch patch file allowlist differs")
    require(value["base_device_commit"] == LOCK["pins"]["device"], "Touch patch base device differs")
    require(value["base_novatek_commit"] == LOCK["components"]["device/drivers/ShengNovatekTouch"], "Touch component base differs")
    require({name for name, item in value["files"].items() if item["before"] is None} == {HEADER},
            "Only the new lifecycle header may have no original")
    require(value["whole_stream_timeout_us"] == 100000 and value["script_guard_retry_ms"] == 100
            and value["valid_stylus_preserves_tracking"] is True and value["timer_wake_spi"] is False,
            "Lifecycle policy parameters differ")
    return value


def read_patch():
    value = spec()
    patch = (HERE / "author-to-v3.patch").read_bytes()
    require(0 < len(patch) <= 131072 and sha(patch) == value["patch_sha256"], "Touch patch hash or size differs")
    require(not any(word in patch for word in (b"GIT binary patch", b"deleted file mode", b"rename from", b"rename to", b"copy from", b"copy to", b"old mode")),
            "Unexpected non-text source change")
    sections = re.split(rb"(?=^diff --git )", patch, flags=re.M)
    require(sections[0] == b"" and len(sections) == len(FILES) + 1, "Patch section count differs")
    seen = set()
    for section in sections[1:]:
        match = re.match(rb"diff --git a/([^\n]+) b/([^\n]+)\n", section)
        require(match is not None and match[1] == match[2], "Unexpected patch path pair")
        name = match[1].decode()
        require(name in FILES and name not in seen, "Unknown or duplicate patch path")
        seen.add(name)
        old = re.findall(rb"^--- (.+)$", section, re.M)
        new = re.findall(rb"^\+\+\+ (.+)$", section, re.M)
        require(new == [("b/" + name).encode()], "Unexpected target patch path")
        if name == HEADER:
            require(old == [b"/dev/null"] and section.count(b"new file mode 100644\n") == 1,
                    "Lifecycle header must be a new regular source file")
        else:
            require(old == [("a/" + name).encode()] and b"new file mode" not in section,
                    "Unexpected creation of existing source")
    require(seen == FILES and patch.count(b"new file mode") == 1, "New-file allowlist differs")
    return patch


def apply_touch_patch(top):
    top = Path(top).resolve()
    value = spec()
    read_patch()
    for relative, item in value["files"].items():
        path = top / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(top), "Unexpected linked touch source")
        if item["before"] is None:
            require(not path.exists(), "New lifecycle header already exists")
        else:
            require(path.is_file() and sha(path.read_bytes()) == item["before"], "Unexpected original touch source: " + relative)
    patch = HERE / "author-to-v3.patch"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=top, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=top, check=True, capture_output=True)
    for relative, item in value["files"].items():
        require(sha((top / relative).read_bytes()) == item["after"], "Unexpected patched touch source: " + relative)
    probe = (top / "device/package/TouchProbe.cpp").read_text()
    require("releaseStylusFingerContacts" not in probe and "memset(core.slots" not in probe,
            "Retired eager stylus release survived")
    require('#include "TouchLifecycle.h"' in probe and "lifetime.acceptValid(" in probe
            and "lifetime.published(" in probe and "expireTouchStream(" in probe,
            "Reviewed lifecycle integration missing")
    return value


def protocol_tests(top, output):
    source = Path(top) / "device/drivers/ShengNovatekTouch"
    compiler = shutil.which(os.environ.get("CC", "cc"))
    require(compiler is not None, "C compiler missing for protocol preflight")
    command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               "-I", str(source), str(source / "NvtProtocol.c"), str(source / "Test/nvt-protocol.c"), "-o", str(output)]
    subprocess.run(command, check=True)
    subprocess.run([str(output)], check=True)


def lifecycle_test(top, output):
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    require(compiler is not None, "C++ compiler missing for lifecycle header preflight")
    source = Path(output).with_suffix(".cpp")
    source.write_text(r"""#include "TouchLifecycle.h"
#include <cassert>
int main() {
    TouchLifecycle l;
    assert(l.waitMs(0,false)==0);
    assert(!l.acceptValid(1000)); l.published(1);
    assert(l.waitMs(1001,false)==100);
    assert(l.expire(100999,false)==TouchLifecycle::None);
    assert(!l.acceptValid(101000)); // A stylus acceptance refreshes the same clock.
    assert(l.physicalActive && l.waitMs(101000,false)==100);
    assert(l.expire(201000,true)==TouchLifecycle::GuardDeferred);
    assert(l.expire(201001,true)==TouchLifecycle::None);
    assert(l.waitMs(201001,true)==100 && !l.stalled && l.physicalActive);
    assert(l.expire(301000,false)==TouchLifecycle::Release);
    assert(l.stalled && !l.physicalActive && l.waitMs(301000,false)==0);
    assert(l.expire(401000,false)==TouchLifecycle::None);
    assert(l.acceptValid(401001) && !l.physicalActive);
    l.published(1); l.published(0);
    assert(l.waitMs(999999,false)==0);
}
""")
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(Path(top) / "device/package"), str(source), "-o", str(output)], check=True)
    subprocess.run([str(output)], check=True)


def preflight():
    top = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
    value = spec()
    with tempfile.TemporaryDirectory(prefix="touch-lifecycle-v3-preflight-", dir=top) as name:
        temp = Path(name)
        for relative, item in value["files"].items():
            if item["before"] is None: continue
            original = top / relative
            copy = temp / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, copy)
        value = apply_touch_patch(temp)
        protocol_tests(temp, temp / "nvt-protocol-test")
        lifecycle_test(temp, temp / "touch-lifecycle-test")
    print(json.dumps({"status": "TOUCH_LIFECYCLE_V3_PREFLIGHT_PASS", "patch_sha256": value["patch_sha256"], "files": len(FILES)}))


if __name__ == "__main__":
    import sys
    require(sys.argv[1:] == ["--preflight"], "Usage: touch_frame_kind.py --preflight")
    preflight()
