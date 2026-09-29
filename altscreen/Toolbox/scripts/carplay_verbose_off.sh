#!/bin/sh
SCRIPT_DIR=$(CDPATH='' cd -P -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || exit 1
exec /bin/sh "$SCRIPT_DIR/store_carplay_logs.sh" verbose-off
