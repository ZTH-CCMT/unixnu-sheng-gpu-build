# UniXNU OS17 GPU components with full host qualification

This job builds the real signed iOS17 Adreno Metal plugin, Turnip and bridge and
runs the complete author host-software controls using the exact matching original
QuartzCore input. Output remains a candidate: physical GPU, iOS execution and
installation readiness are separate qualifications.

The host simulator now advertises the current producer client aperture. Its old
0x20000000 start overlapped current preemption mappings, producing BoMap Busy
translated into Vulkan OUT_OF_DEVICE_MEMORY. Warm control run41440107606 held
cached Mesa and both smoke executables unchanged: baseline failed BoMap Busy;
changing only the reviewed host configuration made the original replay generator
pass. This proves the host-model issue under that control, not tablet RAM exhaustion
or a physical GPU fix. The source uses GpuClientVaStart and the existing (32,48]
input-width guard/current client-window formula. Production driver/ABI is unchanged.

Exact inputs remain UniXNU6790e7ce6e77f67a9174fba1255e64eacf1c41ad,
device28b30285768e04008ac525c04182e245bfac441e, their four component gitlinks,
Mesa85fda3b36405bcaea8bffc64aa4f2651dc90770d and
metal2vulkan624bab3918de5b978e1101517abca2b4fa426565. Hash-bound authored host
fixtures, the missing original Preempt core in the host build list and the host
clock export are retained. The full host script records its original and effective
identities separately; its original runtime test logic remains intact.

Matching original input is downloaded transiently from the fixed official Apple
IPSW using unmodified pinned RangeFile plus reviewed transport restrictions.
Version/build/product/unique Erase identity, exact BuildManifest hash, member size,
encoded size, CRC, SHA384/SHA256 and final QuartzCore9670832B/SHA606f... are checked.
Each HTTP range and response is bounded before reading; a dedicated RuntimeError
1800s deadline cannot be swallowed by RangeFile retries. The raw APFS image is
mounted readonly, copied only to an owned test-input tree, detached/rehashed and
deleted before tests. Inode/path-guarded cleanup removes the staged original input.

No prefix-only surrogate is called full qualification. The full author suite,
fresh preserved QuartzCore4-case controls and priming6-case controls must return
success and match their actual checkpoint/source identities. PASS metadata follows
successful original-input cleanup. Self-built iOS binary validation retains real
SDK linking, actual4KiB SHA256 CodeDirectory pages/CDHash, actual codesign strict
verification, resource seal and trust.json agreement. Hardware flags remain false.

The replay generator has only a diagnostics wrapper: failure/timeout prints actual
captured stdout/stderr and rethrows. Commands, environment, timeout, RD parsing
and all original success criteria remain unchanged. It does not hide a failure.

A failed job separately preserves exact allowlisted public build outputs and own
logs through collector52cde8..., under2GiB. Its marker is
ONLY_RECOVERY_NOT_INSTALL_READY; signatures/qualification are not inferred.
include-hidden-files:true applies only to that explicit collector output so its
safe .cache__*.log names are retained. No SDK or original Apple OS image/raw/library, RD memory dump,
shader/cache/archive payload or dependency tree is added to upload paths. Full
qualification checkpoints contain identities/counters only, not original or
compiled Apple cache bytes. Successful candidate and recovery artifacts are distinct.

Deployment: unixnu-gpu-full-qualification.yml to
.github/workflows/unixnu-gpu-only.yml; build_gpu_only.py, qualify_gpu_host.py,
verify_gpu_artifacts.py, host-XnuMemoryFixture.h, host-resource-private.h,
host-check-turnip-darwin-host.py, host-host_gpu_service.cpp,
host-gen-turnip-replay.py and collect_failed_components.py to ci/;
ci-dependencies.json and this README to repository root.

Manual dispatch and one exact main-push commit gate are retained. All actions are
existing pinned versions; contents:read only, standard macos26ARM64, Cargo1,
Ninja/make2, Rust1.98, initial8GiB free, author5.25GiB test reserve, 120minute job,
2GiB artifact bound and7day retention remain. No paid larger runner, Xcode deletion,
cache service or skipped qualification is introduced. Review before publishing.
