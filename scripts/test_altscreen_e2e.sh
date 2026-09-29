#!/bin/bash
#
# AltScreen + RGI SD package, end to end, in the AltScreen scripts' own testing mode:
# INSTALL -> START -> STATUS -> RESTORE ORIGINAL against a fake head-unit root.
#
#   FIXTURE=<card>/MMI-Cockpit-Carplay/backup ./scripts/test_altscreen_e2e.sh
#   HOST_TEST_IMAGE=mib2-rgi-host-tests:cn-p1002 FIXTURE=... ./scripts/test_altscreen_e2e.sh
#   FIXTURE_TRAIN=MHI2Q_CN_AUG22_P1002 SIMULATE_QNX_MKDIR=1 FIXTURE=... ./scripts/test_altscreen_e2e.sh
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
case "$SIMULATE_QNX_MKDIR" in 0|1) ;; *) echo 'ERROR: SIMULATE_QNX_MKDIR must be 0 or 1'; exit 2 ;; esac
[ -f "$SD_DIR/SHA256SUMS-SD.txt" ] || { echo "ERROR: no package in $SD_DIR; run ./scripts/build_sd.sh"; exit 1; }
[ -d "$FIXTURE/ORIGINAL/files" ] || { echo "ERROR: $FIXTURE has no ORIGINAL/files"; exit 1; }

docker run --rm --init -v "$SD_DIR":/sd:ro -v "$FIXTURE":/fixture:ro \
    -e "FIXTURE_TRAIN=${FIXTURE_TRAIN:-}" -e "SIMULATE_QNX_MKDIR=$SIMULATE_QNX_MKDIR" \
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
(cd /sd && sha256sum -c SHA256SUMS-SD.txt >/dev/null) || { echo "ERROR: SD manifest mismatch"; exit 1; }
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
echo "FIXTURE_TRAIN=$train SIMULATE_QNX_MKDIR=$SIMULATE_QNX_MKDIR"
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

run install ./install_mmi_cockpit_carplay_rx.sh
need install "INSTALL=PASS integrated=.*+RGI"
need install "RGI_COMPANION=PASS"
M=$ROOT/mnt/app/root/carplay-altscreen/bin/mirror
S=/sd/Toolbox/carplay_alt_screen/mirror_display/release
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

if [ "$fails" = 0 ]; then echo "AltScreen+RGI e2e: INSTALL/START/STATUS/RESTORE PASS"; else
    echo "AltScreen+RGI e2e: $fails FAILED"; for l in /tmp/*.log; do echo "----- $l"; tail -30 "$l"; done; exit 1; fi
'
