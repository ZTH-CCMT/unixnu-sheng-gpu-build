# UniXNU OS17 GPU component build plan

This is a reviewable, **not yet remotely executed** workflow. It builds candidate user-space GPU components; it does not boot or install them.

## Files and placement

Copy `unixnu-gpu-only.yml` to `.github/workflows/unixnu-gpu-only.yml` in the approved dedicated repository, and copy `build_gpu_only.py` plus `verify_gpu_artifacts.py` to `ci/`. The repository needs no device secret. The manual dispatch has no free-form shell, source-ref, seed, or signing-key input.

No repository has been created, no files uploaded, and no workflow triggered by this plan.

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

A provisional planning allowance is30–90minutes, up to the120minute cap. This has not run; first source downloads, Rust LTO and runner queueing can change it. Qualification on the standard small ARM64 runner's available RAM remains unknown. Repository visibility, account allowance and billing must be approved separately; this plan promises no private-runner free quota.

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

Existing official Actions research found no current exact sheng GPU component artifact to download. The only old successful macOS run reviewed was for uke; current sheng package workflow had no runs. This dedicated workflow therefore remains an unexecuted route, not a repackaged verified author binary.
