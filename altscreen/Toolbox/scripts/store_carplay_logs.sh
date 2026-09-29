#!/bin/sh
# Standalone GEM collection: runs from the updated Toolbox, never the installed
# AltScreen runtime. No INSTALL, restore, process restart or persistent verbose.
set -u
unset LD_PRELOAD
TESTING=${ALTSCREEN_CHAIN_TESTING:-0}
ROOT=""; VOLUME=""; LIMIT=1048576; TIMEOUT=4
if [ "$TESTING" = 1 ]; then
    ROOT=${ALTSCREEN_CHAIN_ROOT:-}; VOLUME=${ALTSCREEN_CHAIN_VOLUME:-}
    case "$ROOT:$VOLUME" in *'/../'*|*'/..:'*|*'/..') echo "FAIL: unsafe test paths"; exit 2 ;; esac
    case "$ROOT" in /tmp/*|/var/tmp/*) ;; *) echo "FAIL: invalid test root"; exit 2 ;; esac
    case "$VOLUME" in /tmp/*|/var/tmp/*) ;; *) echo "FAIL: invalid test volume"; exit 2 ;; esac
else
    PATH=/proc/boot:/bin:/usr/bin:/usr/sbin:/sbin:/armle/bin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
    export PATH
    # /tmp belongs to each node; collect from MMX even when GEM ran on RCC.
    if [ ! -d /mnt/app/eso/hmi/lsd ] && [ -d /net/mmx/mnt/app/eso/hmi/lsd ]; then
        exec on -f mmx /bin/sh "$0" "$@"
    fi
    [ -d /mnt/app/eso/hmi/lsd ] || { echo "FAIL: cannot identify MMX; no logs collected"; exit 1; }
    VOLUME=${ALTSCREEN_SD_VOLUME:-}
fi
MODE=${1:-collect}
case "$MODE" in collect|verbose-off) ;; *) echo "usage: store_carplay_logs.sh [collect|verbose-off]"; exit 2 ;; esac
if [ "$MODE" = verbose-off ]; then
    rm -f "$ROOT/tmp/carplay_verbose" || { echo "FAIL: cannot clear temporary verbose marker"; exit 1; }
    echo "CARPLAY_VERBOSE=OFF temporary_marker_removed=YES"
    if [ -e "$ROOT/mnt/app/carplay_verbose" ]; then
        echo "WARN: existing /mnt/app/carplay_verbose still enables verbose; persistent marker left unchanged"
    fi
    echo "Reconnect CarPlay to refresh the log level; saved logs are retained."
    exit 0
fi
if [ -z "$VOLUME" ]; then
    for candidate in /net/mmx/fs/sda0 /net/mmx/fs/sda1 /net/mmx/fs/sdb0 /net/mmx/fs/sdb1 /fs/sda0 /fs/sda1 /fs/sdb0 /fs/sdb1; do
        if [ -f "$candidate/Toolbox/scripts/store_carplay_logs.sh" ]; then VOLUME=$candidate; break; fi
    done
fi
[ -n "$VOLUME" ] && [ -d "$VOLUME/Toolbox" ] || { echo "FAIL: matching Toolbox SD not found"; exit 1; }
ensure_dirs() {
    for dir in "$@"; do
        [ -d "$dir" ] && [ ! -L "$dir" ] && continue
        [ ! -e "$dir" ] && [ ! -L "$dir" ] && mkdir -p "$dir" || return 1
    done
}
BASE="$VOLUME/MMI-Cockpit-Carplay/logs/rgi"
if ! ensure_dirs "$BASE"; then
    [ "$TESTING" != 1 ] && mount -uw "$VOLUME" 2>/dev/null
    ensure_dirs "$BASE" || { echo "FAIL: cannot create $BASE"; exit 1; }
fi
# Highest + 1, not the first free number; a removed older save stays removed.
last=0
for d in "$BASE"/collect_*; do
    [ -d "$d" ] || continue
    value=${d##*/collect_}
    case "$value" in ''|*[!0-9]*) continue ;; esac
    while :; do case "$value" in 0?*) value=${value#0} ;; *) break ;; esac; done
    [ "$value" -gt "$last" ] && last=$value
done
n=$((last + 1))
OUT="$BASE/collect_$n"
# mkdir (not -p) reserves the new directory, so parallel invocations never mix.
mkdir "$OUT" || { echo "FAIL: cannot reserve $OUT; retry STORE LOGS"; exit 1; }
ensure_dirs "$OUT/tmp" "$OUT/config" "$OUT/probes" || { echo "FAIL: incomplete save at $OUT"; exit 1; }
INFO="$OUT/info.txt"; WARNINGS=0
{
    echo "collection=$n"
    echo "date=$(date 2>&1)"
    echo "source_node=MMX"
    echo "verbose_before=$( [ -e "$ROOT/tmp/carplay_verbose" ] || [ -e "$ROOT/mnt/app/carplay_verbose" ] && echo on || echo off )"
    echo "log_tail_limit_bytes=$LIMIT"
    echo "probe_timeout_seconds=$TIMEOUT"
    echo "runtime_changed=NO restore=NO reboot=NO"
    echo "snapshot_is_live=YES logs_may_rotate_during_copy=YES"
} > "$INFO" || { echo "FAIL: cannot write $INFO"; exit 1; }
warning() { WARNINGS=$((WARNINGS + 1)); echo "WARN $*" >> "$INFO"; }
copy_log() {
    src=$1; dest=$2
    if [ ! -f "$src" ] || [ -L "$src" ]; then
        echo "SKIP missing_or_not_regular=$src" >> "$INFO"; return
    fi
    bytes=$(wc -c < "$src")
    [ "$bytes" -le "$LIMIT" ] || echo "TRUNCATED source=$src original_bytes=$bytes kept_tail=$LIMIT" >> "$INFO"
    if tail -c "$LIMIT" "$src" > "$dest.part" && mv "$dest.part" "$dest"; then
        echo "SAVED source=$src bytes=$(wc -c < "$dest")" >> "$INFO"
    else warning "copy_failed=$src partial_file_retained=YES"; fi
}
copy_small() {
    src=$1; dest=$2
    if [ ! -f "$src" ] || [ -L "$src" ]; then echo "SKIP missing_or_not_regular=$src" >> "$INFO"; return; fi
    bytes=$(wc -c < "$src")
    if [ "$bytes" -gt "$LIMIT" ]; then warning "oversize_metadata_skipped=$src bytes=$bytes"; return; fi
    if cp "$src" "$dest"; then echo "SAVED source=$src bytes=$bytes" >> "$INFO"; else warning "copy_failed=$src"; fi
}
# Explicit names only: no /tmp/*, /dev/shmem, images, firmware or core dumps.
for name in carplay_hook.log carplay_java.log maneuver_render.log carplay_wrapper.log \
            MMI-Cockpit-Carplay.altscreen_hook.log altscreen_hook.log MMI-Cockpit-Carplay.mirror.log; do
    for suffix in '' .1 .2 .3; do copy_log "$ROOT/tmp/$name$suffix" "$OUT/tmp/$name$suffix"; done
done
for name in mmi-mirror-basevideo.ready carplay_cluster.ctx cluster_geom.cfg \
            mmi-mirror-hmi.state carplay_supervisor.owner MMI-Cockpit-Carplay.mirror.pid \
            mmi-mirror-active carplay-video-position.used carplay-video-reset.request \
            carplay-video-reset.ack; do
    copy_small "$ROOT/tmp/$name" "$OUT/tmp/$name"
done
for name in cluster_ui.url cluster_fps; do copy_small "$ROOT/mnt/app/root/hooks/$name" "$OUT/config/$name"; done
for name in dio_manager.json smartphone_integrator.json; do
    copy_small "$ROOT/mnt/system/etc/eso/production/$name" "$OUT/config/$name"
done
copy_small "$VOLUME/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt" "$OUT/config/sd_build.txt"

# Stock probes can hang on QNX. Kill only the process started here, bound its
# output, and record failures rather than claiming an absent hook from no output.
probe() {
    name=$1; shift
    raw="$OUT/probes/$name.part"; timed="$OUT/probes/$name.timeout"
    "$@" > "$raw" 2>&1 & child=$!
    (
        tick=0
        while [ "$tick" -lt "$TIMEOUT" ]; do
            sleep 1
            kill -0 "$child" 2>/dev/null || exit 0
            tick=$((tick + 1))
            [ "$(wc -c < "$raw")" -le "$LIMIT" ] || break
        done
        echo "timeout_or_output_limit" > "$timed"
        kill "$child" 2>/dev/null || true
        sleep 1
        kill -9 "$child" 2>/dev/null || true
    ) & guard=$!
    wait "$child"; rc=$?
    kill "$guard" 2>/dev/null || true
    wait "$guard" 2>/dev/null || true
    if tail -c "$LIMIT" "$raw" > "$OUT/probes/$name"; then rm -f "$raw"; else warning "probe_save_failed=$name"; fi
    echo "PROBE name=$name exit=$rc bounded=$( [ -f "$timed" ] && echo stopped || echo completed )" >> "$INFO"
    [ "$rc" -eq 0 ] && [ ! -f "$timed" ] || warning "probe_incomplete=$name"
}
probe processes.txt pidin arguments
probe dio_libraries.txt pidin -p dio_manager libs
probe integrator_libraries.txt pidin -p smartphone_integrator libs
probe renderer_libraries.txt pidin -p maneuver_render libs
if : > "$ROOT/tmp/carplay_verbose"; then
    echo "verbose_after=on temporary_marker=/tmp/carplay_verbose" >> "$INFO"
else warning "cannot_enable_temporary_verbose"; fi
echo "warnings=$WARNINGS" >> "$INFO"
sync
echo "COLLECT_DIR=$OUT"
echo "STORE_LOGS=$( [ "$WARNINGS" -eq 0 ] && echo PASS || echo PASS_WITH_WARNINGS )"
echo "Logs saved. Verbose enabled in RAM; reconnect CarPlay, reproduce, then STORE LOGS again."
echo "Save one wired navigation session, then one wireless navigation session. Do not reboot between saves."
echo "Use CARPLAY VERBOSE OFF after diagnosis; no INSTALL or START is needed for collection."
[ "$WARNINGS" -eq 0 ]
