#!/usr/bin/env python3
"""Generate CN P1002 sources from upstream sources without editing that baseline.

Changes match the real CN LSD member descriptors and resource-request bytecode.
Every replacement is counted; upstream drift fails instead of silently patching.
See docs/cn-java-port.md for original ABI evidence and remaining validation.
"""
import argparse
import difflib
import hashlib
import json
import shutil
from pathlib import Path


def adapt(relative, source):
    edits = []
    def replace(before, after, count=1):
        nonlocal source
        actual = source.count(before)
        if actual != count:
            raise ValueError(f"{relative}: expected {count} occurrence(s), got {actual}: {before!r}")
        source = source.replace(before, after)
        edits.append({"before": before, "after": after, "count": count})
    if relative == "de/audi/app/terminalmode/ExternalEventsListener.java":
        replace("    private IDSISmartphoneManager.ISmartphoneProperties smartphoneProperties;\n", "")
        replace("        IDispatcher dispatcher,\n        IDSISmartphoneManager.ISmartphoneProperties smartphoneProperties", "        IDispatcher dispatcher")
        replace("        this.smartphoneProperties = smartphoneProperties;\n", "")
        replace("                    ExternalEventsListener.this.smartphoneProperties\n                        .getPropertyMUHFPPhonecallActive()\n                        .accept(new Boolean(telState.getCallActive()));\n", "")
    elif relative == "de/audi/app/terminalmode/interapp/HighPriorityResourceTracker.java":
        replace("import de.audi.atip.interapp.bap.ecall.data.EmergencyNumber;\n", "")
        replace("    private final IDSISmartphoneManager.ISmartphoneProperties smartphoneProperties;\n", "")
        replace("        PropertyFactory propertyfactory,\n        IDSISmartphoneManager.ISmartphoneProperties idsismartphonemanager$ismartphoneproperties", "        PropertyFactory propertyfactory")
        replace("        this.smartphoneProperties = idsismartphonemanager$ismartphoneproperties;\n", "")
        for indent, value in (("                    ", "Boolean.FALSE"), ("            ", "new Boolean(false)"), ("        ", "new Boolean(true)")):
            replace(indent + "this.smartphoneProperties.getPropertyMURVCActive().accept(" + value + ");\n", "")
        replace("        public EmergencyNumber[] getAllowedEmergencyNumbers() {\n            return new EmergencyNumber[0];\n        }\n\n", "")
    elif relative == "de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController.java":
        for name in ("getDSITakeType", "getDSITakeConstraint", "getDSIBorrowConstraint", "getDSIUnborrowConstraint"):
            replace(name + "(flag)", name + "()")
        replace("aidsiresource[i].getDSITransferPriority(flag)", "(flag ? 2 : 1)")
    elif relative == "de/esolutions/hmi/widgets/audi/evo/high/PartialPopupManagerEvoHigh.java":
        replace("AbstractPartialPopupManager", "PartialPopupManager", 2)
    return source, edits


def prepare(source_root, output):
    source_root, output = Path(source_root), Path(output)
    if output.resolve() == source_root.resolve() or source_root.resolve() in output.resolve().parents:
        raise ValueError("output must not overwrite or be inside java_patch")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    report = []
    for path in sorted(source_root.rglob("*.java")):
        relative = path.relative_to(source_root).as_posix()
        original = path.read_text()
        adapted, edits = adapt(relative, original)
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(adapted)
        if edits:
            report.append({"path": relative, "upstream_sha256": hashlib.sha256(original.encode()).hexdigest(),
                           "generated_sha256": hashlib.sha256(adapted.encode()).hexdigest(), "edits": edits})
            (output / (path.name + ".diff")).write_text("".join(difflib.unified_diff(original.splitlines(True), adapted.splitlines(True), fromfile="upstream/" + relative, tofile="cn-p1002/" + relative)))
    if len(report) != 4:
        raise ValueError("CN adaptation requires exactly four upstream source files")
    (output / "adaptations.json").write_text(json.dumps({"firmware": "MHI2Q_CN_AUG22_P1002", "adaptations": report}, indent=2) + "\n")
    print("CN P1002: generated four ABI adaptations; upstream java_patch is unchanged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    prepare(args.source, args.output)
