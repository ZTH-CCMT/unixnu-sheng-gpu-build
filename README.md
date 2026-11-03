# UniXNU sheng OS17 GPU build

Builds the pinned public UniXNU GPU components for ordinary ARM64/iOS17 using a real macOS SDK and real 4KiB signatures. Apple original input is fetched temporarily for host checks and is not uploaded. Device data is never uploaded.

The complete host suite, additional QuartzCore/priming controls, reviewed Q cache-layout expectations and authenticated C6 host-component reuse remain required before iOS production. The one shared plugin-source correction uses steady_clock elapsed watchdog deadlines instead of counting sleep iterations; the original 17-second stall and watchdog verdict remain unchanged. Controlled A/B run41566142919 reproduced the original miss and passed the corrected gate. This does not prove physical GPU execution or fix tablet rendering by itself.

Outputs are candidate components only. Installation, device GPU execution and any reboot/flash/reset require separate review and user timing. No downloaded binary is automatically installed. The build preserves the original source pins and explicitly records all source overlays, including the watchdog header correction.

The complete fixed GopFramebuffer submodule is now initialized for both NativeGOPWire and NativeHalfCodes headers. Previously compiled ordinary ARM64/iOS17 Turnip and bridge inputs are reused only after fixed v6 run/artifact/hash/target checks; final plugin and probe daemon are genuinely compiled and signed in this run. No Cargo/Mesa fallback is hidden, and reused libraries are explicitly marked not rebuilt.

The OS27-only patchFramebufferBranch helper receives the standard C++17 [[maybe_unused]] annotation, because its sole arm64e call is excluded from OS17. No warning option, Werror, function body or runtime call site is changed. The exact before/after source hashes and this compatibility change are recorded in the candidate manifest.

Published-device initialization currently reports Vulkan error -3 on the physical tablet. This diagnostic revision preserves the same failure result and successful path, and only exposes the existing Rust warning sink through bounded PW rows when diagnostics are enabled. The warning can be empty or stale and is not itself a proven root cause. Existing raw iOS Turnip and bridge archives are reused with exact authentication; final plugin and daemon compile/sign and complete host controls remain. No device deployment is automatic.

The existing warning snapshot is displayed immediately on the failure path, split through a finite best-effort PW sequence, and retained as a bounded PWlast summary; empty snapshots append Wempty to the original PUB refusal. No new IOKit retain, open, close, native worker thread or initialization retry is introduced.
