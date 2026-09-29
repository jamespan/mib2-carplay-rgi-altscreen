#!/usr/bin/env python3
"""Replay the vehicle-verified CN P1002 AMap safe-area and phone-marker fixes.

Only the exact upstream AltScreen ELF, optionally processed by this repository's
FPS tool, is accepted. OEM libraries are neither read nor redistributed. The hex
payload is our assembled safearea.S code; the output's normalized SHA must equal
the previously vehicle-tested v21 hook. FPS is independent and preserved.
"""
import hashlib
from pathlib import Path
import sys

from patch_altscreen_fps import TARGETS, apply as fps_apply, state as fps_state

HERE = Path(__file__).resolve().parent
BASE_SHA = TARGETS['libcarplay_altscreen.so']['sha256']
CN_SHA = '8980ea016d91411e524fd7777e2e457410591da69b7be3fe2ff3ac927bdd7875'
PAYLOAD_SHA = '4642385e89b0d48918eb3f5a19953e4bad2739ce5c3306bbe4a58b3d95e0d09f'
START, END = 0x265A8, 0x26774


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    """Normalize only the known FPS word; never normalize arbitrary code."""
    word = data[0x14B84:0x14B88]
    if word not in (bytes.fromhex('dc00001a'), bytes.fromhex('00f020e3')):
        raise ValueError('unknown FPS instruction')
    return fps_apply(data, TARGETS['libcarplay_altscreen.so']['patches'], 1)


def patch(data):
    original = normalized(data)
    if sha(original) == CN_SHA:
        return data  # idempotent, still a complete pinned-file identity check
    name, state = fps_state(data)
    if name != 'libcarplay_altscreen.so' or state not in ('stock', 'patched'):
        raise ValueError('not the pinned upstream AltScreen hook/FPS variant')
    if sha(original) != BASE_SHA or len(original) != 251880:
        raise ValueError('unknown CN overlay input')
    assembly = (HERE / 'cn_p1002/safearea.S').read_bytes()
    if sha(assembly) != PAYLOAD_SHA:
        raise ValueError('safearea assembly changed; regenerate and revalidate the payload')
    payload = bytes.fromhex((HERE / 'cn_p1002/safearea.hex').read_text())
    if len(payload) != 324:
        raise ValueError('unexpected safearea payload size')
    out = bytearray(data)
    out[START:END] = payload + bytes.fromhex('00de') * ((END - START - len(payload)) // 2)
    for offset, old, new in (
        (0x26218, 'e20000eb', 'e20000fa'),
        (0x2713C, '19fdffeb', '1afdfffa'),
        (0x0DF88, '1eff2f11', '0000a0e1'),
    ):
        if data[offset:offset + 4] != bytes.fromhex(old):
            raise ValueError('unexpected branch at %#x' % offset)
        out[offset:offset + 4] = bytes.fromhex(new)
    result = bytes(out)
    if sha(normalized(result)) != CN_SHA:
        raise ValueError('overlay differs from the verified v21 code')
    return result


def main(argv):
    if len(argv) != 3:
        print('usage: patch_cn_altscreen.py <input.so> <output.so>', file=sys.stderr)
        return 2
    try:
        output = patch(Path(argv[1]).read_bytes())
        Path(argv[2]).write_bytes(output)
        print('%s: CN P1002 safeArea + phone marker, sha256=%s' % (argv[2], sha(output)))
    except (OSError, ValueError) as exc:
        print('ERROR: %s' % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
