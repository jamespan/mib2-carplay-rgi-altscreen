#!/bin/bash
# Internal build worker; called by build_java.sh on a host JDK 8 or in Docker.
set -euo pipefail
: "${PROJECT_ROOT:?}" "${BUILD_ID:?}" "${BUILD_CLASSPATH:?}"
JDK_BIN=${JDK_BIN:-}
VERSION=$("${JDK_BIN}javac" -version 2>&1)
case "$VERSION" in 'javac 1.8.'*) ;; *) echo "ERROR: JDK 8 required for Java 1.4 output, got $VERSION" >&2; exit 1;; esac
SRC=${JAVA_SOURCE_DIR:-"$PROJECT_ROOT/java_patch"}
WORK="$PROJECT_ROOT/build/java"
OUT="$WORK/classes"
GEN="$WORK/generated"
OUTJAR="$PROJECT_ROOT/build/carplay_hook.jar"
rm -rf "$WORK"
mkdir -p "$OUT" "$GEN/com/luka/carplay/core"
find "$SRC" -name '*.java' -type f | LC_ALL=C sort > "$WORK/sources.txt"
sed "s/@BUILD_ID@/$BUILD_ID/g" "$SRC/com/luka/carplay/core/CarPlayApp.java" > "$GEN/com/luka/carplay/core/CarPlayApp.java"
grep -v '/com/luka/carplay/core/CarPlayApp.java$' "$WORK/sources.txt" > "$WORK/compile.txt"
printf '%s\n' "$GEN/com/luka/carplay/core/CarPlayApp.java" >> "$WORK/compile.txt"
BOOT=()
[ -z "${BUILD_BOOTCLASSPATH:-}" ] || BOOT=(-bootclasspath "$BUILD_BOOTCLASSPATH")
echo "$VERSION; compiling $(wc -l < "$WORK/compile.txt" | tr -d ' ') source files, target 1.4"
"${JDK_BIN}javac" -source 1.4 -target 1.4 "${BOOT[@]}" -cp "$BUILD_CLASSPATH" \
    -sourcepath "$GEN:$SRC" -d "$OUT" -Xlint:-options @"$WORK/compile.txt"
cp -R "$PROJECT_ROOT/java_resources/." "$OUT/"
# Publish only a successfully compiled JAR. Stock/JCL classes are classpath-only.
(cd "$OUT" && "${JDK_BIN}jar" cf "$WORK/carplay_hook.jar" .)
mv "$WORK/carplay_hook.jar" "$OUTJAR"
echo "$VERSION" > "$PROJECT_ROOT/build/java-compiler.txt"
