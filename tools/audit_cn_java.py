#!/usr/bin/env python3
"""Check the built CN JAR against all CN stock callers and run upstream RGI tests.

Uses the JDK's bundled ASM only for local analysis, never in the vehicle JAR.
Host probes needing reconstructed J9 bytecode use -Xverify:none; this is not a
J9 or hardware validation. A PASS binds the exact stock and patch SHA-256.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from java_build_manifest import verify_source_inputs

TESTS = [
    ("CnResourceRequestTest", True),
    ("com.luka.carplay.rgd.VCTextScrollTest", False),
    ("RouteInfoPresentationTest", False),
    ("RendererMapperDirectionTest", False),
    ("RouteGuidanceDeltaTest", False),
    ("DistanceBargraphChainTest", True), ("KomoGraphicsStateTest", True),
    ("ManeuverParityTest", True), ("RendererViewportTest", True),
    ("ClusterKdkSyncTest", True), ("ClusterKdkBackingTest", True),
    ("AltScreenContextTest", True),
    ("AltScreenVideoLayoutTest", True),
    ("ClusterKdkBapChainTest", True), ("ClusterKdkRendererLifecycleTest", True),
    ("com.luka.carplay.rgd.LaneGuidanceTransportTest", True),
    ("com.luka.carplay.rgd.LaneGuidanceLifecycleTest", True),
    ("com.luka.carplay.rgd.RgiDeliveryRecoveryTest", True),
    ("com.luka.carplay.rgd.CurrentPositionDeliveryTest", True),
    ("com.luka.carplay.rgd.RouteInfoTimeoutTest", True),
    ("com.luka.carplay.rgd.CurrentPositionStockChainTest", True),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--stock", required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--javac", default="javac")
    args = parser.parse_args()
    root = Path(args.project).resolve()
    stock = Path(args.stock).resolve()
    patch = root / "build/carplay_hook.jar"
    out = root / "build/cn-java-audit"
    out.mkdir(parents=True, exist_ok=True)
    classes = out / "classes"
    classes.mkdir(exist_ok=True)
    report_path = root / "build/cn-java-audit.json"
    report = {"firmware": "MHI2Q_CN_AUG22_P1002", "status": "FAIL", "errors": [],
              "vehicle_validated": False, "tests": [],
              "limitations": ["Host tests are not a J9 class-load or vehicle validation",
                              "Reconstructed stock methods need relaxed HotSpot verification in selected probes"]}
    # Invalidate a previous PASS before any potentially failing work.
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    def run(command, name, cwd=None, timeout=120):
        p = subprocess.run(list(map(str, command)), cwd=cwd or root, capture_output=True, text=True, timeout=timeout)
        (out / (name + ".log")).write_text(p.stdout + p.stderr)
        if p.returncode:
            raise RuntimeError(name + " failed (see " + str(out / (name + ".log")) + ")")
        return p.stdout + p.stderr

    try:
        report.update(jar_sha256=sha(patch), stock_sha256=sha(stock))
        manifest = json.loads((root / "build/java-build.json").read_text())
        verify_source_inputs(manifest, root)
        report["source_sha256"] = manifest["source_sha256"]
        if manifest["firmware"] != report["firmware"]:
            raise ValueError("Java build is not identified as CN P1002")
        if manifest["jar"]["sha256"] != report["jar_sha256"] or manifest["stock"]["sha256"] != report["stock_sha256"]:
            raise ValueError("Built JAR/stock do not match java-build.json")
        if not manifest.get("jcl") or manifest["jcl"]["sha256"] != report["stock_sha256"]:
            raise ValueError("CN audit requires the complete CN JXE's own JCL")
        if manifest["stock_class_count"] != 30348:
            raise ValueError("Expected the complete 30348-class CN P1002 stock, not a stub JAR")
        version = run([args.javac, "-version"], "javac-version").strip()
        report["audit_compiler"] = version
        jdk8 = version.startswith("javac 1.8.")
        exports = [] if jdk8 else [arg for package in ("asm", "asm.tree") for arg in ("--add-exports", "java.base/jdk.internal.org.objectweb." + package + "=ALL-UNNAMED")]
        source = (root / "tests/JavaStockLinkageAudit.java").read_text().replace("org.objectweb.asm", "jdk.internal.org.objectweb.asm").replace("n : m.instructions)", "n : m.instructions.toArray())")
        audit_source = out / "JavaStockLinkageAudit.java"
        audit_source.write_text(source)
        run([args.javac, *(["-XDignore.symbol.file"] if jdk8 else exports), "-d", classes, audit_source], "compile-linkage")
        linkage = run([args.java, *exports, "-Xmx2g", "-cp", classes, "JavaStockLinkageAudit", patch, stock], "linkage")
        counts = re.search(r"(\d+) patch classes / (\d+) remaining stock classes; links patch=(\d+) stock=(\d+); errors=(\d+)", linkage)
        if not counts or int(counts[5]):
            raise ValueError("Missing successful full-stock linkage summary")
        report["linkage"] = dict(zip(("patch_classes", "remaining_stock_classes", "patch_links", "stock_links", "errors"), map(int, counts.groups())))
        cp = str(patch) + ":" + str(stock)
        sources = [root / "tests" / (name.split(".")[-1] + ".java") for name, _ in TESTS]
        sources.append(root / "tests/ManeuverChainAudit.java")
        run([args.javac, "-encoding", "UTF-8", "-cp", cp, "-d", classes, *sources], "compile-tests")
        for name, relaxed in TESTS:
            command = [args.java, *(["-Xverify:none"] if relaxed else []), "-cp", str(classes) + ":" + cp, name]
            if name.endswith("LaneGuidanceTransportTest"):
                command.append(str(out / "lane-guidance-wire.bin"))
            run(command, name, cwd=out)
            report["tests"].append({"name": name, "status": "PASS", "converted_stock_verifier_disabled": relaxed})
            print(name + ": PASS", flush=True)
        if sha(patch) != report["jar_sha256"] or sha(stock) != report["stock_sha256"]:
            raise ValueError("Inputs changed during audit")
        verify_source_inputs(manifest, root)
        report["status"] = "PASS"
    except (Exception, KeyboardInterrupt) as error:
        report["errors"].append(str(error))
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print("CN Java audit: " + report["status"] + "; " + str(report_path))
    if report["errors"]:
        print("\n".join(report["errors"]))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
