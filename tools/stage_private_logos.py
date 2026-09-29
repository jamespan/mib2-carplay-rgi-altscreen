#!/usr/bin/env python3
"""Stage a local numbered AL111LG1 splash pool; never download or generate images."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct


def inspect_pool(source):
    assets = {}
    for path in source.glob("logo_*.rgba"):
        match = re.fullmatch(r"logo_([1-9][0-9]*)\.rgba", path.name)
        if match:
            assets[int(match[1])] = path
    if not assets or sorted(assets) != list(range(1, len(assets) + 1)) or len(assets) > 64:
        raise ValueError("provide consecutive logo_1.rgba through logo_N.rgba (1 <= N <= 64)")
    inventory = []
    for number, path in sorted(assets.items()):
        data = path.read_bytes()
        if len(data) < 16 or data[:8] != b"AL111LG1":
            raise ValueError(f"{path.name}: not an AL111LG1 logo")
        width, height = struct.unpack("<II", data[8:16])
        if not width or not height or len(data) != 16 + width * height * 4:
            raise ValueError(f"{path.name}: invalid RGBA dimensions/length")
        inventory.append({"name": path.name, "width": width, "height": height,
                          "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return inventory


def stage_pool(source, release):
    source = source.resolve()
    release = release.resolve()
    inventory = inspect_pool(source)  # Validate everything before touching the stage.
    if source == release:
        raise ValueError("source and release must be separate directories")
    if not (release / "start_vehicle.sh").is_file():
        raise ValueError("release must be a staged mirror directory with start_vehicle.sh")
    for item in inventory:
        shutil.copyfile(source / item["name"], release / item["name"])
    (release / "logo_pool.count").write_text(f"{len(inventory)}\n")
    # This manifest is public-safe: no owner's filesystem paths or image metadata.
    (release / "logo_pool.sha256").write_text("".join(
        f'{item["sha256"]}  {item["name"]}\n' for item in inventory))
    sums = release / "SHA256SUMS"
    lines = sums.read_text().splitlines() if sums.exists() else []
    lines = [line for line in lines if not re.search(r"  logo_(?:[0-9]+\.rgba|pool\.)", line)]
    for name in [item["name"] for item in inventory] + ["logo_pool.count", "logo_pool.sha256"]:
        lines.append(f"{hashlib.sha256((release / name).read_bytes()).hexdigest()}  {name}")
    sums.write_text("\n".join(lines) + "\n")
    return {"count": len(inventory), "assets": inventory}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = stage_pool(args.source, args.release)
    except (OSError, ValueError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
