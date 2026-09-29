#!/bin/bash
#
# AltScreen + RGI SD package, end to end, in the AltScreen scripts' own testing mode:
# INSTALL -> START -> STATUS -> RESTORE ORIGINAL against a fake head-unit root.
#
#   FIXTURE=<card>/MMI-Cockpit-Carplay/backup ./scripts/test_altscreen_e2e.sh
#   HOST_TEST_IMAGE=mib2-rgi-host-tests:cn-p1002 FIXTURE=... ./scripts/test_altscreen_e2e.sh
#   FIXTURE_TRAIN=MHI2Q_CN_AUG22_P1002 SIMULATE_QNX_MKDIR=1 FIXTURE=... ./scripts/test_altscreen_e2e.sh
#   PRIOR_SD_DIR=<previous-release>/SD-Overlay FIXTURE=... ./scripts/test_altscreen_e2e.sh
#
# FIXTURE is an AltScreen stock backup from a real unit (ORIGINAL/files, firewall-original,
# boot-diagnostics); it holds that unit's dio_manager, libairplay, JSON configs and
# startup.sh, so it stays outside the repo. The package is build/sd (./scripts/build_sd.sh).
#
# Runs in Linux with mksh as /bin/sh: QNX /bin/sh is pdksh (dash rejects the stock
# startup.sh), and on macOS the /tmp symlink breaks AltScreen's runtime-forward check.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SD_DIR="${SD_DIR:-$PROJECT_DIR/build/sd}"
FIXTURE="${FIXTURE:?set FIXTURE=<card>/MMI-Cockpit-Carplay/backup}"
HOST_TEST_IMAGE="${HOST_TEST_IMAGE:-eclipse-temurin:8-jdk-jammy}"
SIMULATE_QNX_MKDIR="${SIMULATE_QNX_MKDIR:-1}"
SIMULATE_QNX_CKSUM="${SIMULATE_QNX_CKSUM:-1}"
PRIOR_SD_DIR="${PRIOR_SD_DIR:-}"
DOCKER_MOUNTS=(-v "$SD_DIR:/sd:ro" -v "$FIXTURE:/fixture:ro")
if [ -n "$PRIOR_SD_DIR" ]; then
    [ -f "$PRIOR_SD_DIR/SHA256SUMS-SD.txt" ] || { echo "ERROR: previous release is not an SD package: $PRIOR_SD_DIR"; exit 1; }
    DOCKER_MOUNTS+=(-v "$PRIOR_SD_DIR:/sd-prior:ro")
fi
case "$SIMULATE_QNX_MKDIR" in 0|1) ;; *) echo 'ERROR: SIMULATE_QNX_MKDIR must be 0 or 1'; exit 2 ;; esac
case "$SIMULATE_QNX_CKSUM" in 0|1) ;; *) echo 'ERROR: SIMULATE_QNX_CKSUM must be 0 or 1'; exit 2 ;; esac
[ -f "$SD_DIR/SHA256SUMS-SD.txt" ] || { echo "ERROR: no package in $SD_DIR; run ./scripts/build_sd.sh"; exit 1; }
[ -d "$FIXTURE/ORIGINAL/files" ] || { echo "ERROR: $FIXTURE has no ORIGINAL/files"; exit 1; }

docker run --rm --init "${DOCKER_MOUNTS[@]}" \
    -e "FIXTURE_TRAIN=${FIXTURE_TRAIN:-}" -e "SIMULATE_QNX_MKDIR=$SIMULATE_QNX_MKDIR" -e "SIMULATE_QNX_CKSUM=$SIMULATE_QNX_CKSUM" \
    "$HOST_TEST_IMAGE" bash -c '
set -u
if ! command -v mksh >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq mksh >/dev/null 2>&1 || { echo "ERROR: cannot install mksh"; exit 1; }
fi
ln -sf /bin/mksh /bin/sh
if [ "$SIMULATE_QNX_MKDIR" = 1 ]; then
    # The CN head unit returned EEXIST for mkdir -p on an existing final path.
    # Reproduce that behavior only inside this disposable container.
    mv /bin/mkdir /bin/mkdir.real
    cat > /bin/mkdir <<EOF_QNX_MKDIR
#!/bin/sh
if [ "\$#" -eq 2 ] && [ "\$1" = -p ] && [ -d "\$2" ]; then
    echo "mkdir: File exists: \$2" >&2
    exit 1
fi
exec /bin/mkdir.real "\$@"
EOF_QNX_MKDIR
    chmod 755 /bin/mkdir
fi
if [ "$SIMULATE_QNX_CKSUM" = 1 ]; then
    # Real CN files record stdin as e.g. "1364422823      75725 STDIN".
    # Preserve the exit code even if a caller subsequently normalizes columns.
    mv /usr/bin/cksum /usr/bin/cksum.real
    cat > /usr/bin/cksum <<EOF_QNX_CKSUM
#!/bin/sh
[ "\${ALTSCREEN_TEST_CKSUM_FAILURE:-0}" != 1 ] || exit 71
if [ "\$#" = 0 ]; then
    answer=\$(/usr/bin/cksum.real) || exit \$?
    set -- \$answer
    printf "%s      %s STDIN\\n" "\$1" "\$2"
else
    exec /usr/bin/cksum.real "\$@"
fi
EOF_QNX_CKSUM
    chmod 755 /usr/bin/cksum
fi
(cd /sd && sha256sum -c SHA256SUMS-SD.txt >/dev/null) || { echo "ERROR: SD manifest mismatch"; exit 1; }
if [ -d /sd-prior ]; then
    (cd /sd-prior && sha256sum -c SHA256SUMS-SD.txt >/dev/null) || { echo "ERROR: previous SD manifest mismatch"; exit 1; }
fi
F=/fixture/ORIGINAL/files; VOL=/tmp/vol; ROOT=/tmp/root
mkdir -p $VOL; (cd /sd && tar -cf - .) | (cd $VOL && tar -xf -)
mkdir -p $ROOT/eso/bin/apps $ROOT/eso/lib $ROOT/armle/usr/lib $ROOT/mnt/system/etc/eso/production \
         $ROOT/mnt/system/etc/boot $ROOT/mnt/app/root $ROOT/mnt/app/eso/hmi/lsd/jars $ROOT/dev/shmem $ROOT/tmp
cp $F/_eso_bin_apps_dio_manager $ROOT/eso/bin/apps/dio_manager
cp $F/_eso_lib_libairplay.so $ROOT/eso/lib/libairplay.so
cp $F/_armle_usr_lib_libNmeBaseClasses.so $ROOT/armle/usr/lib/libNmeBaseClasses.so
P=$ROOT/mnt/system/etc/eso/production
cp $F/_mnt_system_etc_eso_production_smartphone_integrator.json $P/smartphone_integrator.json
cp $F/_mnt_system_etc_eso_production_dio_manager.json $P/dio_manager.json
cp /fixture/firewall-original/pf.conf $ROOT/mnt/system/etc/pf.conf
cp /fixture/boot-diagnostics/startup.sh $ROOT/mnt/system/etc/boot/startup.sh
train=${FIXTURE_TRAIN:-}
if [ -z "$train" ]; then
    if [ -f /sd/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt ]; then
        train=MHI2Q_CN_AUG22_P1002
    else
        train=MHI2Q_ER_AUG22_FIXTURE
    fi
fi
echo "Current train = $train" > $ROOT/dev/shmem/version.txt
echo "FIXTURE_TRAIN=$train SIMULATE_QNX_MKDIR=$SIMULATE_QNX_MKDIR SIMULATE_QNX_CKSUM=$SIMULATE_QNX_CKSUM"
cp $P/dio_manager.json /tmp/dio.orig; cp $P/smartphone_integrator.json /tmp/si.orig
export ALTSCREEN_CHAIN_TESTING=1 ALTSCREEN_CHAIN_ROOT=$ROOT ALTSCREEN_CHAIN_VOLUME=$VOL
cd $VOL/Toolbox/scripts
fails=0
need(){ grep -q "$2" /tmp/$1.log && echo "  ok   $1: $2" || { echo "  FAIL $1: missing $2"; fails=$((fails+1)); }; }
run(){
    timeout 180 /bin/sh "$2" > /tmp/$1.log 2>&1
    rc=$?; echo "== $1 rc=$rc"
    if [ "$rc" != "${3:-0}" ]; then
        echo "  FAIL $1: exit $rc, expected ${3:-0}"
        fails=$((fails+1))
    fi
}

txn(){
    timeout 180 /bin/sh ./cn_upgrade_transaction.sh "$2" > /tmp/$1.log 2>&1
    rc=$?; echo "== $1 rc=$rc"
    if [ "$rc" != "${3:-0}" ]; then
        echo "  FAIL $1: exit $rc, expected ${3:-0}"; fails=$((fails+1))
    fi
}

# Prove the CN gate executes before controller mutation, then remove our own
# sentinel and proceed with a clean install. Nothing is written to /fixture.
if [ -f /sd/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt ]; then
    J=$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar
    echo previous-custom-sentinel > "$J"
    cp "$J" /tmp/previous-custom.jar
    run refused_install ./install_mmi_cockpit_carplay_rx.sh 1
    need refused_install "CN_PREFLIGHT=FAIL previous_custom_installation_present"
    cmp -s "$J" /tmp/previous-custom.jar && cmp -s /tmp/si.orig $P/smartphone_integrator.json &&
        cmp -s /tmp/dio.orig $P/dio_manager.json && [ ! -e "$ROOT/mnt/app/root/carplay-altscreen" ] \
        && echo "  ok   migration: previous installation refused before mutation" \
        || { echo "  FAIL migration: refused install mutated previous state"; fails=$((fails+1)); }
    rm -f "$J"
fi

# Fail after the RGI smartphone-integrator child has been published. Alter only
# the disposable card copy, then prove the outer installer restores ORIGINAL
# and removes this attempted installation before the subsequent successful run.
cp ./rgi_companion.sh /tmp/rgi-companion.original
sed "s/^patch_dio(){/patch_dio(){ return 91;/" /tmp/rgi-companion.original > ./rgi_companion.sh
run rollback_install ./install_mmi_cockpit_carplay_rx.sh 1
need rollback_install "FAIL: RGI companion install failed"
cmp -s /tmp/si.orig $P/smartphone_integrator.json && cmp -s /tmp/dio.orig $P/dio_manager.json &&
    [ ! -e "$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar" ] &&
    [ ! -e "$ROOT/mnt/app/root/hooks" ] && [ ! -e "$ROOT/mnt/app/root/carplay-altscreen" ] \
    && echo "  ok   rollback: late RGI failure restores JSON and removes new JAR/hooks/runtime" \
    || { echo "  FAIL rollback: previous JSON or new installation leftovers"; fails=$((fails+1)); }
cp /tmp/rgi-companion.original ./rgi_companion.sh

# Install an actual previous release when supplied. Both package trees are mounted
# read-only; their files are overlaid only onto the disposable card copy. Existing
# backups/state stay in place, just like Update Toolbox followed by INSTALL.
INITIAL_SD=/sd
if [ -d /sd-prior ]; then
    INITIAL_SD=/sd-prior
    (cd "$INITIAL_SD" && tar -cf - .) | (cd "$VOL" && tar -xf -)
    echo "UPGRADE_BASE=HISTORICAL_RELEASE"
else
    echo "UPGRADE_BASE=CURRENT_RELEASE (set PRIOR_SD_DIR for historical upgrade coverage)"
fi
run install ./install_mmi_cockpit_carplay_rx.sh
need install "INSTALL=PASS integrated=.*+RGI"
need install "RGI_COMPANION=PASS"
M=$ROOT/mnt/app/root/carplay-altscreen/bin/mirror
S=$INITIAL_SD/Toolbox/carplay_alt_screen/mirror_display/release
cmp -s "$S/select_logo.sh" "$M/select_logo.sh" \
    && echo "  ok   install: splash selector staged exactly" \
    || { echo "  FAIL install: splash selector missing or changed"; fails=$((fails+1)); }
if [ -f "$S/logo_pool.count" ]; then
    count=$(cat "$S/logo_pool.count"); i=1
    cmp -s "$S/logo_pool.count" "$M/logo_pool.count" || { echo "  FAIL install: private splash pool count"; fails=$((fails+1)); }
    while [ "$i" -le "$count" ]; do
        cmp -s "$S/logo_$i.rgba" "$M/logo_$i.rgba" \
            || { echo "  FAIL install: private splash logo_$i.rgba"; fails=$((fails+1)); }
        i=$((i+1))
    done
    echo "  checked install: $count private splash images byte-for-byte"
fi
grep -q "\"CARPLAY_PRELOAD_EXTRA=/mnt/app/root/carplay-altscreen/lib/libcarplay_altscreen.so\"" $P/smartphone_integrator.json \
    && echo "  ok   install: CARPLAY_PRELOAD_EXTRA in carplay child" || { echo "  FAIL install: CARPLAY_PRELOAD_EXTRA"; fails=$((fails+1)); }
H=$ROOT/mnt/app/root/hooks
sed -n "/^INHERITED_PRELOAD=/,/^echo \"\\[startup\\] preload/p" $H/carplay_startup.sh > /tmp/pre.sh
got=$(env -u LD_PRELOAD CARPLAY_PRELOAD_EXTRA=/mnt/app/root/carplay-altscreen/lib/libcarplay_altscreen.so H=/mnt/app/root/hooks WLOG=/dev/null /bin/sh -c ". /tmp/pre.sh; echo \$LD_PRELOAD")
[ "$got" = /mnt/app/root/carplay-altscreen/lib/libcarplay_altscreen.so:/mnt/app/root/hooks/libcarplay_hook.so ] \
    && echo "  ok   wrapper: dio_manager preload $got" || { echo "  FAIL wrapper preload: $got"; fails=$((fails+1)); }

# Snapshot every persistent device file, mode, and link, plus the SD state; this
# catches a rollback which silently replaces the working project with ORIGINAL.
# Use Python only on the host. The production installer remains QNX shell-only.
cat > /tmp/persistent-snapshot.py <<EOF_SNAPSHOT
import hashlib, json, os, stat, sys
from pathlib import Path
out = {}
for label, raw in (("device", "/tmp/root/mnt"), ("state", "/tmp/vol/MMI-Cockpit-Carplay/state")):
    base = Path(raw)
    if not base.exists():
        continue
    for p in sorted(base.rglob("*")):
        if p.name == ".chain_test.lock":
            continue
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode):
            value = ["symlink", os.readlink(p)]
        elif stat.S_ISREG(st.st_mode):
            value = ["file", stat.S_IMODE(st.st_mode), hashlib.sha256(p.read_bytes()).hexdigest()]
        else:
            continue
        out[label + "/" + str(p.relative_to(base))] = value
print(json.dumps(out, indent=2, sort_keys=True))
EOF_SNAPSHOT
snapshot(){ python3 /tmp/persistent-snapshot.py > "$1"; }
backup_snapshot(){
    (cd "$VOL/MMI-Cockpit-Carplay/backup" && find original firewall-original universal-hook-original boot-diagnostics -type f -print0 | sort -z | xargs -0 sha256sum) > "$1"
}
check_same(){
    if cmp -s "$1" "$2"; then echo "  ok   $3"; else
        echo "  FAIL $3"; diff -u "$1" "$2" | head -80; fails=$((fails+1))
    fi
}

if [ -f /sd/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt ]; then
    echo topaligned > "$H/cluster_ui.url"
    echo 30 > "$H/cluster_fps"
    # These existing launch flags are settings for the next reboot, not live host
    # processes. An upgrade must retain them while requiring a reboot to load JAR.
    RS=$ROOT/mnt/app/root/carplay-altscreen/state
    for marker in ACTIVE ARMED ARMED_IAP2; do touch "$RS/$marker"; done
    echo prior-working-run > "$RS/run_id"
    echo user-kept-file > "$H/unrelated-user-file"
    snapshot /tmp/before-upgrade.json
    backup_snapshot /tmp/original-before.sha256
    cp "$H/cluster_ui.url" /tmp/ui.before
    cp "$H/cluster_fps" /tmp/fps.before
    cp "$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar" /tmp/prior-installed.jar

    (cd /sd && tar -cf - .) | (cd "$VOL" && tar -xf -)
    if [ "$SIMULATE_QNX_CKSUM" = 1 ]; then
        export ALTSCREEN_TEST_CKSUM_FAILURE=1
        txn checksum_failure identify 1
        unset ALTSCREEN_TEST_CKSUM_FAILURE
        snapshot /tmp/after-cksum-failure.json
        check_same /tmp/before-upgrade.json /tmp/after-cksum-failure.json "failed checksum refuses upgrade without modifying live files"
    fi

    # Reject another live INSTALL before it can open an upgrade transaction.
    mkdir "$ROOT/tmp/cn-rgi-install.lock"
    echo $$ > "$ROOT/tmp/cn-rgi-install.lock/pid"
    run concurrent_upgrade ./install_mmi_cockpit_carplay_rx.sh 1
    need concurrent_upgrade "CN install already running"
    snapshot /tmp/after-lock-refusal.json
    check_same /tmp/before-upgrade.json /tmp/after-lock-refusal.json "concurrent INSTALL rejected without changing installed files"
    rm "$ROOT/tmp/cn-rgi-install.lock/pid"; rmdir "$ROOT/tmp/cn-rgi-install.lock"

    # Model FAT: stored files acquire 0777, but explicit original modes must
    # restore 0644 JAR/config and 0755 scripts. This starts with the true v1
    # wrapper, whose old code did not yet know the outer pending marker.
    txn prepare_fat begin
    need prepare_fat "CN_UPGRADE=PREPARED"
    mkdir /tmp/cn-fake-stock
    cat > /tmp/cn-fake-stock/dio_manager <<EOF_STOCK
#!/bin/sh
[ -z "\${LD_PRELOAD:-}" ] && [ -z "\${CARPLAY_PRELOAD_EXTRA:-}" ] || exit 43
[ "\${1:-}" = guard-argument ] || exit 44
echo PENDING_GUARD=STOCK_ONLY_PRELOAD_CLEARED
EOF_STOCK
    chmod 755 /tmp/cn-fake-stock/dio_manager
    H="$H" DIODIR=/tmp/cn-fake-stock LD_PRELOAD=/tmp/absent-fixture-preload.so CARPLAY_PRELOAD_EXTRA=fixture-extra \
        /bin/sh "$H/carplay_startup.sh" guard-argument > /tmp/pending_wrapper.log 2>&1
    rc=$?
    [ "$rc" = 0 ] || { echo "  FAIL pending wrapper: exit $rc"; fails=$((fails+1)); }
    need pending_wrapper "PENDING_GUARD=STOCK_ONLY_PRELOAD_CLEARED"
    JOURNAL=$VOL/MMI-Cockpit-Carplay/upgrade-current
    chmod -R 777 "$JOURNAL/data"
    txn rollback_fat rollback
    need rollback_fat "CN_UPGRADE=ROLLED_BACK"
    snapshot /tmp/after-fat-rollback.json
    check_same /tmp/before-upgrade.json /tmp/after-fat-rollback.json "FAT rollback: bytes, permissions, and previous state restored"
    cp -R "$JOURNAL" /tmp/journal-valid-a

    # Create a second valid complete snapshot with different data. Restoring
    # snapshot A while the head-unit pending token belongs to B must fail closed.
    echo distinct-prior-user-file > "$H/unrelated-user-file"
    snapshot /tmp/before-interrupted-upgrade.json
    txn prepare_interrupted begin
    cp -R "$JOURNAL" /tmp/journal-valid-b
    rm -rf "$JOURNAL"; cp -R /tmp/journal-valid-a "$JOURNAL"
    snapshot /tmp/before-wrong-snapshot.json
    txn wrong_snapshot rollback 1
    need wrong_snapshot "pending_snapshot_mismatch"
    snapshot /tmp/after-wrong-snapshot.json
    check_same /tmp/before-wrong-snapshot.json /tmp/after-wrong-snapshot.json "different complete journal rejected before modifying live files"
    rm -rf "$JOURNAL"; cp -R /tmp/journal-valid-b "$JOURNAL"
    echo interrupted-new-jar > "$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar"
    run recover_interrupted ./install_mmi_cockpit_carplay_rx.sh 1
    need recover_interrupted "CN_UPGRADE=ROLLED_BACK"
    need recover_interrupted "Full_MMI_reboot_then_retry_INSTALL"
    snapshot /tmp/after-interrupted-recovery.json
    check_same /tmp/before-interrupted-upgrade.json /tmp/after-interrupted-recovery.json "interrupted INSTALL recovers matching previous version and stops for reboot"
    echo user-kept-file > "$H/unrelated-user-file"

    cp ./rgi_companion.sh /tmp/rgi-companion.upgrade
    sed "s/^patch_dio(){/patch_dio(){ return 91;/" /tmp/rgi-companion.upgrade > ./rgi_companion.sh
    run failed_upgrade ./install_mmi_cockpit_carplay_rx.sh 1
    need failed_upgrade "CN_PREFLIGHT=PASS.*inplace_upgrade=YES"
    need failed_upgrade "FAIL: RGI companion install failed"
    snapshot /tmp/after-failed-upgrade.json
    check_same /tmp/before-upgrade.json /tmp/after-failed-upgrade.json "upgrade rollback: all previous persistent files/modes/state restored"
    backup_snapshot /tmp/original-after-failure.sha256
    check_same /tmp/original-before.sha256 /tmp/original-after-failure.sha256 "upgrade rollback: ORIGINAL remains unchanged"
    cmp -s /tmp/prior-installed.jar "$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar" &&
        grep -q "carplay_startup.sh" "$P/smartphone_integrator.json" \
        && echo "  ok   upgrade rollback: working JAR and RGI wrapper survive" \
        || { echo "  FAIL upgrade rollback: working project replaced by factory state"; fails=$((fails+1)); }
    cp /tmp/rgi-companion.upgrade ./rgi_companion.sh

    run upgrade ./install_mmi_cockpit_carplay_rx.sh
    need upgrade "CN_PREFLIGHT=PASS.*inplace_upgrade=YES"
    need upgrade "INSTALL=PASS integrated=.*+RGI"
    cmp -s /sd/Toolbox/carplay_alt_screen/hmi/carplay_hook-basevideo3.jar "$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar" \
        && echo "  ok   upgrade: new JAR published exactly" \
        || { echo "  FAIL upgrade: incorrect JAR"; fails=$((fails+1)); }
    check_same /tmp/ui.before "$H/cluster_ui.url" "upgrade: chosen map layout preserved"
    check_same /tmp/fps.before "$H/cluster_fps" "upgrade: chosen refresh rate preserved"
    [ -f "$RS/ACTIVE" ] && [ -f "$RS/ARMED" ] && [ -f "$RS/ARMED_IAP2" ] &&
        [ "$(cat "$RS/run_id")" = prior-working-run ] && [ -f "$H/unrelated-user-file" ] \
        && echo "  ok   upgrade: launch settings and unrelated file preserved" \
        || { echo "  FAIL upgrade: previous settings lost"; fails=$((fails+1)); }
    backup_snapshot /tmp/original-after-upgrade.sha256
    check_same /tmp/original-before.sha256 /tmp/original-after-upgrade.sha256 "upgrade: ORIGINAL remains unchanged"

    run reinstall ./install_mmi_cockpit_carplay_rx.sh
    need reinstall "CN_PREFLIGHT=PASS.*inplace_upgrade=YES"
    need reinstall "INSTALL=PASS integrated=.*+RGI"
    check_same /tmp/ui.before "$H/cluster_ui.url" "same-version reinstall: layout preserved"
    backup_snapshot /tmp/original-after-reinstall.sha256
    check_same /tmp/original-before.sha256 /tmp/original-after-reinstall.sha256 "same-version reinstall: ORIGINAL remains unchanged"
    # The later restore assertion expects only this project-owned directory.
    rm "$H/unrelated-user-file"
fi

# The ARM/QNX sidecar cannot execute on this host. Exercise the installed launch
# scripts with their explicit binary override, without altering the real binary
# staged above. All sidecar markers remain inside the disposable fake root.
cat > /tmp/fake-mirror <<EOF_FAKE_MIRROR
#!/bin/sh
trap "exit 0" TERM INT
while :; do sleep 1; done
EOF_FAKE_MIRROR
chmod 755 /tmp/fake-mirror
export ALT111_MIRROR_BIN=/tmp/fake-mirror ALT111_MIRROR_TMP_ROOT=$ROOT/tmp
export ALT111_JAVA_BASE_READY_FILE=$ROOT/tmp/mmi-mirror-basevideo.ready
export ALT111_MIRROR_ACTIVE_FILE=$ROOT/tmp/mmi-mirror-active
echo "SIDECAR_EXECUTION=HOST_FIXTURE (real ARM/QNX payload is installed but not executed)"
run start ./start_mmi_cockpit_carplay_rx_test.sh
need start "^START=PASS integrated="

run status ./status_mmi_cockpit_carplay_test.sh
need status "HMI_CONTROL_PLANE=PASS"
need status "UNIVERSAL_PRELOAD_CONFIG=ARMED"
need status "RGI_NATIVE=INSTALLED"
need status "RGI_SI_CHILD=WRAPPER"
need status "RGI_DIO_IDS=5/5"

run restore ./stop_mmi_cockpit_carplay_test.sh
need restore "RGI_NATIVE=REMOVED"
need restore "RESTORE=PASS integrated"
[ ! -e $H ] && [ ! -e $ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar ] \
    && echo "  ok   restore: hooks and JAR removed" || { echo "  FAIL restore: files left"; fails=$((fails+1)); }
cmp -s /tmp/dio.orig $P/dio_manager.json && cmp -s /tmp/si.orig $P/smartphone_integrator.json \
    && echo "  ok   restore: both JSON configs byte-identical to ORIGINAL" || { echo "  FAIL restore: JSON differs"; fails=$((fails+1)); }

if [ "$fails" = 0 ]; then echo "AltScreen+RGI e2e: INSTALL/UPGRADE/ROLLBACK/REINSTALL/START/STATUS/RESTORE PASS"; else
    echo "AltScreen+RGI e2e: $fails FAILED"; for l in /tmp/*.log; do echo "----- $l"; tail -30 "$l"; done; exit 1; fi
'
