#!/bin/sh
# Sourced by start_vehicle.sh. The assets are an optional, privately staged pool.
# Use the QNX-tested dd + cksum path: QNX od cannot read /dev/urandom reliably.
select_startup_logo() {
  logo_root=$1
  logo_tmp_root=$2
  # Preserve an explicit fixed override, but distinguish it from an automatic
  # selection inherited by same-session abnormal recovery.
  ALT111_LOGO_FIXED_ASSET="${ALT111_LOGO_FIXED_ASSET-${ALT111_LOGO_ASSET:-}}"
  ALT111_LOGO_PICK_SOURCE="${ALT111_LOGO_PICK_SOURCE:-override}"
  ALT111_LOGO_PICK_DETAIL="${ALT111_LOGO_PICK_DETAIL:-not_sampled}"
  if [ -z "${ALT111_LOGO_ASSET:-}" ]; then
    ALT111_LOGO_ASSET="$logo_root/logo.rgba"
    ALT111_LOGO_PICK_SOURCE=default
    ALT111_LOGO_PICK_DETAIL=no_private_pool
    logo_count=$(cat "$logo_root/logo_pool.count" 2>/dev/null || true)
    case "$logo_count" in
      [1-9]|[1-5][0-9]|6[0-4])
        logo_tmp="$logo_tmp_root/MMI-Cockpit-Carplay.logo-random.$$"
        logo_random=; logo_index=
        if dd if="${ALT111_LOGO_RANDOM_DEVICE:-/dev/urandom}" bs=16 count=1 >"$logo_tmp" 2>/dev/null; then
          logo_random=$(cksum < "$logo_tmp" 2>/dev/null) || logo_random=
          logo_index=$(printf '%s\n' "$logo_random" | awk -v n="$logo_count" \
            'NF == 2 && $1 ~ /^[0-9]+$/ && $1 <= 4294967295 && $2 == 16 { print $1 % n + 1; exit }') || logo_index=
        fi
        rm -f "$logo_tmp" 2>/dev/null || true
        case "$logo_index" in
          [1-9]|[1-5][0-9]|6[0-4])
            if [ "$logo_index" -le "$logo_count" ] && [ -s "$logo_root/logo_${logo_index}.rgba" ]; then
              ALT111_LOGO_ASSET="$logo_root/logo_${logo_index}.rgba"
              ALT111_LOGO_PICK_SOURCE=dd_urandom
              ALT111_LOGO_PICK_DETAIL="index=$logo_index count=$logo_count"
            else
              ALT111_LOGO_PICK_DETAIL="missing_pool_asset index=$logo_index count=$logo_count"
            fi
            ;;
          *) ALT111_LOGO_PICK_DETAIL=random_read_failed ;;
        esac
        ;;
      '') ;;
      *) ALT111_LOGO_PICK_DETAIL=invalid_pool_count ;;
    esac
  fi
  export ALT111_LOGO_ASSET ALT111_LOGO_FIXED_ASSET
  export ALT111_LOGO_PICK_SOURCE ALT111_LOGO_PICK_DETAIL
}
