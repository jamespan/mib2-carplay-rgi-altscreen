#!/bin/bash
#
# Build the complete MMI-Cockpit-Carplay SD card: AltScreen (CarPlay video on the VC)
# with route guidance from this repo.
#
#   STOCK_JAR=MU1329-base.jar ./scripts/build_sd.sh              # build all, stage build/sd/
#   SKIP_BUILD=1 ./scripts/build_sd.sh                           # reuse build/ artifacts
#   SD=/Volumes/SD32 STOCK_JAR=MU1329-base.jar ./scripts/build_sd.sh   # also sync onto the card
#   ALTSCREEN_FULL_FPS=0 ./scripts/build_sd.sh                   # stock AltScreen video binaries (15 fps)
#   CN_PROFILE=1 PRIVATE_LOGO_DIR=local_assets/mixed16 ...        # CN P1002 + private random splash pool
#
# Inputs:  altscreen/   the AltScreen SD tree (scripts, mirror sidecar, universal preload,
#                       GEM menu, MIB2 Toolbox) with @CARPLAY_JAR_SIZE@/@CARPLAY_JAR_CKSUM@
#                       placeholders where its scripts pin the HMI JAR identity
#          build/       carplay_hook.jar, libcarplay_hook.so, maneuver_render (built here)
#          deploy/      the RGI wrapper/supervisor scripts; deploy/altscreen/carplay_child.json
# Output:  build/sd/    copy its contents onto the SD root
#
# The card's MMI-Cockpit-Carplay/ (AltScreen stock backups, logs, state) is never part of
# the output and never touched by SD=: RESTORE ORIGINAL needs the backups on that card.
set -euo pipefail
export COPYFILE_DISABLE=1   # macOS tar: no AppleDouble ._ files on the FAT card

[ "$#" -eq 0 ] || { echo "usage: [STOCK_JAR=<jar>] [SKIP_BUILD=1] [SD=<card>] ./scripts/build_sd.sh"; exit 2; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$PROJECT_DIR/altscreen"
OUT="${OUT:-$PROJECT_DIR/build/sd}"
JAR="$PROJECT_DIR/build/carplay_hook.jar"
RGI_DIR=Toolbox/carplay_alt_screen/rgi
JAR_DEST=Toolbox/carplay_alt_screen/hmi/carplay_hook-basevideo3.jar
PINNED_SCRIPTS="install_mmi_cockpit_carplay_rx.sh start_mmi_cockpit_carplay_rx_test.sh status_mmi_cockpit_carplay_test.sh"
case "${CN_PROFILE:-0}" in 0|1) ;; *) echo 'ERROR: CN_PROFILE must be 0 or 1'; exit 2 ;; esac
CN_PACKAGE_FINISHED=0
cn_build_exit(){
    result=$?
    if [ "${CN_PROFILE:-0}" = 1 ] && [ "$CN_PACKAGE_FINISHED" != 1 ] &&
       [ -f "$OUT/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt" ]; then
        printf '%s\n' 'target_train=MHI2Q_CN_AUG22_P1002' 'build_status=INCOMPLETE' \
            > "$OUT/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt"
    fi
    return "$result"
}
trap cn_build_exit EXIT

[ -d "$SRC/Toolbox" ] || { echo "ERROR: $SRC is not an AltScreen SD tree"; exit 1; }

if [ "${SKIP_BUILD:-0}" != 1 ]; then
    STOCK_JAR="${STOCK_JAR:-}" bash "$PROJECT_DIR/scripts/build_java.sh"
    bash "$PROJECT_DIR/scripts/build_hook.sh"
    bash "$PROJECT_DIR/scripts/build_renderers.sh"
    if [ "${CN_PROFILE:-0}" = 1 ]; then
        python3 "$PROJECT_DIR/tools/audit_cn_java.py" --stock "${STOCK_JAR:?CN build requires STOCK_JAR}" \
            --java "${CN_JAVA:-java}" --javac "${CN_JAVAC:-javac}"
        if [ -n "${CN_LLVM_BIN:-}" ]; then
            python3 "$PROJECT_DIR/tools/verify_cn_native.py" --stock-dir "${CN_STOCK_DIR:?CN build requires CN_STOCK_DIR}" --llvm-bin "$CN_LLVM_BIN"
        else
            python3 "$PROJECT_DIR/tools/verify_cn_native.py" --stock-dir "${CN_STOCK_DIR:?CN build requires CN_STOCK_DIR}"
        fi
    fi
fi
for f in "$JAR" "$PROJECT_DIR/build/libcarplay_hook.so" "$PROJECT_DIR/build/maneuver_render"; do
    [ -s "$f" ] || { echo "ERROR: missing build artifact $f"; exit 1; }
done

echo "=== MMI-Cockpit-Carplay SD (AltScreen + RGI) -> $OUT ==="
case "$OUT" in "$PROJECT_DIR"/build/*) rm -rf "$OUT" ;; *) [ ! -e "$OUT" ] || { echo "ERROR: $OUT exists; remove it or use a path under build/"; exit 1; } ;; esac
mkdir -p "$OUT"
(cd "$SRC" && tar --exclude=.DS_Store --exclude='._*' -cf - .) | (cd "$OUT" && tar -xf -)
rm -f "$OUT/SHA256SUMS-SD.list"
if [ "${CN_PROFILE:-0}" = 1 ]; then
    printf '%s\n' 'target_train=MHI2Q_CN_AUG22_P1002' 'build_status=INCOMPLETE' \
        > "$OUT/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt"
fi

# AltScreen reads back only every second decoded cluster frame and its mirror sidecar
# polls every 20 ms with a fixed 33 ms period (30 fps in, 15-22 fps on the VC);
# tools/patch_altscreen_fps.py fixes both binaries.
ALTS_LIB=Toolbox/carplay_alt_screen/universal/libcarplay_altscreen.so
ALTS_MIRROR_DIR=Toolbox/carplay_alt_screen/mirror_display/release
if [ "${ALTSCREEN_FULL_FPS:-1}" = 1 ]; then
    for f in "$ALTS_LIB" "$ALTS_MIRROR_DIR/carplay-alt111-mirror-display"; do
        python3 "$PROJECT_DIR/tools/patch_altscreen_fps.py" "$SRC/$f" "$OUT/$f" >/dev/null
    done
    # Keep the sidecar's own checksum list true to what ships.
    if command -v sha256sum >/dev/null 2>&1; then MSHA="sha256sum"; else MSHA="shasum -a 256"; fi
    new_sum=$(cd "$OUT/$ALTS_MIRROR_DIR" && $MSHA carplay-alt111-mirror-display | cut -d' ' -f1)
    sed -e "s/^[0-9a-f]\{64\}  carplay-alt111-mirror-display\$/$new_sum  carplay-alt111-mirror-display/" \
        "$OUT/$ALTS_MIRROR_DIR/SHA256SUMS" > "$OUT/$ALTS_MIRROR_DIR/SHA256SUMS.tmp"
    mv "$OUT/$ALTS_MIRROR_DIR/SHA256SUMS.tmp" "$OUT/$ALTS_MIRROR_DIR/SHA256SUMS"
    (cd "$OUT/$ALTS_MIRROR_DIR" && $MSHA -c SHA256SUMS >/dev/null) \
        || { echo "ERROR: mirror SHA256SUMS does not match the patched sidecar"; exit 1; }
    ALTS_FPS="30 fps (every frame read back, 4 ms sidecar poll)"
else
    ALTS_FPS="stock (15 fps)"
fi

if [ "${CN_PROFILE:-0}" = 1 ]; then
    # Reapply only the car-verified CN geometry/phone-request changes to the
    # upstream universal hook. The patcher preserves the selected FPS mode.
    python3 "$PROJECT_DIR/tools/patch_cn_altscreen.py" "$OUT/$ALTS_LIB" "$OUT/$ALTS_LIB"
fi

if [ -n "${PRIVATE_LOGO_DIR:-}" ]; then
    python3 "$PROJECT_DIR/tools/stage_private_logos.py" \
        --source "$PRIVATE_LOGO_DIR" --release "$OUT/$ALTS_MIRROR_DIR" \
        > "$PROJECT_DIR/build/private-logo-stage.json"
fi

# RGI native half, installed by Toolbox/scripts/rgi_companion.sh from AltScreen INSTALL.
mkdir -p "$OUT/$RGI_DIR"
cp "$PROJECT_DIR/build/libcarplay_hook.so" "$PROJECT_DIR/build/maneuver_render" \
   "$PROJECT_DIR/maneuver_render/resources/flag_atlas.rgba" \
   "$PROJECT_DIR/deploy/smartphone_integrator/carplay_startup.sh" \
   "$PROJECT_DIR/deploy/smartphone_integrator/carplay_monitor.sh" \
   "$PROJECT_DIR/deploy/smartphone_integrator/carplay_processes.sh" \
   "$PROJECT_DIR/deploy/smartphone_integrator/carplay_cleanup.sh" \
   "$PROJECT_DIR/deploy/altscreen/carplay_child.json" "$OUT/$RGI_DIR/"
chmod 755 "$OUT/$RGI_DIR"/*.sh "$OUT/$RGI_DIR/maneuver_render" "$OUT/$RGI_DIR/libcarplay_hook.so"

# The one HMI JAR (RGI Java + the AltScreen ctx-81 video context). AltScreen's INSTALL,
# START and STATUS refuse any JAR whose POSIX cksum/size differ from the pinned pair.
mkdir -p "$(dirname "$OUT/$JAR_DEST")"
cp "$JAR" "$OUT/$JAR_DEST"
set -- $(cksum < "$JAR")
JAR_CKSUM=$1 JAR_SIZE=$2
for s in $PINNED_SCRIPTS; do
    f="$OUT/Toolbox/scripts/$s"
    grep -q '^EXPECTED_SIZE=@CARPLAY_JAR_SIZE@$' "$f" && grep -q '^EXPECTED_CKSUM=@CARPLAY_JAR_CKSUM@$' "$f" \
        || { echo "ERROR: $s lost its JAR identity placeholders"; exit 1; }
    sed -e "s/@CARPLAY_JAR_SIZE@/$JAR_SIZE/" -e "s/@CARPLAY_JAR_CKSUM@/$JAR_CKSUM/" "$f" > "$f.tmp"
    mv "$f.tmp" "$f"; chmod 755 "$f"
done
if grep -rl '@CARPLAY_JAR_' "$OUT/Toolbox" >/dev/null; then
    echo "ERROR: unresolved JAR placeholders:"; grep -rl '@CARPLAY_JAR_' "$OUT/Toolbox"; exit 1
fi

if [ "${CN_PROFILE:-0}" = 1 ]; then
    python3 "$PROJECT_DIR/tools/stage_cn_profile.py" --build "$PROJECT_DIR/build" --sd "$OUT"
fi

# Everything the head unit runs must parse as sh (QNX /bin/sh is pdksh).
for f in "$OUT"/Toolbox/scripts/*.sh "$OUT/$RGI_DIR"/*.sh "$OUT"/Toolbox/carplay_alt_screen/mirror_display/release/*.sh; do
    sh -n "$f" || { echo "ERROR: shell syntax: $f"; exit 1; }
done

# SD integrity list (sha256sum -c SHA256SUMS-SD.txt on the card).
if command -v sha256sum >/dev/null 2>&1; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
# Verify the maintained required-file list, then include every staged file so
# optional local assets and generated profile metadata cannot escape readback.
while IFS= read -r f; do
    [ -z "$f" ] || [ -f "$OUT/$f" ] || { echo "ERROR: required file missing: $f" >&2; exit 1; }
done < "$SRC/SHA256SUMS-SD.list"
python3 - "$OUT" "${CN_PROFILE:-0}" <<'PY'
import hashlib, pathlib, sys
out = pathlib.Path(sys.argv[1])
if sys.argv[2] == "1":
    profile = out / "Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt"
    text = profile.read_text()
    if "build_status=VERIFIED_PENDING_PACKAGE\n" not in text:
        raise SystemExit("ERROR: CN profile has not passed build evidence checks")
    profile.write_text(text.replace("build_status=VERIFIED_PENDING_PACKAGE\n", "build_status=PASS\n"))
manifest = out / "SHA256SUMS-SD.txt"
files = sorted(p for p in out.rglob("*") if p.is_file() and p != manifest)
manifest.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}\n" for p in files))
PY
(cd "$OUT" && $SHA -c SHA256SUMS-SD.txt >/dev/null)
CN_PACKAGE_FINISHED=1

echo "  jar: $JAR_DEST size=$JAR_SIZE cksum=$JAR_CKSUM"
echo "  altscreen video: $ALTS_FPS"
echo "  rgi: $RGI_DIR ($(ls "$OUT/$RGI_DIR" | wc -l | tr -d ' ') files)"
echo "  sums: SHA256SUMS-SD.txt ($(wc -l < "$OUT/SHA256SUMS-SD.txt" | tr -d ' ') files, verified)"

if [ -n "${SD:-}" ]; then
    [ -d "$SD" ] || { echo "ERROR: SD=$SD is not a directory"; exit 1; }
    [ -d "$SD/MMI-Cockpit-Carplay" ] || echo "WARN: $SD has no MMI-Cockpit-Carplay/ (no AltScreen stock backups on this card yet)"
    echo "=== sync -> $SD (MMI-Cockpit-Carplay/ untouched, nothing deleted) ==="
    STAMP="$PROJECT_DIR/build/.sd-sync-stamp"; : > "$STAMP"
    (cd "$OUT" && tar -cf - .) | (cd "$SD" && tar -xf -)
    # macOS stores new files' xattrs as AppleDouble ._* on FAT; drop the ones this copy made.
    find "$SD" -path "$SD/MMI-Cockpit-Carplay" -prune -o -type f -name '._*' -newer "$STAMP" -exec rm -f {} + 2>/dev/null || true
    rm -f "$STAMP"
    sync
    (cd "$SD" && $SHA -c SHA256SUMS-SD.txt >/dev/null) && echo "  card verified against SHA256SUMS-SD.txt"
fi
echo "Done. Next on the car: Toolbox -> Update Toolbox, then MMI-Cockpit-Carplay -> INSTALL, reboot, START, reboot."
