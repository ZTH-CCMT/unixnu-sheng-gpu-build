"""Apply the reviewed, hash-locked THP frame-kind fix and run its host protocol tests."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "os27-update-lock.json").read_text())
FILES = {
    "device/drivers/ShengNovatekTouch/NvtProtocol.h",
    "device/drivers/ShengNovatekTouch/NvtProtocol.c",
    "device/drivers/ShengNovatekTouch/Test/nvt-protocol.c",
    "device/package/TouchProbe.cpp",
    "device/package/BootLog.c",
}

def require(ok, message):
    if not ok: raise RuntimeError(message)

def sha(data): return hashlib.sha256(data).hexdigest()

def spec():
    value = LOCK["touch_frame_kind_fix"]
    require(set(value["files"]) == FILES, "Touch patch file allowlist differs")
    require(value["base_device_commit"] == LOCK["pins"]["device"], "Touch patch base device differs")
    require(value["base_novatek_commit"] == LOCK["components"]["device/drivers/ShengNovatekTouch"], "Touch component base differs")
    return value

def read_patch():
    value = spec()
    patch = (HERE / "touch-frame-kind.patch").read_bytes()
    require(0 < len(patch) <= 131072 and sha(patch) == value["patch_sha256"], "Touch patch hash or size differs")
    require(b"GIT binary patch" not in patch and b"new file mode" not in patch and b"deleted file mode" not in patch, "Unexpected non-text source change")
    old = re.findall(rb"^--- a/(.+)$", patch, re.M)
    new = re.findall(rb"^\+\+\+ b/(.+)$", patch, re.M)
    require(len(old) == len(new) == len(FILES) and set(old) == set(new) == {p.encode() for p in FILES}, "Touch patch path allowlist differs")
    return patch

def apply_touch_patch(top):
    top = Path(top).resolve()
    value = spec()
    read_patch()
    for relative, item in value["files"].items():
        path = top / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(top), "Unexpected linked touch source")
        require(sha(path.read_bytes()) == item["before"], "Unexpected original touch source: " + relative)
    patch = HERE / "touch-frame-kind.patch"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=top, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=top, check=True, capture_output=True)
    for relative, item in value["files"].items():
        require(sha((top / relative).read_bytes()) == item["after"], "Unexpected patched touch source: " + relative)
    return value

def protocol_tests(top, output):
    source = Path(top) / "device/drivers/ShengNovatekTouch"
    output = Path(output)
    compiler = shutil.which(os.environ.get("CC", "cc"))
    require(compiler is not None, "C compiler missing for protocol preflight")
    command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               "-I", str(source), str(source / "NvtProtocol.c"), str(source / "Test/nvt-protocol.c"), "-o", str(output)]
    subprocess.run(command, check=True)
    subprocess.run([str(output)], check=True)


def preflight():
    top = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
    with tempfile.TemporaryDirectory(prefix="touch-kind-preflight-", dir=top) as name:
        temp = Path(name)
        for relative in FILES:
            original = top / relative
            copy = temp / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, copy)
        value = apply_touch_patch(temp)
        protocol_tests(temp, temp / "nvt-protocol-test")
    print(json.dumps({"status": "TOUCH_KIND_PREFLIGHT_PASS", "patch_sha256": value["patch_sha256"], "files": len(FILES)}))

if __name__ == "__main__":
    import sys
    require(sys.argv[1:] == ["--preflight"], "Usage: touch_frame_kind.py --preflight")
    preflight()
