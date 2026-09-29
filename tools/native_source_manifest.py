#!/usr/bin/env python3
"""Hash repository-native build inputs without reading SDK or vehicle files."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def manifest(target):
    if target == 'hook':
        dirs, script = ['hook'], 'scripts/build_hook.sh'
    elif target == 'renderer':
        dirs, script = ['maneuver_render', 'common', 'toolchain/qnx65-abi/include'], 'scripts/build_renderers.sh'
    else:
        raise ValueError('target must be hook or renderer')
    paths = [ROOT/script, Path(__file__).resolve()]
    for directory in dirs:
        paths.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ('.c', '.h', '.cpp', '.hpp', '.map'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: native_source_manifest.py hook|renderer')
    print(json.dumps(manifest(sys.argv[1]), sort_keys=True, indent=2))
