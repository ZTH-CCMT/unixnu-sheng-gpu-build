"""Apply the nine-file diagnostic capture patch on unchanged v3 policy; host-only preflights."""
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
NEW_HEADERS = {"device/package/TouchLifecycle.h", "device/package/TouchRawEvidence.h",
               "device/package/TouchEvidenceWire.h", "device/package/TouchEvidenceSerialize.h"}
FILES = {
    "device/drivers/ShengNovatekTouch/NvtProtocol.h",
    "device/drivers/ShengNovatekTouch/NvtProtocol.c",
    "device/drivers/ShengNovatekTouch/Test/nvt-protocol.c",
    "device/package/TouchProbe.cpp", "device/package/BootLog.c", *NEW_HEADERS,
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
    require({name for name, item in value["files"].items() if item["before"] is None} == NEW_HEADERS,
            "Only the four new package headers may have no original")
    require(value["whole_stream_timeout_us"] == 100000 and value["script_guard_retry_ms"] == 100
            and value["valid_stylus_preserves_tracking"] is True and value["timer_wake_spi"] is False,
            "Lifecycle policy parameters differ")
    diagnostic = value.get("diagnostic_evidence", {})
    require(diagnostic.get("id") == "touch-raw-evidence-v1"
            and diagnostic.get("diagnostic_only") is True
            and diagnostic.get("not_a_fix") is True
            and diagnostic.get("algorithm_base_patch_sha256") ==
                "e5b77be888b47ee74ad43f9163cea3394b750f6246ac9168f643e569fe05a609"
            and diagnostic.get("default_disabled") is True
            and diagnostic.get("new_hardware_transactions") is False
            and diagnostic.get("changes_root_or_data") is False,
            "Not the reviewed diagnostic-only raw evidence scope")
    require(re.fullmatch(r"[0-9a-f]{64}", value.get("patch_sha256") or "") is not None
            and all(re.fullmatch(r"[0-9a-f]{64}", item.get("after") or "") is not None
                    for item in value["files"].values()),
            "Raw evidence candidate is incomplete; freeze all nine reviewed files first")
    return value


def read_patch():
    value = spec()
    patch = (HERE / "author-to-raw-evidence.patch").read_bytes()
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
        if name in NEW_HEADERS:
            require(old == [b"/dev/null"] and section.count(b"new file mode 100644\n") == 1,
                    "New diagnostic/lifecycle header must be a regular source file")
        else:
            require(old == [("a/" + name).encode()] and b"new file mode" not in section,
                    "Unexpected creation of existing source")
    require(seen == FILES and patch.count(b"new file mode") == len(NEW_HEADERS), "New-file allowlist differs")
    return patch


def apply_touch_patch(top):
    top = Path(top).resolve()
    value = spec()
    read_patch()
    for relative, item in value["files"].items():
        path = top / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(top), "Unexpected linked touch source")
        if item["before"] is None:
            require(not path.exists(), "New diagnostic/lifecycle header already exists")
        else:
            require(path.is_file() and sha(path.read_bytes()) == item["before"], "Unexpected original touch source: " + relative)
    patch = HERE / "author-to-raw-evidence.patch"
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


def raw_evidence_test(top, output):
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    require(compiler is not None, "C++ compiler missing for evidence header preflight")
    source = Path(output).with_suffix(".cpp")
    source.write_text(r"""#include "TouchRawEvidence.h"
#include "TouchEvidenceWire.h"
#include "TouchEvidenceSerialize.h"
#include <cassert>
#include <cstring>
using namespace touch_raw_evidence;
static Storage storage;
static SlotState slots[Slots];
static ContactState contact[Slots];
static uint8_t raw[RawBytes],peek[PeekBytes],blob[TouchEvidenceWire::MaxBlob];
static int16_t reference[Nodes];
static char text[TouchEvidenceWire::RowCapacity];
static Prepared frame(Collector &c,uint64_t now,uint16_t seq,uint8_t data,uint8_t published) {
    const FrameInfo info={now,seq,4,data,published};
    return c.prepare(raw,RawBytes,peek,PeekBytes,reference,Nodes,slots,Slots,true,info);
}
int main() {
    Collector disabled;
    assert(disabled.configure(false,nullptr,0));
    disabled.guard(9999999);
    assert(!disabled.frozenAcquire());
    Collector c;
    assert(c.configure(true,&storage,100));
    reference[0]=-32768;reference[1]=32767;
    slots[0].active=1;slots[0].tracking_id=1;slots[0].fx=INT64_C(0x123456789);
    assert(frame(c,100,1,0x1d,0)==CapturedP);
    assert(!c.after(0,contact,Slots,0));
    contact[0].slot=0;contact[0].tracking_id=1;contact[0].x=100;contact[0].y=200;
    assert(frame(c,200,2,3,0)==AwaitingM);reference[0]=123;
    assert(c.after(1,contact,Slots,1));
    assert(frame(c,300,3,3,1)==AwaitingM);assert(c.after(1,contact,Slots,1));
    assert(frame(c,400,4,3,1)==AwaitingM);assert(c.after(0,contact,Slots,0));
    assert(!c.frozenAcquire());c.guard(2000200);
    const Frozen *f=c.frozenAcquire();
    assert(f && f->valid_mask==15 && f->metadata_count==3 && f->freeze_reason==Deadline);
    assert(f->samples[FirstP].m_result==MNotCalled);
    assert(f->samples[FirstPositiveM].pre_slots[0].fx==INT64_C(0x123456789));
    assert(f->samples[FirstPositiveM].reference[0]==-32768);
    const size_t n=TouchEvidenceSerialize::serialize(*f,blob,sizeof(blob));
    assert(n==TouchEvidenceSerialize::HeaderBytes+4*TouchEvidenceSerialize::SampleBytes+
        3*TouchEvidenceSerialize::MetadataBytes);
    assert(!std::memcmp(blob,"TEVRAW01",8));
    assert(blob[8]==1 && blob[9]==0 && blob[10]==0 && blob[11]==0);
    const uint32_t encoded=(uint32_t)blob[12]|((uint32_t)blob[13]<<8)|
        ((uint32_t)blob[14]<<16)|((uint32_t)blob[15]<<24);
    assert(encoded==n);
    assert(TouchEvidenceSerialize::serialize(*f,blob,n-1)==0);
    static const uint8_t vector[]={'1','2','3','4','5','6','7','8','9'};
    assert(TouchEvidenceWire::crc32(vector,sizeof vector)==0xcbf43926u);
    const uint32_t crc=TouchEvidenceWire::crc32(blob,n);
    const size_t chunks=(n+TouchEvidenceWire::RawChunk-1)/TouchEvidenceWire::RawChunk;
    for(size_t i=0;i<chunks;++i) {
        const size_t bytes=TouchEvidenceWire::rows(text,sizeof text,blob,n,crc,(uint32_t)i,0x123);
        assert(bytes>0 && bytes<sizeof text && std::strstr(text,"[touch evidence]") &&
            std::strstr(text,"TEV1 off="));
    }
    const uint64_t observed=f->observed_frames;
    assert(frame(c,2000300,5,3,0)==Ignored);c.guard(9999999);
    assert(f->observed_frames==observed);
}
""")
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(Path(top) / "device/package"), str(source), "-o", str(output)], check=True)
    subprocess.run([str(output)], check=True)


def preflight():
    top = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
    value = spec()
    with tempfile.TemporaryDirectory(prefix="touch-raw-evidence-preflight-", dir=top) as name:
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
        raw_evidence_test(temp, temp / "touch-evidence-test")
    print(json.dumps({"status": "TOUCH_RAW_EVIDENCE_DIAGNOSTIC_PREFLIGHT_PASS", "patch_sha256": value["patch_sha256"], "files": len(FILES)}))


if __name__ == "__main__":
    import sys
    require(sys.argv[1:] == ["--preflight"], "Usage: touch_frame_kind.py --preflight")
    preflight()
