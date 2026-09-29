#!/usr/bin/env python3
"""Stale or incomplete Java source provenance must not authorize SD staging."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("java_build_manifest", Path(__file__).resolve().parents[1] / "tools/java_build_manifest.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SourceProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("scripts/build_java.sh", "scripts/compile_java.sh", "tools/prepare_cn_java.py",
                     "tools/java_build_manifest.py", "java_patch/Test.java", "java_resources/metrics.bin"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        sources = MODULE.source_inputs(self.root)
        self.record = {"source_inputs": sources, "source_sha256": MODULE.source_digest(sources)}

    def test_unchanged_inputs(self):
        self.assertTrue(MODULE.verify_source_inputs(self.record, self.root))

    def test_changed_java_resource_and_build_tools(self):
        for name in self.record["source_inputs"]:
            with self.subTest(name=name):
                path = self.root / name
                before = path.read_bytes()
                path.write_bytes(before + b"changed")
                with self.assertRaisesRegex(ValueError, "changed since build"):
                    MODULE.verify_source_inputs(self.record, self.root)
                path.write_bytes(before)

    def test_added_java_source(self):
        (self.root / "java_patch/Added.java").write_text("class Added {}")
        with self.assertRaisesRegex(ValueError, "changed since build"):
            MODULE.verify_source_inputs(self.record, self.root)

    def test_deleted_resource(self):
        (self.root / "java_resources/metrics.bin").unlink()
        with self.assertRaisesRegex(ValueError, "changed since build"):
            MODULE.verify_source_inputs(self.record, self.root)

    def test_missing_or_corrupt_manifest(self):
        with self.assertRaisesRegex(ValueError, "no source provenance"):
            MODULE.verify_source_inputs({}, self.root)
        self.record["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "aggregate"):
            MODULE.verify_source_inputs(self.record, self.root)


if __name__ == "__main__":
    unittest.main()
