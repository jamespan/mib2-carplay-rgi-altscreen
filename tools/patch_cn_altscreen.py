#!/usr/bin/env python3
"""Replay the vehicle-verified CN P1002 AMap safe-area and phone-marker fixes.

Only the exact upstream AltScreen ELF, optionally processed by this repository's
FPS tool, is accepted. OEM libraries are neither read nor redistributed. The hex
payload is our assembled safearea.S code. Each geometry mode has a pinned full-file
SHA: on matches the vehicle-tested v21 hook; off restores upstream geometry and
keeps only repeated phone markers. FPS is independent and preserved.
"""
import argparse
import hashlib
from pathlib import Path
import sys

from patch_altscreen_fps import TARGETS, apply as fps_apply

HERE = Path(__file__).resolve().parent
BASE_SHA = TARGETS['libcarplay_altscreen.so']['sha256']
CN_SHA = '8980ea016d91411e524fd7777e2e457410591da69b7be3fe2ff3ac927bdd7875'
CN_MARKER_SHA = '37bbee59321bce4e1e35d87816a09288a1e5b656673f9d0fa20ba8ccb83a649f'
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


def patch(data, safe_area=True):
    original = normalized(data)
    expected_sha = CN_SHA if safe_area else CN_MARKER_SHA
    if sha(original) == expected_sha:
        return data  # idempotent, still a complete pinned-file identity check
    if sha(original) not in (BASE_SHA, CN_SHA, CN_MARKER_SHA):
        raise ValueError('not the pinned upstream AltScreen hook/FPS variant')
    # Rebuild either mode from the checked-in baseline, so turning safeArea off
    # restores BOTH call sites and its entire code range, retaining phone markers.
    if sha(original) != BASE_SHA:
        original = (HERE.parent / 'altscreen/Toolbox/carplay_alt_screen/universal/libcarplay_altscreen.so').read_bytes()
    if sha(original) != BASE_SHA or len(original) != 251880:
        raise ValueError('unknown CN overlay input')
    out = bytearray(original)
    out[0x14B84:0x14B88] = data[0x14B84:0x14B88]  # preserve chosen FPS mode
    out[0x0DF88:0x0DF8C] = bytes.fromhex('0000a0e1')
    if not safe_area:
        result = bytes(out)
        if sha(normalized(result)) != CN_MARKER_SHA:
            raise ValueError('phone-marker-only output identity mismatch')
        return result
    assembly = (HERE / 'cn_p1002/safearea.S').read_bytes()
    if sha(assembly) != PAYLOAD_SHA:
        raise ValueError('safearea assembly changed; regenerate and revalidate the payload')
    payload = bytes.fromhex((HERE / 'cn_p1002/safearea.hex').read_text())
    if len(payload) != 324:
        raise ValueError('unexpected safearea payload size')
    out[START:END] = payload + bytes.fromhex('00de') * ((END - START - len(payload)) // 2)
    for offset, old, new in (
        (0x26218, 'e20000eb', 'e20000fa'),
        (0x2713C, '19fdffeb', '1afdfffa'),
        (0x0DF88, '1eff2f11', '0000a0e1'),
    ):
        if original[offset:offset + 4] != bytes.fromhex(old):
            raise ValueError('unexpected branch at %#x' % offset)
        out[offset:offset + 4] = bytes.fromhex(new)
    result = bytes(out)
    if sha(normalized(result)) != CN_SHA:
        raise ValueError('overlay differs from the verified v21 code')
    return result


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--safe-area', choices=('on', 'off'), default='on')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv[1:])
    try:
        output = patch(args.input.read_bytes(), safe_area=args.safe_area == 'on')
        args.output.write_bytes(output)
        print('%s: CN P1002 safeArea=%s phone_marker=repeat, sha256=%s' % (args.output, args.safe_area, sha(output)))
    except (OSError, ValueError) as exc:
        print('ERROR: %s' % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
