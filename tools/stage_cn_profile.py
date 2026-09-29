#!/usr/bin/env python3
"""Stamp a CN-only test package after checking its actual build evidence.

No proprietary inputs, absolute source paths, or vehicle logs go onto the card.
This is static/build validation, never a claim of an on-vehicle pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
from native_source_manifest import manifest as native_sources
from java_build_manifest import verify_source_inputs

TRAIN = "MHI2Q_CN_AUG22_P1002"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(build, sd):
    java = json.loads((build / "java-build.json").read_text())
    audit = json.loads((build / "cn-java-audit.json").read_text())
    native = json.loads((build / "native-evidence/cn-native-build.json").read_text())
    base = sd / "Toolbox/carplay_alt_screen"
    jar_hash = sha(base / "hmi/carplay_hook-basevideo3.jar")
    stock_hash = java["stock"]["sha256"]
    verify_source_inputs(java)
    checks = {
        "java_firmware": java.get("firmware") == TRAIN,
        "java_jar": java["jar"]["sha256"] == jar_hash,
        "java_class_version": java.get("class_major") == 48,
        "audit_status": audit.get("status") == "PASS",
        "audit_firmware": audit.get("firmware") == TRAIN,
        "audit_jar": audit.get("jar_sha256") == jar_hash,
        "audit_stock": audit.get("stock_sha256") == stock_hash,
        "audit_java_sources": audit.get("source_sha256") == java.get("source_sha256"),
        "native_status": native.get("status") == "PASS",
        "native_firmware": native.get("firmware") == TRAIN,
        "native_hook": native.get("hook_sha256") == sha(base / "rgi/libcarplay_hook.so"),
        "native_renderer": native.get("renderer_sha256") == sha(base / "rgi/maneuver_render"),
    }
    failed = [key for key, ok in checks.items() if not ok]
    for target in ("hook", "renderer"):
        recorded = json.loads((build / f"native-evidence/{target}-inputs-after.json").read_text())
        if recorded != native_sources(target):
            failed.append(target + "_source_changed_since_build")
    if failed:
        raise ValueError("CN build evidence mismatch: " + ", ".join(failed))
    (base / "CN_P1002_BUILD.txt").write_text(
        f"target_train={TRAIN}\n"
        "build_status=VERIFIED_PENDING_PACKAGE\n"
        "migration_policy=restore_previous_then_reboot_then_install\n"
        "vehicle_validated=NO\n"
        f"jar_sha256={jar_hash}\nstock_jar_sha256={stock_hash}\n"
        f"rgi_hook_sha256={native['hook_sha256']}\n"
        f"renderer_sha256={native['renderer_sha256']}\n"
    )
    (base / "CN_BUILD_CHECKS.json").write_text(json.dumps({
        "firmware": TRAIN, "build_id": java["build_id"],
        "checks": checks, "vehicle_validated": False,
        "note": "Build/linkage checks passed; verify full functionality in the vehicle.",
    }, indent=2) + "\n")
    (sd / "SD_CARD_README.txt").write_text("""CN P1002 / AltScreen + RGI 首轮试验包

目标固件：MHI2Q_CN_AUG22_P1002。已做本地构建和接口检查，尚未实车验证。
基线：https://github.com/jamespan/mib2-carplay-rgi-altscreen

从旧定制包迁移：
1. 先用旧包 STORE LOGS，再执行 RESTORE ORIGINAL，完整重启 MMI。
2. 确认原车地图恢复，再复制本包到 SD。保留 MMI-Cockpit-Carplay/backup 和 logs。
3. 如果装过独立 NavActiveIgnore 补丁，先用原工具卸载并完整重启。
4. Update Toolbox，退出再进入绿菜单。
5. MMI-Cockpit-Carplay -> INSTALL，PASS 后完整重启 MMI。
6. START，PASS 后再完整重启 MMI。

本包使用新 RGI/图层/缩放实现，不叠加旧 CPZ2 或 v36 灰框隐藏试验。
如带有 logo_pool.count，使用本地私有随机开屏；重新连接会重新抽取，随机可能重复。
先用有线高德验证导航信息、Classic/Sport、滚轮缩放、断开恢复，再比较无线。
连接时和断开后分别 STORE LOGS。新组合的高德数据完整性、Sport位置、30FPS和
无线音频仍待验证。INSTALL=PASS 只表示安装成功，不表示完整导航链路已实测成功。

SHA256SUMS-SD.txt 覆盖本包全部文件。不要复制未完成构建的目录。
不会自动弹出 SD 卡。
""")
    print("CN_PROFILE=PASS target=" + TRAIN + " vehicle_validated=NO")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--sd", required=True, type=Path)
    args = parser.parse_args()
    try:
        stage(args.build, args.sd)
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f"CN_PROFILE=FAIL {exc}\n")


if __name__ == "__main__":
    main()
