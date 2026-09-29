#!/usr/bin/env python3
"""Publish direct-display once after the first real frame, including after a logo.

Pinned upstream sidecar only, optionally FPS-patched. At 0x102894 the current
BEQ skips marker(true, ..., "direct-display") when r6=1 (a logo was presented).
The new unconditional branch takes that same first-frame-only marker path. The
steady-state frame loop (0x10292c, present_frame at 0x102964) never traverses it.
No startup delay, geometry, per-frame write, or failure path is changed.
"""
import argparse
import hashlib
from pathlib import Path
from patch_altscreen_fps import TARGETS, apply

TARGET = TARGETS["carplay-alt111-mirror-display"]
OFFSET = 0x2894
OLD = bytes.fromhex("1e01000a")
NEW = bytes.fromhex("1e0100ea")


def patch(data):
    if data[OFFSET:OFFSET + 4] not in (OLD, NEW):
        raise ValueError("unknown first-frame marker branch")
    original = bytearray(data)
    original[OFFSET:OFFSET + 4] = OLD
    fps = TARGET["patches"]
    # Require one complete known FPS mode; no arbitrary-word normalization.
    if not any(all(original[p[0]:p[0]+4] == bytes.fromhex(p[column]) for p in fps)
               for column in (1, 2)):
        raise ValueError("unknown/mixed FPS mode")
    normalized = apply(original, fps, 1)
    if hashlib.sha256(normalized).hexdigest() != TARGET["sha256"]:
        raise ValueError("not the pinned upstream sidecar/FPS variant")
    output = bytearray(data)
    output[OFFSET:OFFSET + 4] = NEW
    return bytes(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = patch(args.input.read_bytes())
    args.output.write_bytes(output)
    print("%s: first-video phase publication, sha256=%s" %
          (args.output, hashlib.sha256(output).hexdigest()))


if __name__ == "__main__":
    main()
