#!/bin/sh
# CarPlay private111 Direct Display V2 INSTALL.
# Installs the type111 control/data plane, H264/decoded SHM bridge,
# displayable3 GLES sidecar, and Java80 HMI control plane.
# Window58 readback is not used by the sidecar. The mib2q-carplay-rgi companion
# (route guidance hook, RGI98 maneuver renderer) is installed next to it.
set -u

BASE="$0"
RESOLVED=$(command -v -- "$BASE" 2>/dev/null)
[ -n "$RESOLVED" ] || RESOLVED="$BASE"
SCRIPTDIR=$(cd -P -- "$(dirname -- "$RESOLVED")" 2>/dev/null && pwd -P)
[ -n "$SCRIPTDIR" ] || { echo "FAIL: cannot resolve installer directory"; exit 126; }

TESTING=${ALTSCREEN_CHAIN_TESTING:-0}
DEVICE_ROOT=""
VOLUME=""
if [ "$TESTING" = 1 ]; then
    VOLUME=${ALTSCREEN_CHAIN_VOLUME:-}
    DEVICE_ROOT=${ALTSCREEN_CHAIN_ROOT:-}
    [ -n "$VOLUME" ] || { echo "FAIL: testing volume missing"; exit 1; }
    case "$DEVICE_ROOT" in /tmp/*|/var/tmp/*) ;; *) echo "FAIL: invalid ALTSCREEN_CHAIN_ROOT"; exit 2 ;; esac
else
    for candidate in /net/mmx/fs/sda0 /net/mmx/fs/sda1 /net/mmx/fs/sdb0 /net/mmx/fs/sdb1 /fs/sda0 /fs/sda1 /fs/sdb0 /fs/sdb1; do
        if [ -s "$candidate/Toolbox/carplay_alt_screen/universal/libcarplay_altscreen.so" ] &&
           [ -s "$candidate/Toolbox/carplay_alt_screen/hmi/carplay_hook-basevideo3.jar" ]; then
            VOLUME=$candidate; break
        fi
    done
fi

[ -n "$VOLUME" ] || { echo "FAIL: no Toolbox SD card discovered"; exit 1; }
CONTROLLER="$VOLUME/Toolbox/scripts/altscreen_chain_test.sh"
RGI_COMPANION="$VOLUME/Toolbox/scripts/rgi_companion.sh"
CN_PREFLIGHT="$VOLUME/Toolbox/scripts/cn_migration_preflight.sh"
CN_TRANSACTION="$VOLUME/Toolbox/scripts/cn_upgrade_transaction.sh"
MIRROR_RELEASE="$VOLUME/Toolbox/carplay_alt_screen/mirror_display/release"
MIRROR_INFO="$MIRROR_RELEASE/BUILD_INFO.txt"
JAR_SOURCE="$VOLUME/Toolbox/carplay_alt_screen/hmi/carplay_hook-basevideo3.jar"
JAR_TARGET="$DEVICE_ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar"
JAR_TARGET_DIR=$(dirname -- "$JAR_TARGET")
EXPECTED_SIZE=@CARPLAY_JAR_SIZE@
EXPECTED_CKSUM=@CARPLAY_JAR_CKSUM@

[ -f "$CONTROLLER" ] || { echo "FAIL: chain controller missing: $CONTROLLER"; exit 127; }
[ -f "$RGI_COMPANION" ] || { echo "FAIL: RGI companion missing: $RGI_COMPANION"; exit 127; }
[ -s "$JAR_SOURCE" ] || { echo "FAIL: Java80 HMI JAR missing: $JAR_SOURCE"; exit 1; }
[ -s "$MIRROR_INFO" ] || { echo "FAIL: V2 Mirror BUILD_INFO missing: $MIRROR_INFO"; exit 1; }
[ -s "$MIRROR_RELEASE/logo.rgba" ] || { echo "FAIL: second-screen logo asset missing"; exit 1; }
[ -s "$MIRROR_RELEASE/watermark.rgba" ] || { echo "FAIL: watermark asset missing (kept as a placeholder, rendered fully transparent)"; exit 1; }
grep -Fq 'release_binary_status=PRIVATE111_DIRECT_DISPLAY_V2' "$MIRROR_INFO" 2>/dev/null &&
grep -Fq 'vehicle_zip_status=READY_FOR_VEHICLE_TEST' "$MIRROR_INFO" 2>/dev/null || {
    echo "FAIL: this package is not an approved rebuilt V2 vehicle release"
    grep -E '^(release_binary_status|vehicle_zip_status)=' "$MIRROR_INFO" 2>/dev/null || true
    echo "ACTION=REBUILD_QNX_SIDECAR_AND_PROMOTE_BEFORE_INSTALL"
    exit 1
}

file_size(){
    n=$(wc -c < "$1" 2>/dev/null) || { echo 0; return; }
    set -- $n
    echo "${1:-0}"
}
file_cksum(){
    if command -v cksum >/dev/null 2>&1; then
        cksum < "$1" 2>/dev/null | awk '{print $1}'
    else
        echo unavailable
    fi
}
jar_valid(){
    f=$1
    [ -s "$f" ] || return 1
    [ "$(file_size "$f")" = "$EXPECTED_SIZE" ] || return 1
    sum=$(file_cksum "$f")
    [ "$sum" = unavailable ] || [ "$sum" = "$EXPECTED_CKSUM" ] || return 1
}
mount_app_rw(){ [ "$TESTING" = 1 ] || mount -uw /mnt/app; }
mount_app_ro(){ [ "$TESTING" = 1 ] || mount -ur /mnt/app; }

jar_valid "$JAR_SOURCE" || {
    echo "FAIL: Java80 HMI JAR identity mismatch"
    echo "expected_size=$EXPECTED_SIZE expected_cksum=$EXPECTED_CKSUM"
    echo "actual_size=$(file_size "$JAR_SOURCE") actual_cksum=$(file_cksum "$JAR_SOURCE")"
    exit 1
}

# Recover an interrupted project upgrade before trying to identify its currently
# mixed files. Recovery restores the previous complete installation and stops.
CN_UPGRADE=0
CN_LOCK=""
CN_LOCK_HELD=0
if [ -f "$VOLUME/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt" ]; then
    [ -f "$CN_TRANSACTION" ] || { echo 'FAIL: CN upgrade transaction helper missing'; exit 1; }
    # Stock CN startup creates /ramdisk as qnx4. /tmp is /dev/shmem, whose
    # special files are outside the shell's regular-file noclobber guarantee.
    CN_LOCK="$DEVICE_ROOT/ramdisk/cn-rgi-install.lock"
    CN_LEGACY_LOCK="$DEVICE_ROOT/tmp/cn-rgi-install.lock"
    if [ -e "$CN_LEGACY_LOCK" ] || [ -L "$CN_LEGACY_LOCK" ]; then
        echo "FAIL: legacy CN install lock exists; preserved path=$CN_LEGACY_LOCK"
        echo 'ACTION=Full_MMI_reboot_then_retry_INSTALL'
        exit 1
    fi
    [ ! -L "$DEVICE_ROOT/ramdisk" ] || { echo 'FAIL: CN install lock parent is a symlink'; exit 1; }
    CN_LOCK_ID="owner=CN_RGI_INSTALL_V1 pid=$$"
    CN_LOCK_BYTES=$((${#CN_LOCK_ID}+1))
    cn_lock_exists(){ [ -e "$CN_LOCK" ] || [ -L "$CN_LOCK" ]; }
    cn_lock_read(){
        CN_LOCK_TEXT=""
        CN_LOCK_READ_BYTES=""
        [ ! -L "$CN_LOCK" ] && [ -f "$CN_LOCK" ] || return 1
        CN_LOCK_READ_BYTES=$(wc -c < "$CN_LOCK" 2>/dev/null) || return 1
        set -- $CN_LOCK_READ_BYTES
        [ "$#" -eq 1 ] || return 1
        CN_LOCK_READ_BYTES=$1
        case "$CN_LOCK_READ_BYTES" in ''|*[!0-9]*) return 1 ;; esac
        [ "${#CN_LOCK_READ_BYTES}" -le 3 ] && [ "$CN_LOCK_READ_BYTES" -le 128 ] || return 1
        CN_LOCK_TEXT=$(cat "$CN_LOCK" 2>/dev/null) || return 1
        # The byte count also rejects stripped NULs, extra trailing newlines,
        # and an incomplete record; command substitution alone cannot do that.
        [ "$CN_LOCK_READ_BYTES" = "$((${#CN_LOCK_TEXT}+1))" ]
    }
    cn_lock_refuse(){
        cn_lock_read || true
        # Another process may have created its lock but not written its owner yet.
        if [ "$CN_LOCK_READ_BYTES" = 0 ]; then sleep 1; fi
        if cn_lock_read; then
            case "$CN_LOCK_TEXT" in
                'owner=CN_RGI_INSTALL_V1 pid='*)
                    lock_pid=${CN_LOCK_TEXT#'owner=CN_RGI_INSTALL_V1 pid='}
                    case "$lock_pid" in
                        ''|*[!0-9]*|0|1) ;;
                        *)
                            if kill -0 "$lock_pid" 2>/dev/null; then
                                echo "FAIL: CN install already running pid=$lock_pid"
                                echo "CN_INSTALL_LOCK=PRESERVED path=$CN_LOCK"
                                return 1
                            fi
                            ;;
                    esac
                    ;;
            esac
        fi
        echo "FAIL: CN install lock exists with an unverified or inactive owner; preserved path=$CN_LOCK"
        echo 'ACTION=Full_MMI_reboot_then_retry_INSTALL'
        return 1
    }
    cn_exit(){
        cn_rc=$1
        trap - 0 HUP INT TERM
        if [ "$CN_UPGRADE" = 1 ]; then
            if [ -e "$DEVICE_ROOT/mnt/app/root/.cn-rgi-upgrade.pending" ]; then
                ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_TRANSACTION" rollback ||
                    echo 'FAIL: previous version recovery incomplete; retain SD and retry INSTALL'
            fi
            cn_rc=1
        fi
        if [ "$CN_LOCK_HELD" = 1 ]; then
            if cn_lock_read && [ "$CN_LOCK_TEXT" = "$CN_LOCK_ID" ] &&
               [ "$CN_LOCK_READ_BYTES" = "$CN_LOCK_BYTES" ]; then
                rm -f "$CN_LOCK" || { echo 'WARN: CN install lock release failed'; cn_rc=1; }
            else
                echo "WARN: CN install lock ownership changed; preserved path=$CN_LOCK"
                cn_rc=1
            fi
        fi
        exit "$cn_rc"
    }
    trap 'cn_exit $?' 0
    trap 'exit 1' HUP INT TERM
    if cn_lock_exists; then cn_lock_refuse; exit 1; fi
    # Noclobber supplies exclusive creation on the ordinary RAM filesystem.
    # Do not create the parent or fall back to the special /tmp namespace.
    if CN_LOCK_ERROR=$({
        trap - 0 HUP INT TERM
        umask 077
        set -C
        printf '%s\n' "$CN_LOCK_ID" > "$CN_LOCK"
    } 2>&1); then
        if cn_lock_read && [ "$CN_LOCK_TEXT" = "$CN_LOCK_ID" ] &&
           [ "$CN_LOCK_READ_BYTES" = "$CN_LOCK_BYTES" ]; then
            CN_LOCK_HELD=1
        else
            echo "FAIL: CN install lock owner verification failed; preserved path=$CN_LOCK"
            echo 'ACTION=Full_MMI_reboot_then_retry_INSTALL'
            exit 1
        fi
    else
        [ -z "$CN_LOCK_ERROR" ] || printf '%s\n' "$CN_LOCK_ERROR" >&2
        if cn_lock_exists; then cn_lock_refuse
        else echo "FAIL: CN install lock could not be created path=$CN_LOCK"; fi
        exit 1
    fi
    ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_TRANSACTION" recover
    recover_rc=$?
    [ "$recover_rc" = 0 ] || exit 1
fi

# Run before controller INSTALL: unknown/legacy owners still require RESTORE.
[ -f "$CN_PREFLIGHT" ] || { echo 'FAIL: CN migration preflight missing'; exit 1; }
ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_PREFLIGHT" || exit 1
ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$RGI_COMPANION" preflight || exit 1
if [ -n "$CN_LOCK" ] && ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_TRANSACTION" identify >/dev/null 2>&1; then
    ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CONTROLLER" restore-preflight || exit 1
    # Set the cleanup flag before begin: if publishing pending fails partway,
    # the exit trap can still restore the completed journal.
    CN_UPGRADE=1
    ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_TRANSACTION" begin || exit 1
    ALTSCREEN_CN_UPGRADE=1
    export ALTSCREEN_CN_UPGRADE
fi

echo "PACKAGE_MODE=CARPLAY_PRIVATE111_DIRECT_DISPLAY_V2"
echo "NATIVE_SOURCE=private111_ScreenStreamProcessData h264_shm=/carplay111_h264"
echo "DECODER_BACKEND=stock_omx_screen_linearized_shm decoded_shm=/carplay111_decoded"
echo "PIXEL_BRIDGE=Screen_linearized_NV12_to_existing_MMI_GLES"
echo "PIXEL_TARGET=displayable3"
echo "HMI_CONTEXT=ctx81 (nav without video: ctx80)"
echo "WINDOW58_READBACK=DISABLED"
echo "DIRECT_DISPLAY_SIDECAR=INCLUDED"
echo "RGI98_NATIVE_RENDERER=INCLUDED companion=mib2q-carplay-rgi"

ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CONTROLLER" install "${1:-}"
CHAIN_RC=$?
[ "$CHAIN_RC" -eq 0 ] || exit "$CHAIN_RC"

APP_RW=0
TMP="$JAR_TARGET.basevideo3.tmp"
rollback(){
    if [ "$CN_UPGRADE" = 1 ]; then
        [ "$APP_RW" != 1 ] || { mount_app_ro >/dev/null 2>&1 || true; APP_RW=0; }
        if ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_TRANSACTION" rollback; then CN_UPGRADE=0; fi
        return
    fi
    echo "WARN: Java80 deployment failed; removing deployed JAR and restoring native state"
    if [ "$APP_RW" != 1 ]; then
        if mount_app_rw >/dev/null 2>&1; then APP_RW=1; fi
    fi
    if [ "$APP_RW" = 1 ]; then
        rm -f "$TMP" "$JAR_TARGET" || echo "WARN: Java HMI JAR removal failed"
        sync >/dev/null 2>&1 || true
        mount_app_ro >/dev/null 2>&1 || true
        APP_RW=0
    fi
    ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$RGI_COMPANION" remove >/dev/null 2>&1 || echo "WARN: RGI companion removal failed"
    ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CONTROLLER" restore >/dev/null 2>&1 || echo "WARN: native rollback failed; runtime remains inert until RESTORE ORIGINAL succeeds"
}
fail(){ msg=$1; rollback; echo "FAIL: $msg" >&2; exit 1; }

MIRROR_RUNTIME="$DEVICE_ROOT/mnt/app/root/carplay-altscreen/bin/mirror"
[ -x "$MIRROR_RUNTIME/carplay-alt111-mirror-display" ] || fail "integrated direct-display binary was not staged"
[ -x "$MIRROR_RUNTIME/start_vehicle.sh" ] || fail "integrated direct-display launcher was not staged"
[ -s "$MIRROR_RUNTIME/logo.rgba" ] || fail "second-screen logo asset was not staged"
[ -s "$MIRROR_RUNTIME/watermark.rgba" ] || fail "watermark asset was not staged (kept as a placeholder, rendered fully transparent)"

mount_app_rw || fail "cannot mount /mnt/app writable"
APP_RW=1
[ -d "$JAR_TARGET_DIR" ] || mkdir -p "$JAR_TARGET_DIR" || fail "cannot create HMI JAR directory"
rm -f "$TMP" 2>/dev/null || true
cp "$JAR_SOURCE" "$TMP" || fail "cannot stage Java80 HMI JAR"
chmod 644 "$TMP" || fail "cannot chmod Java80 HMI JAR"
jar_valid "$TMP" || fail "staged Java80 HMI JAR identity check failed"
mv "$TMP" "$JAR_TARGET" || fail "cannot publish Java80 HMI JAR"
jar_valid "$JAR_TARGET" || fail "installed Java80 HMI JAR identity check failed"
sync || fail "sync failed after Java80 HMI install"
mount_app_ro || fail "cannot remount /mnt/app read-only"
APP_RW=0

echo "HMI_CONTROL_PLANE=INSTALLED target=/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar size=$EXPECTED_SIZE cksum=$EXPECTED_CKSUM"
echo "HMI_CONTRACT=RGI_SCREEN ctx81=98,101,102,3 ctx80=98,101,102,33 basevideo=3"

# Route guidance native half (hook + maneuver renderer + supervisor), wired into the
# carplay child next to the AltScreen preload.
ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$RGI_COMPANION" install || fail "RGI companion install failed"
if [ "$CN_UPGRADE" = 1 ]; then
    ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$CN_TRANSACTION" commit || fail "CN upgrade commit failed"
    CN_UPGRADE=0
fi
echo "INSTALL=PASS integrated=AltScreen+H264Tap+DecoderTap+Displayable3+Java80+RGI reboot_required=YES"
exit 0
