# CN P1002 native build and retained AMap geometry

This profile targets the owner's `MHI2Q_CN_AUG22_P1002`. The repository's RGI,
cover-art and AltScreen command modules remain the upstream implementation;
there is one command owner and no parallel `libcn_carplay_zoom_v30.so` bridge.
Cross-compilation and the checks below do **not** certify the combined package
on a vehicle. The generated native manifest records `vehicle_validated=false`.

## Build inputs and provenance

`scripts/build_hook.sh` and `scripts/build_renderers.sh` accept `QNX_IMAGE`.
Both resolve it to an immutable Docker image ID, disable the container network,
mount source read-only and allow writes only under ignored `build/`. Target
binaries are inspected, never executed on the host.

```sh
QNX_IMAGE=qnx65-armv7-toolchain:latest bash scripts/build_hook.sh
QNX_IMAGE=qnx65-armv7-toolchain:latest bash scripts/build_renderers.sh
python3 tools/verify_cn_native.py --stock-dir /private/cn-p1002-originals
```

The full hook is C; the maneuver scene engine requires a C++11 frontend and
standard headers. A previously cached **C-only** QNX compiler can build the
hook but cannot build this renderer. The renderer links through the C driver
and rejects C++ runtime imports rather than shipping another libstdc++.
The local build used the pinned QNX compiler source at
`luka-dev/qnx65-armv7-toolchain` commit
`baa45224f18ae6b13c2e9c77c6663bb8181eb6a1`, GCC 8.5, ARMv7-A/VFPv3-D16/softfp,
and added the C++ frontend plus generated target headers to the existing
C/libgcc recipe. OEM files, SDK and toolchain outputs are private build inputs,
not repository contents.

`build/native-evidence/cn-native-build.json` records the actual hook/renderer
SHA256, image identities, CN factory hashes and static check results. Package
staging must check this manifest against the binary files it copies. Missing or
failed verification is not a completed native build.

## CN ABI evidence and remaining limits

The exact original AirPlay, NmeSDK and NmeBaseClasses files are identified by
SHA256 in `tools/verify_cn_native.py`; only their identities and symbol contracts
are recorded. All seven hook interposers exist in these originals, as do the
CF dictionary/string functions, callback tables and session command sender.

The prior CN factory disassembly established that `CinemoCreateIAP` writes an
owned `ICinemoIAP*` to the first output pointer. The CN exported wrappers dispatch
AddRef/Release through vtable offsets 0/4 and `SendIAP2` through offset 0x3c,
preserving its four-word `(this, session, bytes, length)` ABI. The concrete
receiver retains its internal send object under a mutex, releases the mutex,
sends and releases that retained reference. These are the conventions used by
the upstream RGI worker; they do not prove phone RGD support or eliminate every
disconnect timing race. Original evidence remains in the owner's private
`cn-integration-v23/cn-nme-audit-20260928` directory.

The output gates require ELF32 ARM EABI5, the baseline soft-float calling ABI,
exact hook exports, no TLS/emutls/TEXTREL/dynamic R_ARM_REL32 and no dynamic C++
runtime. The hook initializer must be only the compiler's `frame_dummy`.
Renderer linking uses the upstream screen/EGL/GLES import-stub convention;
actual CN BSP loading, displayable 98 and context 80/81 composition still need
vehicle validation. No factory library is replaced by these builds.

## Retained, narrow binary overlay

`tools/patch_cn_altscreen.py INPUT OUTPUT` accepts the exact checked-in universal
AltScreen hook or its known FPS-patched variant. It replays only these previously
vehicle-tested changes:

* For a 1440×542 type-111 cluster display, advertise `safeArea={x:480,y:0,w:480,h:542}`.
  The full view area, video dimensions, main display and splash pixels are unchanged.
  Other types and dimensions retain their original full safe area.
* Keep emitting repeated phone-request markers, instead of returning early when
  the cached request flag is unchanged. This does not synthesize phone requests.

For the upstream-layout comparison, CN packages now default to `CN_MAP_SAFEAREA=0`.
The patcher's `--safe-area off` restores the full original safe-area code and both
call sites, while retaining only the repeated-phone-request change and the selected
FPS instruction. `CN_MAP_SAFEAREA=1` restores the previous geometry byte-for-byte.
`CN_P1002_BUILD.txt` records the selected mode and exact AltScreen library hash.
This switch does not change the JAR, RGI hook, renderer, or splash assets.

After normalizing the one FPS instruction, the entire output SHA256 must equal
the pinned hash for its mode: the vehicle-tested v21 hook when on, or the upstream
hook with only the phone-marker instruction changed when off.
Unknown or partly modified inputs fail closed. Applying the tool twice is safe.

Our 324-byte Thumb payload is supplied as assembly and text hex, not as an OEM
binary. `tools/cn_p1002/verify_payload.py` independently reassembles it with
`llvm-mc` and resolves the seven explicit ARM/Thumb calls. A full original library
is never embedded in that source.

```sh
python3 -m unittest discover -s tests -p test_cn_altscreen.py -v
LLVM_MC=/path/to/llvm-mc python3 tools/cn_p1002/verify_payload.py
python3 tools/patch_cn_altscreen.py \
  altscreen/Toolbox/carplay_alt_screen/universal/libcarplay_altscreen.so \
  build/native-evidence/libcarplay_altscreen-cn.so
# Requires the host-only unicorn and pyelftools packages:
python3 tests/cn_safearea_emulation.py
```

The byte-level geometry test exercises 280 native calls at two relocation bases,
including 172 allocation-failure cases, original CF helpers, reference cleanup,
existing-display updates and nonmatching dimensions. CF adapter endpoints are
stubbed; it does not simulate iOS, AMap or rendering. `CN_HOOK_UNDER_TEST` can
select the staged FPS+CN binary for the same test.

`bash scripts/test_maneuver_native.sh` also runs the upstream lane-wire receiver,
production C/C++ scene/path/transition logic and loopback FIN/RST disconnect tests
with AddressSanitizer and UndefinedBehaviorSanitizer. On Linux it needs standard
Khronos GLES2 headers (Ubuntu package `libgles2-mesa-dev`); unused graphics/platform
symbols are linked to aborting stubs, so the test cannot silently pretend to draw.
The CPU test uses the original preview code path; the QNX target is separately
cross-compiled and audited above. This test does not validate GPU output.

## New upstream mirror and FPS

The profile keeps the upstream mirror paired with upstream Java readiness
handling. The old v19 one-byte mirror patch is **not** transplanted at its old
address: this is a different ELF, and the new `AltScreenVideo.isReady()` checks
the active/ready marker files rather than the old custom marker-mode logic.
The old custom Sport pixel translation is also not a native patch here; layout
ownership belongs to the new Java/context implementation.

The CN overlay composes with the upstream 30 FPS patch and preserves its exact
instruction. The mirror still uses the upstream 4 ms empty-poll / 16.7 ms minimum
loop settings when that patch is enabled. These settings and the new combined
renderer/context workload have **not** been measured on this CN vehicle.
`ALTSCREEN_FULL_FPS=0` selects the unchanged upstream polling/readback schedule
for comparison. The old successful wired zoom result does not prove that the new
bus route is vehicle-validated, and this migration does not claim to fix JYBOX-29
wireless zoom or audio stutter.
