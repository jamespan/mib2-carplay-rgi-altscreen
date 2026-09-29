#!/usr/bin/env python3
"""Record firmware identity and reject incompatible Java class output.

The complete converted stock/JCL are local analysis inputs, never payload.
This validates build identity and class format, not head-unit behavior.
"""
import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def source_inputs(project=PROJECT):
    """Inputs affecting the emitted Java classes/resources; paths are repo-relative."""
    project = Path(project)
    paths = {project / name for name in (
        "scripts/build_java.sh", "scripts/compile_java.sh",
        "tools/prepare_cn_java.py", "tools/java_build_manifest.py",
    )}
    for directory in ("java_patch", "java_resources"):
        paths.update(p for p in (project / directory).rglob("*") if p.is_file())
    return {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def source_digest(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_source_inputs(record, project=PROJECT):
    """Fail on missing/stale provenance; used by both audit and SD staging."""
    expected = record.get("source_inputs")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Java build has no source provenance; rebuild and re-audit")
    if record.get("source_sha256") != source_digest(expected):
        raise ValueError("Java source manifest aggregate does not match its entries")
    actual = source_inputs(project)
    if expected != actual:
        changed = [p for p in sorted(set(expected) | set(actual)) if expected.get(p) != actual.get(p)]
        raise ValueError("Java sources changed since build: " + ", ".join(changed[:10]))
    return True


def identity(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size}


def inputs(args):
    stock = identity(args.stock)
    if args.expected_sha256 and stock["sha256"] != args.expected_sha256.lower():
        raise SystemExit("ERROR: stock JAR SHA-256 mismatch")
    with zipfile.ZipFile(args.stock) as jar:
        classes = [n for n in jar.namelist() if n.endswith(".class")]
        if not classes:
            raise SystemExit("ERROR: stock JAR contains no classes")
    sources = source_inputs(args.project)
    return {"stock": stock, "stock_class_count": len(classes),
            "jcl": identity(args.jcl) if args.jcl else None,
            "firmware": args.firmware, "build_id": args.build_id,
            "source_inputs": sources, "source_sha256": source_digest(sources),
            "vehicle_validated": False}


def output(args):
    record = json.loads(Path(args.inputs).read_text())
    verify_source_inputs(record, args.project)
    classes = []
    with zipfile.ZipFile(args.jar) as jar:
        for name in sorted(jar.namelist()):
            if not name.endswith(".class"):
                continue
            data = jar.read(name)
            magic, minor, major = struct.unpack(">IHH", data[:8])
            if magic != 0xCAFEBABE or major != 48:
                raise SystemExit("ERROR: non-Java-1.4 class: " + name)
            if name.startswith(("java/", "javax/", "org/osgi/", "com/ibm/")):
                raise SystemExit("ERROR: stock/JCL class leaked into payload: " + name)
            classes.append(name)
    if not classes:
        raise SystemExit("ERROR: empty patch JAR")
    record.update({"jar": identity(args.jar), "class_count": len(classes),
                   "class_major": 48, "classes": classes})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    inp = sub.add_parser("inputs")
    inp.add_argument("--stock", required=True)
    inp.add_argument("--jcl", default="")
    inp.add_argument("--firmware", required=True)
    inp.add_argument("--build-id", required=True)
    inp.add_argument("--expected-sha256", default="")
    out = sub.add_parser("output")
    out.add_argument("--jar", required=True)
    out.add_argument("--inputs", required=True)
    verify = sub.add_parser("verify-sources")
    verify.add_argument("--manifest", required=True)
    for command in (inp, out):
        command.add_argument("--output", required=True)
    for command in (inp, out, verify):
        command.add_argument("--project", type=Path, default=PROJECT)
    args = parser.parse_args()
    if args.mode == "verify-sources":
        verify_source_inputs(json.loads(Path(args.manifest).read_text()), args.project)
        print("Java source provenance: PASS")
        return
    result = inputs(args) if args.mode == "inputs" else output(args)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
