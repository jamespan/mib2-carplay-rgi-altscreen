#!/bin/sh
# Outer transaction for an identified CN installation. The upstream controller's
# inner rollback restores ORIGINAL; this journal restores the installed version.
# Journal paths are fixed below and journal content is data, never shell code.
set -u
VOLUME=${ALTSCREEN_SD_VOLUME:-${ALTSCREEN_CHAIN_VOLUME:-}}
[ -n "$VOLUME" ] || { echo 'CN_UPGRADE=FAIL missing_volume'; exit 1; }
ROOT=""
if [ "${ALTSCREEN_CHAIN_TESTING:-0}" = 1 ]; then
    ROOT=${ALTSCREEN_CHAIN_ROOT:-}
    case "$ROOT" in /tmp/*|/var/tmp/*) ;; *) exit 2 ;; esac
fi
RUNTIME="$ROOT/mnt/app/root/carplay-altscreen"
HOOKS="$ROOT/mnt/app/root/hooks"
STATE="$VOLUME/MMI-Cockpit-Carplay/state"
JOURNAL="$VOLUME/MMI-Cockpit-Carplay/upgrade-current"
PENDING="$ROOT/mnt/app/root/.cn-rgi-upgrade.pending"
OWNER=cn-p1002-project-upgrade-v1
mount_rw(){ [ "${ALTSCREEN_CHAIN_TESTING:-0}" = 1 ] || mount -uw "$1"; }
mount_ro(){ [ "${ALTSCREEN_CHAIN_TESTING:-0}" = 1 ] || mount -ur "$1"; }
ensure_dir(){ [ -d "$1" ] || mkdir -p "$1"; }
# QNX cksum pads columns and labels redirected input STDIN. Normalize only this
# helper's identities/journal; do not alter existing ORIGINAL backup checksums.
pair(){
    pair_out=$(cksum < "$1" 2>/dev/null) || return 1
    set -- $pair_out
    case "${1:-}" in ''|*[!0-9]*) return 1 ;; esac
    case "${2:-}" in ''|*[!0-9]*) return 1 ;; esac
    printf '%s %s\n' "$1" "$2"
}
fail(){ echo "CN_UPGRADE=FAIL $1" >&2; return 1; }

# These are the CN port's released binary identities, including the already
# installed v1 which predates upgrade receipts. A runtime owner alone is not an
# identity check. POSIX cksum is provided by the vehicle; SHA tooling is not.
identify(){
    [ -d "$RUNTIME" ] && [ ! -L "$RUNTIME" ] || return 1
    [ ! -e "$ROOT/mnt/app/root/.carplay-altscreen.previous" ] || return 1
    [ ! -e "$RUNTIME/state/transaction.pending" ] || return 1
    [ ! -e "$RUNTIME/state/start.pending" ] || return 1
    grep -qx 'owner=MMI-Cockpit-Carplay' "$RUNTIME/.mmi-cockpit-carplay-runtime-owner" 2>/dev/null || return 1
    grep -qx 'runtime=carplay-altscreen' "$RUNTIME/.mmi-cockpit-carplay-runtime-owner" 2>/dev/null || return 1
    grep -qx 'owner=MMI-Cockpit-Carplay' "$RUNTIME/bin/mirror/.mmi-cockpit-carplay-mirror-owner" 2>/dev/null || return 1
    grep -qx 'mode=carplay-private111-direct-display-v2' "$RUNTIME/bin/mirror/.mmi-cockpit-carplay-mirror-owner" 2>/dev/null || return 1
    [ -f "$STATE/INSTALLED" ] && grep -qx UNIVERSAL "$STATE/firmware_profile.txt" || return 1
    [ -f "$VOLUME/MMI-Cockpit-Carplay/backup/original/COMPLETE" ] || return 1
    [ ! -e "$STATE/RESTORE_PENDING_REBOOT" ] || return 1
    jar="$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar"
    [ -f "$jar" ] && [ ! -L "$jar" ] || return 1
    case "$(pair "$jar")" in '3113048449 254994'|'2924861228 257836'|'1345467403 257879') ;; *) return 1 ;; esac
    case "$(pair "$RUNTIME/lib/libcarplay_altscreen.so")" in
        '978087763 251880'|'3113190410 251880') ;; *) return 1 ;; esac
    [ "$(pair "$HOOKS/libcarplay_hook.so")" = '4153509008 299838' ] || return 1
    [ "$(pair "$HOOKS/maneuver_render")" = '1859543356 177373' ] || return 1
    case "$(pair "$RUNTIME/bin/mirror/carplay-alt111-mirror-display")" in
        '4054744997 51906'|'1892739126 51906') ;; *) return 1 ;; esac
    # The manifest is an additional package lineage marker, not a substitute for
    # checking the installed native binary above. Logos are intentionally free.
    case "$(pair "$RUNTIME/bin/mirror/SHA256SUMS")" in
        '3634299304 2089'|'3417166920 669'|'3090093779 669'|'1749508425 669') ;; *)
        # A later package may carry new artwork while retaining the same code.
        cmp -s "$RUNTIME/bin/mirror/SHA256SUMS" "$VOLUME/Toolbox/carplay_alt_screen/mirror_display/release/SHA256SUMS" || return 1 ;;
    esac
    cfg="$ROOT/mnt/system/etc/eso/production/smartphone_integrator.json"
    grep -q '"exec": "carplay_startup.sh"' "$cfg" || return 1
    grep -q 'CARPLAY_PRELOAD_EXTRA=/mnt/app/root/carplay-altscreen/lib/libcarplay_altscreen.so' "$cfg" || return 1
    grep -Eq 'libcn_carplay_|libcp_mirror[.]so|/root/hooks/libcarplay_altscreen' "$cfg" && return 1
    for old in "$HOOKS"/libcn_carplay_* "$HOOKS"/libcp_mirror.so "$HOOKS"/libcarplay_altscreen.so; do
        [ ! -e "$old" ] && [ ! -L "$old" ] || return 1
    done
    [ ! -e "$ROOT/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] || return 1
    echo 'CN_UPGRADE_IDENTITY=PASS project=CN_P1002 known_binary_set=YES'
}

# Fixed slots prevent a corrupted SD journal from naming arbitrary destinations.
slots(){ echo 'runtime hooks jar si dio firewall startup_mnt startup_etc state lib_target stock_dio stock_dio_app stock_airplay stock_nme_arm stock_nme_app stock_nme_eso'; }
path_for(){
    case "$1" in
        runtime) echo "$RUNTIME" ;;
        hooks) echo "$HOOKS" ;;
        jar) echo "$ROOT/mnt/app/eso/hmi/lsd/jars/carplay_hook.jar" ;;
        si) echo "$ROOT/mnt/system/etc/eso/production/smartphone_integrator.json" ;;
        dio) echo "$ROOT/mnt/system/etc/eso/production/dio_manager.json" ;;
        firewall) echo "$ROOT/mnt/system/etc/pf.conf" ;;
        startup_mnt) echo "$ROOT/mnt/system/etc/boot/startup.sh" ;;
        startup_etc) echo "$ROOT/etc/boot/startup.sh" ;;
        state) echo "$STATE" ;;
        lib_target) echo "$ROOT/mnt/app/root/lib-target" ;;
        stock_dio) echo "$ROOT/eso/bin/apps/dio_manager" ;;
        stock_dio_app) echo "$ROOT/mnt/app/eso/bin/apps/dio_manager" ;;
        stock_airplay) echo "$ROOT/eso/lib/libairplay.so" ;;
        stock_nme_arm) echo "$ROOT/armle/usr/lib/libNmeBaseClasses.so" ;;
        stock_nme_app) echo "$ROOT/mnt/app/armle/usr/lib/libNmeBaseClasses.so" ;;
        stock_nme_eso) echo "$ROOT/eso/lib/libNmeBaseClasses.so" ;;
        *) return 1 ;;
    esac
}
# cksum over every regular file plus the directory names. All install-owned
# trees must be ordinary files/directories; do not follow symlinks into the car.
mode_of(){
    LC_ALL=C ls -ld "$1" | awk '
        { p=substr($1,1,10); if(length(p)!=10) exit 1; special=0; mode="";
          for(g=0;g<3;g++){ n=0; a=substr(p,2+3*g,1); b=substr(p,3+3*g,1); c=substr(p,4+3*g,1);
            if(a=="r")n+=4;else if(a!="-")exit 1;
            if(b=="w")n+=2;else if(b!="-")exit 1;
            if(c=="x"||c=="s"||c=="t")n+=1;
            else if(c!="-"&&c!="S"&&c!="T")exit 1;
            if(c=="s"||c=="S")special+=(g==0?4:2);
            if(c=="t"||c=="T")special+=1;
            mode=mode n;
          } print special mode; }'
}
tree_manifest() (
    cd "$1" || exit 1
    lists="$ROOT/tmp/cn-rgi-tree-list.$$"
    trap 'rm -f "$lists" "$lists.sorted"' 0
    find . -print > "$lists" || exit 1
    LC_ALL=C sort "$lists" > "$lists.sorted" || exit 1
    while IFS= read -r item; do
        [ ! -L "$item" ] || exit 1
        if [ -d "$item" ]; then printf 'directory %s\n' "$item"; continue; fi
        [ -f "$item" ] || exit 1
        sum=$(cksum < "$item") || exit 1
        printf '%s %s\n' "$sum" "$item"
    done < "$lists.sorted"
)
tree_modes() (
    cd "$1" || exit 1
    lists="$ROOT/tmp/cn-rgi-mode-list.$$"
    trap 'rm -f "$lists" "$lists.sorted"' 0
    find . -print > "$lists" && LC_ALL=C sort "$lists" > "$lists.sorted" || exit 1
    while IFS= read -r item; do
        mode=$(mode_of "$item") || exit 1
        printf '%s %s\n' "$mode" "$item"
    done < "$lists.sorted"
)
apply_modes() (
    dir=$1; modes=$2
    while IFS= read -r line; do
        mode=${line%% *}; item=${line#* }
        case "$mode" in [0-7][0-7][0-7][0-7]) ;; *) exit 1 ;; esac
        case "$item" in .|./*) ;; *) exit 1 ;; esac
        case "/$item/" in *'/../'*|*'/./../'*) exit 1 ;; esac
        [ ! -L "$dir/$item" ] && chmod "$mode" "$dir/$item" || exit 1
    done < "$modes"
)
snapshot_slot() (
    slot=$1; src=$(path_for "$slot") || exit 1; dst="$JOURNAL/data/$slot"
    [ ! -L "$src" ] || exit 1
    if [ -d "$src" ]; then
        ensure_dir "$dst" || exit 1
        cp -R "$src/." "$dst/" || exit 1
        tree_manifest "$src" > "$JOURNAL/source-$slot" || exit 1
        tree_manifest "$dst" > "$JOURNAL/check-$slot" || exit 1
        cmp -s "$JOURNAL/source-$slot" "$JOURNAL/check-$slot" || exit 1
        tree_modes "$src" > "$JOURNAL/modes-$slot" || exit 1
        echo directory > "$JOURNAL/kind-$slot"
    elif [ -f "$src" ]; then
        cp "$src" "$dst" && cmp -s "$src" "$dst" || exit 1
        mode_of "$src" > "$JOURNAL/modes-$slot" || exit 1
        echo file > "$JOURNAL/kind-$slot"
    elif [ -e "$src" ]; then exit 1
    else echo absent > "$JOURNAL/kind-$slot"; : > "$JOURNAL/modes-$slot"
    fi
)
journal_manifest(){
    tree_manifest "$JOURNAL/data" || return 1
    for slot in $(slots); do
        printf 'slot=%s\n' "$slot"
        cat "$JOURNAL/kind-$slot" "$JOURNAL/modes-$slot" || return 1
    done
}
verify_journal(){
    [ -d "$JOURNAL" ] && [ ! -L "$JOURNAL" ] || return 1
    grep -qx "$OWNER" "$JOURNAL/COMPLETE" || return 1
    [ "$(pair "$JOURNAL/manifest")" = "$(cat "$JOURNAL/manifest.cksum")" ] || return 1
    journal_manifest > "$JOURNAL/check-data" || return 1
    cmp -s "$JOURNAL/manifest" "$JOURNAL/check-data" || return 1
    for slot in $(slots); do
        kind=$(cat "$JOURNAL/kind-$slot") || return 1
        case "$kind" in
            directory) [ -d "$JOURNAL/data/$slot" ] || return 1 ;;
            file) [ -f "$JOURNAL/data/$slot" ] || return 1 ;;
            absent) [ ! -e "$JOURNAL/data/$slot" ] || return 1 ;;
            *) return 1 ;;
        esac
    done
}
pending_valid(){
    [ -f "$PENDING" ] && [ ! -L "$PENDING" ] || return 1
    [ "$(sed -n '1p' "$PENDING")" = "$OWNER" ] || return 1
    [ "$(sed -n '2p' "$PENDING")" = "$(pair "$JOURNAL/manifest")" ] || return 1
}
guard_wrapper(){
    wrapper=$1
    [ -f "$wrapper" ] && [ ! -L "$wrapper" ] || return 1
    {
        printf '%s\n' '#!/bin/sh'
        cat <<'CN_UPGRADE_GUARD'
# A previous release did not yet check the outer CN transaction marker.
if [ -e "${H:-/mnt/app/root/hooks}/../.cn-rgi-upgrade.pending" ]; then
    unset LD_PRELOAD CARPLAY_PRELOAD_EXTRA
    cd "${DIODIR:-/mnt/app/eso/bin/apps}" || exit 127
    exec "${DIODIR:-/mnt/app/eso/bin/apps}/dio_manager" "$@"
fi
CN_UPGRADE_GUARD
        sed '1d' "$wrapper"
    } > "$wrapper.cn-upgrade-guard" || return 1
    sh -n "$wrapper.cn-upgrade-guard" && chmod 755 "$wrapper.cn-upgrade-guard" &&
        mv "$wrapper.cn-upgrade-guard" "$wrapper"
}
guard_old_wrapper(){ guard_wrapper "$HOOKS/carplay_startup.sh"; }
begin(){
    [ ! -e "$PENDING" ] || { fail pending_upgrade_requires_recovery; return 1; }
    identify || { fail unrecognized_installation; return 1; }
    if [ -e "$JOURNAL" ]; then
        [ ! -L "$JOURNAL" ] && [ -d "$JOURNAL" ] || return 1
        history="$VOLUME/MMI-Cockpit-Carplay/upgrade-history"
        ensure_dir "$history" || return 1
        seq=1; while [ -e "$history/$seq" ]; do seq=$((seq+1)); done
        mv "$JOURNAL" "$history/$seq" || return 1
    fi
    ensure_dir "$JOURNAL/data" || return 1
    for slot in $(slots); do snapshot_slot "$slot" || { fail "snapshot_$slot"; return 1; }; done
    journal_manifest > "$JOURNAL/manifest" || return 1
    pair "$JOURNAL/manifest" > "$JOURNAL/manifest.cksum" || return 1
    printf '%s\n' "$OWNER" > "$JOURNAL/COMPLETE" || return 1
    verify_journal && sync || return 1
    mount_rw /mnt/app || return 1
    printf '%s\n%s\n' "$OWNER" "$(pair "$JOURNAL/manifest")" > "$PENDING.new" && mv "$PENDING.new" "$PENDING" &&
        touch "$RUNTIME/state/transaction.pending" && rm -f "$RUNTIME/state/basevideo3.enabled" &&
        guard_old_wrapper && sync || { mount_ro /mnt/app; return 1; }
    mount_ro /mnt/app || return 1
    echo 'CN_UPGRADE=PREPARED rollback_target=PREVIOUS_INSTALLATION'
}
restore_slot() (
    slot=$1; dst=$(path_for "$slot") || exit 1; src="$JOURNAL/data/$slot"
    kind=$(cat "$JOURNAL/kind-$slot") || exit 1
    [ ! -L "$dst" ] || exit 1
    case "$kind" in
        directory)
            # Keep the old tree until the replacement is completely copied.
            tmp="$dst.cn-upgrade-recover"
            [ ! -L "$tmp" ] || exit 1
            rm -rf "$tmp" || exit 1
            ensure_dir "$tmp" && cp -R "$src/." "$tmp/" || exit 1
            tree_manifest "$tmp" > "$JOURNAL/check-restore-$slot" || exit 1
            cmp -s "$JOURNAL/source-$slot" "$JOURNAL/check-restore-$slot" || exit 1
            apply_modes "$tmp" "$JOURNAL/modes-$slot" || exit 1
            [ "$slot" != hooks ] || guard_wrapper "$tmp/carplay_startup.sh" || exit 1
            rm -rf "$dst" && mv "$tmp" "$dst" || exit 1 ;;
        file)
            if cmp -s "$src" "$dst" && [ "$(mode_of "$dst")" = "$(cat "$JOURNAL/modes-$slot")" ]; then exit 0; fi
            ensure_dir "$(dirname "$dst")" || exit 1
            cp "$src" "$dst.cn-upgrade-recover" && cmp -s "$src" "$dst.cn-upgrade-recover" &&
                chmod "$(cat "$JOURNAL/modes-$slot")" "$dst.cn-upgrade-recover" &&
                mv "$dst.cn-upgrade-recover" "$dst" || exit 1 ;;
        absent) rm -rf "$dst" || exit 1 ;;
        *) exit 1 ;;
    esac
)
rollback(){
    pending_valid || { fail pending_snapshot_mismatch; return 1; }
    verify_journal || { fail damaged_snapshot_keep_pending; return 1; }
    mount_rw /mnt/app || return 1
    mount_rw /mnt/system || { mount_ro /mnt/app; return 1; }
    rc=0
    # Restore runtime last so its original ACTIVE flags are only published after
    # the JAR, native hook and configurations are back to the same version.
    for slot in hooks jar si dio firewall startup_mnt startup_etc state lib_target stock_dio stock_dio_app stock_airplay stock_nme_arm stock_nme_app stock_nme_eso runtime; do
        restore_slot "$slot" || { rc=1; break; }
    done
    if [ "$rc" = 0 ]; then
        # All component versions now match again. Drop the temporary wrapper
        # guard only after that, so a second interruption during recovery is safe.
        original="$JOURNAL/data/hooks/carplay_startup.sh"
        mode=$(awk '$2=="./carplay_startup.sh" { print $1 }' "$JOURNAL/modes-hooks")
        cp "$original" "$HOOKS/carplay_startup.sh.cn-upgrade-recover" &&
            cmp -s "$original" "$HOOKS/carplay_startup.sh.cn-upgrade-recover" &&
            chmod "$mode" "$HOOKS/carplay_startup.sh.cn-upgrade-recover" &&
            mv "$HOOKS/carplay_startup.sh.cn-upgrade-recover" "$HOOKS/carplay_startup.sh" || rc=1
    fi
    if [ "$rc" = 0 ]; then
        for stray in "$ROOT/mnt/app/root/.carplay-altscreen.previous" "$ROOT/mnt/app/root"/.carplay-altscreen.new.*; do
            [ -e "$stray" ] || continue
            [ -f "$stray/.mmi-cockpit-carplay-runtime-owner" ] && [ ! -L "$stray" ] || { rc=1; break; }
            rm -rf "$stray" || { rc=1; break; }
        done
    fi
    if [ "$rc" = 0 ]; then
        sync && printf '%s\n' ROLLED_BACK > "$JOURNAL/RESULT" && sync && rm -f "$PENDING" || rc=1
    fi
    if [ "$rc" != 0 ]; then
        mount_ro /mnt/app; mount_ro /mnt/system
        fail rollback_incomplete_keep_SD_and_retry_INSTALL; return 1
    fi
    sync || echo 'WARN: previous version restored; final sync failed; reboot required'
    mount_ro /mnt/app || echo 'WARN: previous version restored; app remount failed; reboot required'
    mount_ro /mnt/system || echo 'WARN: previous version restored; system remount failed; reboot required'
    echo 'CN_UPGRADE=ROLLED_BACK previous_installation_restored=YES original_backup_preserved=YES'
}
commit(){
    pending_valid && verify_journal || return 1
    # INSTALL intentionally disarms its inner controller. Restore only the
    # previous persistent activation choices, never volatile phone-session data.
    mount_rw /mnt/app || return 1
    rc=0
    for leaf in ARMED ARMED_MUTATE ARMED_IAP2 ARMED_INFO ARMED_FEATURE ARMED_CREATE111 ACTIVE FORCE_START \
                FULL_CHAIN_MODE NATIVE_DISPLAY_MODE IAP2_PROFILE run_id fullchain_probe basevideo3.enabled; do
        before="$JOURNAL/data/runtime/state/$leaf"; after="$RUNTIME/state/$leaf"
        if [ -f "$before" ]; then
            mode=$(awk -v item="./state/$leaf" '$2==item { print $1 }' "$JOURNAL/modes-runtime")
            cp "$before" "$after" && cmp -s "$before" "$after" && chmod "$mode" "$after" || rc=1
        else rm -f "$after" || rc=1; fi
    done
    for name in cluster_ui.url cluster_fps; do
        before="$JOURNAL/data/hooks/$name"; after="$HOOKS/$name"
        if [ -f "$before" ]; then
            mode=$(awk -v item="./$name" '$2==item { print $1 }' "$JOURNAL/modes-hooks")
            cp "$before" "$after" && cmp -s "$before" "$after" && chmod "$mode" "$after" || rc=1
        else rm -f "$after" || rc=1; fi
    done
    if [ "$rc" = 0 ]; then
        sync && printf '%s\n' COMMITTED > "$JOURNAL/RESULT" && sync &&
            rm -f "$RUNTIME/state/transaction.pending" && rm -f "$PENDING" || rc=1
    fi
    if [ "$rc" != 0 ]; then mount_ro /mnt/app; return 1; fi
    # Once pending is removed the new complete version is committed. A final
    # read-only remount failure must not trigger a rollback with no journal owner.
    sync || echo 'WARN: CN upgrade committed; final sync failed; reboot required'
    mount_ro /mnt/app || echo 'WARN: CN upgrade committed; remount /mnt/app read-only failed; reboot required'
    echo 'CN_UPGRADE=COMMITTED activation_preserved=YES user_choices_preserved=YES reboot_required=YES'
}
recover(){
    [ -e "$PENDING" ] || return 0
    train=""
    for rel in /net/rcc/dev/shmem/version.txt /dev/shmem/version.txt /net/mmx/dev/shmem/version.txt; do
        [ -r "$ROOT$rel" ] || continue
        train=$(sed -n '/Current train/p' "$ROOT$rel" | head -n 1)
        [ -z "$train" ] || break
    done
    printf '%s\n' "$train" | grep -Eq '(^|[^A-Za-z0-9_])MHI2Q_CN_AUG22_P1002([^A-Za-z0-9_]|$)' || {
        fail recovery_firmware_mismatch; return 1;
    }
    echo 'CN_UPGRADE=RECOVERING interrupted_installation=YES'
    rollback || return 1
    echo 'ACTION=Full_MMI_reboot_then_retry_INSTALL_previous_version_restored'
    return 10
}
case "${1:-}" in
    identify) identify ;;
    begin) begin ;;
    rollback) rollback ;;
    commit) commit ;;
    recover) recover ;;
    *) echo 'usage: cn_upgrade_transaction.sh identify|begin|rollback|commit|recover'; exit 2 ;;
esac
