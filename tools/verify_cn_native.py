#!/usr/bin/env python3
"""Static CN P1002 native gates. Reads private OEM inputs; never copies/runs them.

Usage: verify_cn_native.py --stock-dir <private vehicle dump> [--llvm-bin <dir>]
Writes build/native-evidence/cn-native-build.json only from the inspected outputs.
This checks symbol/ELF contracts, not the vehicle loader or on-road operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from native_source_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
OEM = {
    '_eso_lib_libairplay.so': 'ea2c64202f41fe8ad1fbd3cdf9b3ce2b7a2889a333d5e9b49b1b3aaf83be3950',
    '_armle_usr_lib_libNmeBaseClasses.so': 'd7df8be388a076608c49cf37fe66b312e4f713b22f6608915a30121a4d517a8f',
    '_mnt_app_armle_usr_lib_libNmeSDK.so': '81e3c1d946c872f1591bf2ffb5e171f8d341568766217635c0545ae3bf8dee70',
}
CF_SYMBOLS = ['AirPlayReceiverSessionSendCommand', 'CFDictionaryCreateMutable',
              'CFDictionarySetValue', 'CFDictionarySetInt64', 'CFStringCreateWithCString',
              'CFRelease', 'kCFLDictionaryKeyCallBacksCFLTypes', 'kCFLDictionaryValueCallBacksCFLTypes']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elf(path, expected_type):
    b = path.read_bytes()
    assert b[:7] == b'\x7fELF\x01\x01\x01', 'requires ELF32 little-endian'
    h = struct.unpack_from('<HHIIIIIHHHHHH', b, 16)
    typ, machine, _, _, phoff, shoff, flags, _, phsize, phnum, shsize, shnum, shstr = h
    assert (typ, machine) == (expected_type, 40), 'requires ARM target object'
    assert flags >> 24 == 5 and not flags & 0x400, 'requires EABI5 soft-float call ABI'
    sections = [struct.unpack_from('<IIIIIIIIII', b, shoff+i*shsize) for i in range(shnum)]
    names = b[sections[shstr][4]:sections[shstr][4]+sections[shstr][5]]
    byname = {names[s[0]:].split(b'\0', 1)[0].decode(): s for s in sections}
    assert not any(s[2] & 0x400 for s in sections), 'unexpected TLS section'
    assert not any(struct.unpack_from('<I', b, phoff+i*phsize)[0] == 7 for i in range(phnum)), 'unexpected PT_TLS'
    return b, byname


def main():
    if not __debug__:
        raise SystemExit('Run without -O/PYTHONOPTIMIZE; native audit assertions are required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-dir', type=Path, required=True)
    parser.add_argument('--llvm-bin', type=Path)
    parser.add_argument('--build-dir', type=Path, default=ROOT/'build')
    args = parser.parse_args()
    out = args.build_dir/'native-evidence'
    out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'FAIL', 'firmware': 'MHI2Q_CN_AUG22_P1002',
              'vehicle_validated': False, 'target_executed': False, 'errors': [],
              'checks': {}, 'private_oem_inputs': {}}

    def tool(name, *parameters):
        command = str(args.llvm_bin/name) if args.llvm_bin else shutil.which(name)
        assert command, '%s is required' % name
        return subprocess.check_output([command, *map(str, parameters)], text=True)

    def exports(path):
        return {line.split()[-1] for line in tool('llvm-nm', '-D', '--defined-only', path).splitlines() if line.strip()}

    try:
        oem_exports = set()
        for name, digest in OEM.items():
            path = args.stock_dir/name
            assert sha(path) == digest, 'wrong CN factory input: %s' % name
            found = exports(path)
            oem_exports.update(found)
            report['private_oem_inputs'][name] = {'sha256': digest, 'exports': len(found)}
        hook = args.build_dir/'libcarplay_hook.so'
        renderer = args.build_dir/'maneuver_render'
        report['hook_sha256'] = sha(hook)
        report['renderer_sha256'] = sha(renderer)
        expected = set(re.findall(r'^\s+([A-Za-z_][A-Za-z_0-9]+);$', (ROOT/'hook/carplay_hook.exports.map').read_text(), re.M))
        assert len(expected) == 7 and exports(hook) == expected, 'hook dynamic export allowlist mismatch'
        assert expected <= oem_exports, 'CN original lacks an interposed entry'
        required = set(CF_SYMBOLS + ['CinemoCreateIAP', 'ICinemoIAP_AddRef', 'ICinemoIAP_Release', 'ICinemoIAP_SendIAP2'])
        assert required <= oem_exports, 'CN original lacks CF/iAP sender entry'
        report['checks']['cn_factory_and_airplay_symbol_contracts'] = True
        report['checks']['hook_exact_seven_exports'] = sorted(expected)
        for label, path, kind in [('hook', hook, 3), ('renderer', renderer, 2)]:
            b, sections = elf(path, kind)
            symbols = tool('llvm-nm', '-an', path)
            imports = tool('llvm-nm', '-D', '-u', path)
            details = tool('llvm-readelf', '-W', '-h', '-l', '-S', '-d', '-r', '-A', path)
            (out/(label+'-elf.txt')).write_text(details)
            (out/(label+'-symbols.txt')).write_text(symbols)
            (out/(label+'-imports.txt')).write_text(imports)
            assert 'emutls' not in symbols.lower(), 'emulated TLS is incompatible'
            assert 'TEXTREL' not in details and not re.search(r'\bR_ARM_REL32\b', details), 'unsupported dynamic relocation'
            assert not re.search(r'libstdc\+\+|libgcc_s', details), 'unexpected dynamic C++ runtime'
            # GCC's C crtbegin emits an optional weak __cxa_finalize too. It is
            # already present in the previous pure-C CN candidate; strong C++
            # runtime requirements and every other __cxa import remain rejected.
            runtime_imports = '\n'.join(line for line in imports.splitlines()
                                        if not re.fullmatch(r'\s+w\s+__cxa_finalize', line))
            assert not re.search(r'(__cxa|_ZSt|_ZTI|_ZTV|_Zn[aw]|_Zd[al]|gxx_personality)', runtime_imports), 'unexpected C++ runtime imports'
            assert not re.search(r'Tag_ABI_VFP_args:\s+VFP registers', details), 'hard-float calling ABI'
            needed = re.findall(r'Shared library: \[([^]]+)\]', details)
            if label == 'hook':
                assert needed == ['libz.so.2', 'libsocket.so.3'], 'hook dependency drift'
                init = sections['.init_array']
                assert init[5] == 4, 'eager hook initializer'
                frame = re.search(r'^([0-9a-f]+)\s+\w\s+frame_dummy$', symbols, re.M)
                assert frame and struct.unpack_from('<I', b, init[4])[0] == int(frame[1], 16), 'hook initializer is not compiler frame_dummy'
            else:
                assert set(needed) == {'libscreen.so.1', 'libEGL.so.1', 'libGLESv2.so.1', 'libsocket.so.3', 'libm.so.2', 'libc.so.3'}, 'renderer dependency drift'
            report['checks'][label] = {'bytes': len(b), 'elf': 'ARM ELF32 EABI5 softfp', 'needed': needed,
                                       'tls': False, 'emutls': False, 'textrel': False, 'dynamic_cpp_runtime': False}
        report['checks']['renderer_bsp_limit'] = 'Linked against import stubs; actual CN screen/EGL/GLES loader/display composition must be vehicle-tested.'
        report['checks']['iap2_abi_limit'] = 'CN factory/wrapper argument and ownership analysis is documented in docs/cn-p1002-native.md; symbols alone are not a live-session test.'
        for label in ('hook', 'renderer'):
            report[label+'_image'] = (out/(label+'-image.txt')).read_text().strip()
            before = json.loads((out/(label+'-inputs-before.json')).read_text())
            after = json.loads((out/(label+'-inputs-after.json')).read_text())
            assert before == after == manifest(label), 'native build inputs changed: %s' % label
            report['checks'][label+'_source_inputs_unchanged'] = True
        report['status'] = 'PASS'
    except (OSError, AssertionError, subprocess.SubprocessError) as exc:
        report['errors'].append(str(exc))
    (out/'cn-native-build.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
