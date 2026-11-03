# UniXNU sheng OS17 GPU build

Builds the pinned public UniXNU GPU components for ordinary ARM64/iOS17 using a real macOS SDK and real 4KiB signatures. Apple original input is fetched temporarily for host checks and is not uploaded. Device data is never uploaded.

The complete host suite, additional QuartzCore/priming controls, reviewed Q cache-layout expectations and authenticated C6 host-component reuse remain required before iOS production. The one shared plugin-source correction uses steady_clock elapsed watchdog deadlines instead of counting sleep iterations; the original 17-second stall and watchdog verdict remain unchanged. Controlled A/B run41566142919 reproduced the original miss and passed the corrected gate. This does not prove physical GPU execution or fix tablet rendering by itself.

Outputs are candidate components only. Installation, device GPU execution and any reboot/flash/reset require separate review and user timing. No downloaded binary is automatically installed. The build preserves the original source pins and explicitly records all source overlays, including the watchdog header correction.
