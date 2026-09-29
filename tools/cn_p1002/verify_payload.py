#!/usr/bin/env python3
"""Reassemble our Thumb payload and compare every byte to safearea.hex.

Requires llvm-mc (LLVM_MC may name it). No QNX/OEM file or third-party Python
package is needed. The seven calls are explicitly relocated to the pinned hook.
"""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
START = 0x265A8
HELPERS = {'cf_dict_get_cstr': 0x275CC, 'alt_cf_int64': 0x25448,
           'rect_dict': 0x2E268, 'set_i64': 0x263F4,
           'cf_dict_set_cstr_obj': 0x26500, 'altscreen_log': 0xD540}


def relocated_payload(obj):
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', obj)
    assert h[0][:7] == b'\x7fELF\x01\x01\x01' and h[2] == 40
    sections = [struct.unpack_from('<IIIIIIIIII', obj, h[6] + i*h[11]) for i in range(h[12])]
    names = sections[h[13]]
    names = obj[names[4]:names[4]+names[5]]
    named = {names[s[0]:].split(b'\0', 1)[0].decode(): s for s in sections}
    text = named['.text']
    payload = bytearray(obj[text[4]:text[4]+text[5]])
    sym = named['.symtab']
    strings = sections[sym[6]]
    strings = obj[strings[4]:strings[4]+strings[5]]
    symbols = []
    for offset in range(sym[4], sym[4]+sym[5], sym[9]):
        n, value, size, info, other, index = struct.unpack_from('<IIIBBH', obj, offset)
        symbols.append(strings[n:].split(b'\0', 1)[0].decode())
    rel = named['.rel.text']
    count = 0
    for offset in range(rel[4], rel[4]+rel[5], rel[9]):
        place, info = struct.unpack_from('<II', obj, offset)
        assert info & 255 == 10, 'only R_ARM_THM_CALL relocations allowed'
        target = HELPERS[symbols[info >> 8]]
        delta = target - ((START + place + 4) & ~3)
        assert target % 4 == 0 and delta % 4 == 0 and -(1 << 24) <= delta < (1 << 24)
        value = delta & 0x1FFFFFF
        sign, i1, i2 = (value >> 24) & 1, (value >> 23) & 1, (value >> 22) & 1
        hi = 0xF000 | (sign << 10) | ((value >> 12) & 0x3FF)
        lo = 0xC000 | ((1 ^ i1 ^ sign) << 13) | ((1 ^ i2 ^ sign) << 11) | (((value >> 2) & 0x3FF) << 1)
        payload[place:place+4] = struct.pack('<HH', hi, lo)
        count += 1
    assert count == 7 and len(payload) == 324
    return bytes(payload)


def main():
    if not __debug__:
        raise SystemExit('Run without -O/PYTHONOPTIMIZE; relocation assertions are required')
    mc = os.environ.get('LLVM_MC') or shutil.which('llvm-mc')
    if not mc:
        raise SystemExit('llvm-mc is required; set LLVM_MC to its full path')
    with tempfile.TemporaryDirectory() as tmp:
        obj = Path(tmp) / 'safearea.o'
        subprocess.run([mc, '-triple=thumbv7-none-eabi', '-filetype=obj', str(HERE/'safearea.S'), '-o', str(obj)], check=True)
        actual = relocated_payload(obj.read_bytes())
    expected = bytes.fromhex((HERE/'safearea.hex').read_text())
    if actual != expected:
        raise SystemExit('FAIL: assembled payload differs from committed hex')
    print('PASS: 324 payload bytes, 7 explicit ARM/Thumb call relocations')


if __name__ == '__main__':
    main()
