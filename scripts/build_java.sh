#!/bin/bash
# Build against the actual target firmware, never ship its stock classes.
# Legacy: STOCK_JAR=MU1329-base.jar ./scripts/build_java.sh
# CN: STOCK_JAR=/private/path/CN_P1002-combined.jar STOCK_JCL=same \
#       STOCK_FIRMWARE=MHI2Q_CN_AUG22_P1002 ./scripts/build_java.sh
# STOCK_JCL=same uses the JCL/OSGi already contained in a complete stock JXE.
# EXTRA_JAVA_JARS is an optional colon-separated list (e.g. external OSGi JARs).
# JAVA_BUILD_MODE=local JAVA_HOME=/path/to/jdk8 avoids Docker when JDK 8 exists.
set -euo pipefail
[ "$#" -eq 0 ] || { echo "usage: ./scripts/build_java.sh" >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR=${JXE2JAR_DIR:-"$PROJECT_DIR/../../Tools/jxe2jar"}
STOCK_INPUT=${STOCK_JAR:-MU1316-final.jar}
if [ -f "$STOCK_INPUT" ]; then
    STOCK_PATH="$(cd "$(dirname "$STOCK_INPUT")" && pwd)/$(basename "$STOCK_INPUT")"
elif [ -f "$TOOLS_DIR/out/$STOCK_INPUT" ]; then
    STOCK_PATH="$(cd "$TOOLS_DIR/out" && pwd)/$STOCK_INPUT"
else
    echo "ERROR: stock JAR not found: $STOCK_INPUT; set STOCK_JAR to this firmware's converted JAR" >&2
    exit 1
fi
JCL_PATH=${STOCK_JCL:-}
[ "$JCL_PATH" != same ] || JCL_PATH=$STOCK_PATH
if [ -n "$JCL_PATH" ]; then
    [ -f "$JCL_PATH" ] || { echo "ERROR: STOCK_JCL not found: $JCL_PATH" >&2; exit 1; }
    JCL_PATH="$(cd "$(dirname "$JCL_PATH")" && pwd)/$(basename "$JCL_PATH")"
fi
EXTRA=${EXTRA_JAVA_JARS:-}
if [ -z "$EXTRA" ] && [ -d "$TOOLS_DIR/libs" ]; then
    EXTRA="$TOOLS_DIR/libs/org.osgi.framework-1.10.0.jar:$TOOLS_DIR/libs/org.osgi.util.tracker-1.5.4.jar"
fi
EXTRA_PATHS=()
if [ -n "$EXTRA" ]; then
    IFS=: read -r -a EXTRA_PATHS <<< "$EXTRA"
    for i in "${!EXTRA_PATHS[@]}"; do
        p=${EXTRA_PATHS[$i]}
        [ -f "$p" ] || { echo "ERROR: extra Java JAR not found: $p" >&2; exit 1; }
        EXTRA_PATHS[$i]="$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
    done
fi
MODE=${JAVA_BUILD_MODE:-docker}
case "$MODE" in docker|local) ;; *) echo 'ERROR: JAVA_BUILD_MODE must be docker or local' >&2; exit 2;; esac
BUILD_ID_RAW=${CARPLAY_BUILD_ID:-$(git -C "$PROJECT_DIR" describe --always --dirty 2>/dev/null || echo unknown)}
BUILD_ID=$(printf '%s' "$BUILD_ID_RAW" | tr -cd 'A-Za-z0-9._-')
[ -n "$BUILD_ID" ] || { echo 'ERROR: empty build ID' >&2; exit 1; }
mkdir -p "$PROJECT_DIR/build"
python3 "$PROJECT_DIR/tools/java_build_manifest.py" inputs --stock "$STOCK_PATH" \
    --jcl "$JCL_PATH" --firmware "${STOCK_FIRMWARE:-unspecified}" --build-id "$BUILD_ID" \
    --expected-sha256 "${STOCK_JAR_SHA256:-}" --output "$PROJECT_DIR/build/java-inputs.json"
SOURCE_DIR="$PROJECT_DIR/java_patch"
if [ "${STOCK_FIRMWARE:-}" = MHI2Q_CN_AUG22_P1002 ]; then
    [ -n "$JCL_PATH" ] || { echo 'ERROR: CN build requires STOCK_JCL (same for complete CN JXE)' >&2; exit 1; }
    python3 "$PROJECT_DIR/tools/prepare_cn_java.py" --source "$SOURCE_DIR" --output "$PROJECT_DIR/build/java-profile"
    SOURCE_DIR="$PROJECT_DIR/build/java-profile"
fi
if [ "$MODE" = local ]; then
    JDK_BIN=${JAVA_HOME:+"$JAVA_HOME/bin/"}
    CP=$STOCK_PATH
    for p in "${EXTRA_PATHS[@]}"; do CP="$CP:$p"; done
    PROJECT_ROOT="$PROJECT_DIR" BUILD_ID="$BUILD_ID" BUILD_CLASSPATH="$CP" \
        BUILD_BOOTCLASSPATH="$JCL_PATH" JAVA_SOURCE_DIR="$SOURCE_DIR" JDK_BIN="$JDK_BIN" bash "$SCRIPT_DIR/compile_java.sh"
else
    IMG=${JAVA_BUILD_IMAGE:-eclipse-temurin:8-jdk-jammy}
    MOUNTS=(-v "$PROJECT_DIR:/src" -v "$STOCK_PATH:/deps/stock.jar:ro")
    CP=/deps/stock.jar
    BOOT=
    if [ -n "$JCL_PATH" ]; then MOUNTS+=(-v "$JCL_PATH:/deps/jcl.jar:ro"); BOOT=/deps/jcl.jar; fi
    for i in "${!EXTRA_PATHS[@]}"; do
        MOUNTS+=(-v "${EXTRA_PATHS[$i]}:/deps/extra-$i.jar:ro")
        CP="$CP:/deps/extra-$i.jar"
    done
    docker run --rm --network none "${MOUNTS[@]}" \
        -e JAVA_SOURCE_DIR="/src/${SOURCE_DIR#"$PROJECT_DIR/"}" -e PROJECT_ROOT=/src -e BUILD_ID="$BUILD_ID" -e BUILD_CLASSPATH="$CP" \
        -e BUILD_BOOTCLASSPATH="$BOOT" "$IMG" bash /src/scripts/compile_java.sh
fi
python3 "$PROJECT_DIR/tools/java_build_manifest.py" output --jar "$PROJECT_DIR/build/carplay_hook.jar" \
    --inputs "$PROJECT_DIR/build/java-inputs.json" --output "$PROJECT_DIR/build/java-build.json"
echo "Output: $PROJECT_DIR/build/carplay_hook.jar (build $BUILD_ID)"
