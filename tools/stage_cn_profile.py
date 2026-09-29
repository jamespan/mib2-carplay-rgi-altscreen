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
from patch_cn_altscreen import CN_SHA, CN_MARKER_SHA, normalized
from patch_video_phase import patch as patch_video_phase

TRAIN = "MHI2Q_CN_AUG22_P1002"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(build, sd, map_safearea=False):
    java = json.loads((build / "java-build.json").read_text())
    audit = json.loads((build / "cn-java-audit.json").read_text())
    native = json.loads((build / "native-evidence/cn-native-build.json").read_text())
    base = sd / "Toolbox/carplay_alt_screen"
    jar_hash = sha(base / "hmi/carplay_hook-basevideo3.jar")
    stock_hash = java["stock"]["sha256"]
    altscreen = base / "universal/libcarplay_altscreen.so"
    mirror = base / "mirror_display/release/carplay-alt111-mirror-display"
    mirror_bytes = mirror.read_bytes()
    expected_overlay = CN_SHA if map_safearea else CN_MARKER_SHA
    private_pool = (base / "mirror_display/release/logo_pool.count").is_file()
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
        "altscreen_geometry_mode": hashlib.sha256(normalized(altscreen.read_bytes())).hexdigest() == expected_overlay,
        "mirror_first_video_marker": patch_video_phase(mirror_bytes) == mirror_bytes,
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
        "migration_policy=upgrade_known_project_restore_legacy\n"
        "vehicle_validated=NO\n"
        f"cn_map_safearea={int(map_safearea)}\nphone_request_marker=repeat\n"
        f"altscreen_hook_sha256={sha(altscreen)}\n"
        f"mirror_sha256={sha(mirror)}\nmirror_first_video_marker=1\nsport_video_layout=1\n"
        "maneuver_backing=transparent_carplay_stock_restore\n"
        f"startup_logo={'private_random_pool' if private_pool else 'upstream'}\n"
        f"jar_sha256={jar_hash}\nstock_jar_sha256={stock_hash}\n"
        f"rgi_hook_sha256={native['hook_sha256']}\n"
        f"renderer_sha256={native['renderer_sha256']}\n"
    )
    (base / "CN_BUILD_CHECKS.json").write_text(json.dumps({
        "firmware": TRAIN, "build_id": java["build_id"],
        "checks": checks, "vehicle_validated": False,
        "cn_map_safearea": bool(map_safearea),
        "sport_video_layout": True, "mirror_sha256": sha(mirror),
        "maneuver_backing": "transparent_carplay_stock_restore",
        "startup_logo": "private_random_pool" if private_pool else "upstream",
        "note": "Build/linkage checks passed; verify full functionality in the vehicle.",
    }, indent=2) + "\n")
    geometry_note = ("本包启用旧 CN safeArea 居中修正。" if map_safearea else
        "本包关闭旧 CN safeArea 居中修正，继续使用上游布局选择器。")
    logo_note = ("本包包含私有随机开屏；重新连接会重新抽取，随机可能重复。" if private_pool else
        "本包使用项目自带 logo.rgba，不包含私有随机开屏包。")
    (sd / "SD_CARD_README.txt").write_text(f"""CN P1002 / AltScreen + RGI / 透明转向提示试验包

目标固件：MHI2Q_CN_AUG22_P1002。已做本地构建和接口检查，尚未实车验证。
基线：https://github.com/jamespan/mib2-carplay-rgi-altscreen

从已安装的本项目 CN 版本更新：
1. 保留 SD 的 MMI-Cockpit-Carplay/backup 和 logs。复制本包后执行 Update Toolbox，退出再进入绿菜单。
2. 已识别为本项目的 CN 版本可直接 INSTALL，不需要先 RESTORE；安装器先保存升级前状态，失败时回退。
3. INSTALL 显示 PASS 后完整重启 MMI，使新的 JAR 和动态库生效。
4. 首次安装或此前未启用时，执行 START，PASS 后再完整重启 MMI。
旧独立方案、未知改装或独立 NavActiveIgnore 补丁不能当作本项目覆盖更新；根据安装器提示处理后重试。
仅排查日志时使用独立 STORE LOGS，STORE LOGS + RESTORE 仍会卸载当前安装。

本包使用新 RGI/图层/缩放实现，不叠加旧 CPZ2 或 v36 灰框隐藏试验。
{geometry_note}
更新会保留既有布局设置；首次安装选择 maneuver card on top 并重新连接手机。该选项此前已让本车高德大图居中。
保留 Sport 小图的视频位置同步，回大图/断开时复位；开屏阶段保持原点。
本次隐藏 CarPlay RGI 转向提示的银灰背景，保留箭头；大图弹窗和仪表内提示均适用。
断开 CarPlay 后按原厂状态恢复背景。请实车检查布局切换、导航结束和断开后的显示。
Sport 位置和透明背景需实车验证，不能把本地测试结果当作实车通过。
手机请求标记修复和帧率设置不受 safeArea 开关影响。
{logo_note}
有线 RGI 的箭头、距离、时间和路名已有实车照片；无线 JYBOX-29 缺少 RGI 的原因待采集。
新增 STORE LOGS (keep CarPlay running) 只保存现场，不恢复或重启，Update Toolbox 后即可用。
先点一次 STORE LOGS 开启临时详细日志，再重新连接有线高德导航，切换大图/Sport并再次 STORE LOGS。
然后换无线并复现，再次 STORE LOGS。两轮之间不重启 MMI；记录有线/无线对应 collect_N 编号。
目录：MMI-Cockpit-Carplay/logs/rgi/collect_N/。CARPLAY VERBOSE OFF 可关闭临时详细日志，重连后生效。
STORE LOGS + RESTORE 仍会恢复原车，仅采集时不要选错。
INSTALL=PASS 只表示安装成功，STORE_LOGS=PASS 只表示日志保存成功。

SHA256SUMS-SD.txt 覆盖本包全部文件。不要复制未完成构建的目录。
不会自动弹出 SD 卡。
""")
    print("CN_PROFILE=PASS target=" + TRAIN + " vehicle_validated=NO")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--sd", required=True, type=Path)
    parser.add_argument("--map-safearea", choices=('0', '1'), default='0')
    args = parser.parse_args()
    try:
        stage(args.build, args.sd, map_safearea=args.map_safearea == '1')
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f"CN_PROFILE=FAIL {exc}\n")


if __name__ == "__main__":
    main()
