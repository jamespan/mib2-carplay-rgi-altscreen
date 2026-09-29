#!/bin/sh
# Foreign CN installations require a clean migration. Identified releases of
# this project can use the installer's complete previous-version transaction.
# This check is read-only and runs before the AltScreen controller mutates files.
set -u
VOLUME=${ALTSCREEN_SD_VOLUME:-${ALTSCREEN_CHAIN_VOLUME:-}}
[ -n "$VOLUME" ] || { echo 'CN_PREFLIGHT=FAIL missing_volume'; exit 1; }
PROFILE="$VOLUME/Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt"
[ -f "$PROFILE" ] || exit 0
ROOT=""
if [ "${ALTSCREEN_CHAIN_TESTING:-0}" = 1 ]; then
    ROOT=${ALTSCREEN_CHAIN_ROOT:-}
    case "$ROOT" in /tmp/*|/var/tmp/*) ;; *) echo 'CN_PREFLIGHT=FAIL invalid_test_root'; exit 1 ;; esac
fi
fail(){ echo "CN_PREFLIGHT=FAIL $1"; exit 1; }
grep -qx 'target_train=MHI2Q_CN_AUG22_P1002' "$PROFILE" || fail invalid_build_profile
grep -qx 'build_status=PASS' "$PROFILE" || fail incomplete_build
train=""
for rel in /net/rcc/dev/shmem/version.txt /dev/shmem/version.txt /net/mmx/dev/shmem/version.txt; do
    [ -r "$ROOT$rel" ] || continue
    train=$(sed -n '/Current train/p' "$ROOT$rel" | head -n 1)
    [ -z "$train" ] || break
done
printf '%s\n' "$train" | grep -Eq '(^|[^A-Za-z0-9_])MHI2Q_CN_AUG22_P1002([^A-Za-z0-9_]|$)' ||
    fail "firmware_mismatch expected=MHI2Q_CN_AUG22_P1002 actual=$train"
JAR="$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar"
NAVIGNORE="$ROOT/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar"
if [ -e "$NAVIGNORE" ] || [ -L "$NAVIGNORE" ]; then
    echo 'ACTION=Uninstall_the_separate_NavActiveIgnore_patch_then_full_MMI_reboot_before_INSTALL'
    fail conflicting_NavActiveIgnore_jar
fi
RUNTIME="$ROOT/mnt/app/root/carplay-altscreen"
CFG="$ROOT/mnt/system/etc/eso/production/smartphone_integrator.json"
[ -f "$CFG" ] || fail missing_smartphone_integrator_config
# Only the project-specific transaction can make the upstream ORIGINAL rollback
# safe for an upgrade. Keep rejecting unknown JARs and legacy zoom owners.
if [ -e "$JAR" ] || [ -L "$JAR" ] || [ -e "$RUNTIME" ] ||
   grep -Eq 'libcn_carplay_|libcarplay_hook[.]so|carplay_startup[.]sh' "$CFG"; then
    UPGRADE="$VOLUME/Toolbox/scripts/cn_upgrade_transaction.sh"
    if [ -f "$UPGRADE" ] && ALTSCREEN_SD_VOLUME="$VOLUME" /bin/sh "$UPGRADE" identify; then
        echo 'CN_PREFLIGHT=PASS train=MHI2Q_CN_AUG22_P1002 inplace_upgrade=YES'
        exit 0
    fi
    echo 'ACTION=Use_the_installed_previous_package_RESTORE_ORIGINAL_then_full_MMI_reboot_before_INSTALL'
    fail previous_custom_installation_present
fi
for name in libcarplay_hook.so maneuver_render flag_atlas.rgba carplay_startup.sh carplay_monitor.sh carplay_processes.sh carplay_cleanup.sh; do
    p="$ROOT/mnt/app/root/hooks/$name"
    [ ! -e "$p" ] && [ ! -L "$p" ] || fail "existing_hook_file=$name"
done
echo 'CN_PREFLIGHT=PASS train=MHI2Q_CN_AUG22_P1002 clean_install=YES'
