#!/bin/bash
# Headless CPU regression test linked to the production renderer sources.
set -euo pipefail
PROJECT_DIR=$(cd "$(dirname "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
cd "$PROJECT_DIR"
# Keep a nonempty array for the macOS system Bash 3.2 + nounset combination.
HOST_FLAGS=(-fno-omit-frame-pointer)
PLATFORM_FLAGS=(-DPLATFORM_MACOS -I/opt/homebrew/include)
PLATFORM_SOURCE=maneuver_render/platform_macos.c
PLATFORM_LIBS=(-L/opt/homebrew/lib -lglfw -framework OpenGL)
if [ "$(uname)" = Linux ]; then
    HOST_FLAGS=(-D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L -ffunction-sections -fdata-sections)
    # Keep the same preview/CPU code path as the original macOS suite. Only
    # graphics declarations come from portable Khronos GLES2 headers; no GL
    # implementation is linked or executed. Ubuntu: libgles2-mesa-dev.
    mkdir -p "$TEST_DIR/OpenGL"
    printf '#include <GLES2/gl2.h>\n' > "$TEST_DIR/OpenGL/gl.h"
    PLATFORM_FLAGS=(-DPLATFORM_MACOS -I"$TEST_DIR")
    PLATFORM_LIBS=(-Wl,--gc-sections)
    PLATFORM_SOURCE="$TEST_DIR/unused_graphics_symbols.c"
    # The parity suite intentionally never creates a window or calls GL. Resolve
    # those cold symbols without depending on a desktop/window server, but abort
    # if a test accidentally calls one. Geometry/scene/decoder code is unchanged.
    printf '#include <stdio.h>\n#include <stdlib.h>\n' > "$PLATFORM_SOURCE"
    for symbol in $(grep -hoE 'gl[A-Z][A-Za-z0-9_]+|platform_[a-z_]+\(' \
        maneuver_render/render.c common/gl_program_cache.h maneuver_render/main.c \
        | sed 's/($//' | sort -u); do
        printf 'void %s(void) { fprintf(stderr, "unexpected graphics/platform call: %s\\n"); abort(); }\n' \
            "$symbol" "$symbol" >> "$PLATFORM_SOURCE"
    done
fi
cc "${HOST_FLAGS[@]}" -O1 -g -std=c99 -Wall -Wextra -Icommon -fsanitize=address,undefined \
    -fno-omit-frame-pointer tests/lane_guidance_test.c -o "$TEST_DIR/lane_guidance_test"
"$TEST_DIR/lane_guidance_test"
SCENE_OBJECTS=()
for source in scene geometry layout lane_panel; do
    c++ "${HOST_FLAGS[@]}" "${PLATFORM_FLAGS[@]}" -O1 -g -std=c++11 -fno-exceptions -fno-rtti -Icommon \
        -fsanitize=address,undefined -fno-omit-frame-pointer \
        -c "maneuver_render/scene/$source.cpp" -o "$TEST_DIR/$source.o"
    SCENE_OBJECTS+=("$TEST_DIR/$source.o")
done
cc "${HOST_FLAGS[@]}" "${PLATFORM_FLAGS[@]}" -O1 -g -std=c99 -Wall -Wextra -Icommon \
    -fsanitize=address,undefined -fno-omit-frame-pointer \
    tests/maneuver_parity_test.c maneuver_render/route_path.c \
    maneuver_render/render.c maneuver_render/server.c "$PLATFORM_SOURCE" \
    "${SCENE_OBJECTS[@]}" \
    "${PLATFORM_LIBS[@]}" -lm -o "$TEST_DIR/maneuver_parity_test"
"$TEST_DIR/maneuver_parity_test"
cc "${HOST_FLAGS[@]}" -O1 -g -std=c99 -Wall -Wextra -Icommon -fsanitize=address,undefined \
    -fno-omit-frame-pointer tests/renderer_peer_loss_test.c -o "$TEST_DIR/renderer_peer_loss_test"
"$TEST_DIR/renderer_peer_loss_test"
