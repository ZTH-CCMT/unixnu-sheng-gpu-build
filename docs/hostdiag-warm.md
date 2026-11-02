# Frozen C4 HOSTDIAG and conditional hostsim VA control

LOCAL PREPARATION ONLY. Not run, not published, not a tablet change or installation.

The authenticated input is the fixed failed-source-build artifact13135679819 from
run41434261061/attempt1, commitdf1f751d98540fa12f839881b1c7cfc613595bdb.
ZIP8306350bytes, SHA332b6683689391b0c658942907b673b73fc51417c05e58dfd47455ef14d9a6c7.
The required four host Mach-O files and compiler profile match their recorded
bytes/SHA. All four primaryCodeDirectory page hashes were recomputed locally.
Six exact optional hidden producer logs are absent from the GitHub ZIP and are
explicitly recorded, not silently accepted as a complete manifest.

Deploy:
- unixnu-hostdiag-warm.yml -> .github/workflows/unixnu-hostdiag-warm.yml
- warm_host_diag.py, warm-policy.json, host-gpu-service-va.cpp -> ci/
- README.md -> optional documentation location; does not replace main build README

This separate workflow has contents:read and the minimum additional actions:read
for the fixed artifact. It uses only the existing pinned checkout/setup-python/
upload-artifact actions. The download authenticates run/head/attempt/conclusion
and artifact ID/name/digest/size. The GitHub bearer token is not forwarded to the
signed asset URL, serialized, or inherited by the tested program.

Before execution, require ARM64 macOS, exact recorded Appleclang21/Xcode26.6
compiler text, SDK26.5 and minimumOS26.0; verify recorded Mach-O targets/dependency
paths and real codesign strict/CDHash on the new Mac. Only an exact-version
SPIRV-Tools1.4.363.0 bottle is installed, not Mesa/Rust/toolchains. Its current
hash/signature/target are recorded. C4 did not retain its previous dependency hash,
so this plan makes no bit-identical complete-runtime-environment claim.

Baseline restores only the fixed required files into a separate work directory,
marks them readonly and runs the exact C4 generator with only HOSTSIM_TRACE=1
added to its runtime diagnostics. RD dump/header files stay outside uploaded logs.
All baseline binary bytes are preserved; failure is not accepted as producer PASS.

Conditional A/B is permitted only if that baseline reports stage5/VK-2 plus first
BoAlloc success then BoMap(method3) Busy2 and the original markers/OOM message.
A different failure stops. The failed IOVA value is inferred from fixed-source
first-fit/layout evidence, not claimed as directly printed by the old binary.

For the matching failure only, exact pinned source and four components are
validated, reviewed host fixtures restored, and host_gpu_service-va.cpp applied.
It uses the current production GpuClientVaStart and client-window formula with
the original (32,48] guard. Only the reviewed strict host core/shim prefix is
compiled. No Mesa/Rust/smoke/shader generation compilation, no production driver
or ABI modification. Cached Mesa and both smoke executables remain exact C4 bytes.
The corrected shim must pass real strict signing/target/dependency checks. The
same generator and original RD success criteria must then return0. Frozen
baseline hashes are checked again. A hostsim control is not physical GPU proof.

The 20minute job uploads only hostdiag-artifact text logs and JSON identities,
even on failure. No recovered binaries, SDK/OS files, dependency trees, GPU memory
dumps or generated replay header are uploaded. All results remain
HOSTDIAG_ONLY_NOT_INSTALL_READY. Root must review before triggering.
