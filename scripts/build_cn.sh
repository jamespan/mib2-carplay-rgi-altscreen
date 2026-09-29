#!/bin/bash
# Local CN P1002 build. Stock firmware and personal images stay outside Git.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export STOCK_JAR="${STOCK_JAR:-$PROJECT_DIR/build/cn-stock/CN_P1002-combined.jar}"
export STOCK_JCL="${STOCK_JCL:-same}"
export STOCK_FIRMWARE=MHI2Q_CN_AUG22_P1002
export CN_PROFILE=1
export CARPLAY_BUILD_ID="${CARPLAY_BUILD_ID:-cn-p1002-$(git -C "$PROJECT_DIR" describe --always --dirty)}"
exec bash "$PROJECT_DIR/scripts/build_sd.sh" "$@"
