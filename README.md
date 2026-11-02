# UniXNU OS17 GPU component build plan

This revision repairs the pinned host simulator fixture after the first cloud attempt failed. It builds candidate user-space GPU components; it does not boot or install them or claim a verified installation.

## Files and placement

Copy `unixnu-gpu-only.yml` to `.github/workflows/unixnu-gpu-only.yml` in the approved dedicated repository, and copy `build_gpu_only.py`, `verify_gpu_artifacts.py`, `host-XnuMemoryFixture.h` and `host-resource-private.h` to `ci/`. The repository needs no device secret. The manual dispatch has no free-form shell, source-ref, seed, or signing-key input.

The first run (41422620304, commit38429792398b499d2594b3284123022d31524fd9) passed real SDK/signature preflight, compiler vectors and host Turnip build, then failed because the pinned host fixture omitted IOFree. This revision preserves production driver, plugin, Turnip and bridge source pins.

## Exact inputs

- UniXNU: `6790e7ce6e77f67a9174fba1255e64eacf1c41ad`.
- Device policy/probe source: `28b30285768e04008ac525c04182e245bfac441e`.
- Four components follow that UniXNU commit's gitlinks: Adreno740, AdrenoMetal, AdrenoPM4, ArmSmmu4K. The job checks their actual HEAD against `git ls-tree`; it never uses component main.
- Mesa: `85fda3b36405bcaea8bffc64aa4f2651dc90770d`, exact recorded patches.
- metal2vulkan: `624bab3918de5b978e1101517abca2b4fa426565`, exact recorded patches.
- Real macOS26 ARM64 runner, Xcode's macOS and iPhoneOS SDKs. This matches the author's chosen host family; Intel/macOS15 compatibility is not asserted.
- LLVM21 or newer (AIR fixture assembly only; the pinned native Rust translator has no llvm-sys/LLVM runtime link and does not need LLVM_CONFIG_PATH), Rust1.98.0 and aarch64-apple-ios target; Mesa Python requirements, Vulkan headers and real Vulkan shader tools. Homebrew tool versions are recorded at execution rather than claimed deterministic here.

## Resource boundary and estimate

Job timeout120minutes; Cargo one build job; RUSTUP_TOOLCHAIN=1.98.0 is explicit, and actual bare cargo/rustc versions plus the installed iOS target are checked. Private resource adapters invoke the real Ninja/make with a final `-j2`; these do not impersonate SDK, clang, or codesign and are recorded. At least8GiB must remain free after installing tools. Insufficient space stops the job; it never deletes Xcode.

A provisional planning allowance is30-90minutes, up to the120minute cap. Source downloads, Rust LTO and runner queueing affect actual duration. Completing the full pipeline on the standard small ARM64 runner remains a qualification requirement. This workflow uses the approved dedicated public repository and standard runner; it claims no private or paid larger-runner allowance.

## Real SDK/signature gates

Before a long build, the helper requires real SDK headers/frameworks, cross-links an ordinary ARM64 iOS17 executable, signs it with the actual codesign, and independently parses its bytes.

For the production plugin, Turnip dylib and probe daemon, validation checks:

- ARM64 rather than arm64e; actual LC_BUILD_VERSION platform2/minimum17.0.
- A bounded LC_CODE_SIGNATURE SuperBlob and primary SHA256 CodeDirectory.
- Page-size exponent12, every actual4KiB code-page digest and the computed CDHash.
- Agreement with the real codesign detail, strict signature verification and the producer trust.json CDHashes.
- The bundle's resource seal as well as executable page hashes.

An empty signing shim returning success cannot satisfy these gates. Signing is ad hoc `--sign -`; no developer private key is supplied.

## Explicit host-peer build split

The pinned plugin builder unconditionally generates a synthetic prefix replay. If its host peer is absent, the original whole host suite requires the original iPadOS QuartzCore/default.metallib.

This source-only stage does not fetch that Apple input. It executes only the exact, hash-bound build prefix of `check-turnip-darwin-host.py`, stopping before its first software-test invocation. This creates the genuine host peer and plugin_smoke; the original replay generator then records its synthetic run normally. The plugin, Turnip and bridge producer source is unmodified.

The prefix is not presented as passing the author's complete qualification. Its original blob identity and extracted prefix SHA256 are in the output manifest.

## Outputs and mandatory qualification gate

The candidate artifact contains self-built NativeAdrenoMetal.bundle (including Turnip), adrenoprobed and its generated plists, trust.json, the iOS Metal bridge archive, build logs, and input/output hashes. No SDK files, Apple OS images/libraries, Data seed, tablet platform seed or owner private key are uploaded.

The manifest and marker explicitly say:

`CANDIDATE_COMPONENTS_BUILT_SIGNED_NOT_INSTALL_READY`

`REQUIRED_PENDING_ORIGINAL_INPUT`

Before installation, the next controlled qualification stage must use the legitimate matching original input locally or temporarily on the runner, never upload it:

1. QuartzCore/default.metallib of iPadOS17.7.11-21H461, SHA256 `606f913adf520420f9b4bb666efb782a68c830f082f1e559e17b20d0d13adbc9`.
2. Build the matching host bridge, then run the author's `check-quartzcore-turnip-cache-host.py` and `check-priming-cache-host.py` with fresh bounded outputs. Restore the remaining full host qualification steps rather than treating this prefix build as their substitute.
3. Record the original-input provenance/hash and all resulting source/binary/cache identities. Gate release on explicit PASS.
4. Back on F:, independently verify artifacts and prepare copied local seed/addon/trust inputs with the matching current owner identity. Never upload that private owner key.
5. Physical qualification remains separate: publication, GPU initialization, submit/fence/present, known output and actual memory pressure must be measured after a separately approved test. A successful compile is not hardware GPU proof.

## Author sources

- [GPU pipeline](https://unixnu.com/drivers/adreno740)
- [Pinned plugin builder](https://github.com/UniXNU/UniXNU/blob/6790e7ce6e77f67a9174fba1255e64eacf1c41ad/scripts/build-adreno-metal-plugin.py)
- [Pinned replay/host suite](https://github.com/UniXNU/UniXNU/blob/6790e7ce6e77f67a9174fba1255e64eacf1c41ad/scripts/check-turnip-darwin-host.py)
- [Original-input suite](https://github.com/UniXNU/UniXNU-sheng/blob/28b30285768e04008ac525c04182e245bfac441e/scripts/check-quartzcore-turnip-cache-host.py)

Source comparison did not find an exact author-published sheng GPU component artifact to download. This dedicated workflow repairs the host fixture after a failed first run and produces candidate components; it does not repackage or claim a verified author installation.

## Pinned host fixture repair

The fixture layer overlays tests/XnuMemoryFixture.h, guarded by exact before/after hashes; a generated host include supplies two Apple GPU-role constants. The additional host script and service overlays are described below. The fixture uses calloc/free and an explicit controllable host task role. It does not implement or impersonate SDK/signing tools, alter production driver/ABI, or claim physical GPU scheduling. CI records the overlay hashes; all original full-qualification and physical-GPU gates remain pending. Local genuine Linux syntax checks covered the original nine shared core sources and host_gpu_service, plus allocation/free and role primitive execution; these checks do not establish Darwin linking, full host-qualification success or physical GPU behavior.

The helper now reports each phase start/completion and a 30-second running heartbeat while preserving the original subprocess timeout.

## Complete host link repair

The second cloud attempt (41426216552, a1bf684c843439fe665991a960ea9965e5a2b33f) compiled the repaired fixture but could not link the peer: the original host list omitted NativeAdrenoPreempt, and the UserClient clock export was absent. Two additional exact-hash host overlays add that existing production source to the test build and export the existing host steady-clock microsecond function. The production source files and iOS targets are unmodified. The real macOS host link now runs before long Mesa builds. Its isolated prefix omits only an unused Turnip existence guard and stops before smoke clients; the complete later build retains its genuine Turnip requirement. A successful preflight is only compile/link qualification, never GPU execution.

Additional CI files: host-check-turnip-darwin-host.py, host-gpu-service.cpp and host-link-preflight-prefix.py belong in ci/ alongside the previous helpers and fixtures.
