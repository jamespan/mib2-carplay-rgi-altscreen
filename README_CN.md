# CN P1002 集成分支

新基线为 Allemon 项目提交 `404ccc23450e385a0183d37fc93677a0c9a5637d`，
在 jamespan 的 fork 中继续维护。目标车机为 `MHI2Q_CN_AUG22_P1002`。

本分支保留上游的 RGI、AltScreen、上下文 80/81、方向盘缩放、布局菜单和
30 FPS 实现。**本地编译和测试通过不等于已经实车验证；该组合是首轮试验版。**

## 与此前定制包的关系

| 项目 | 本分支处理 |
|---|---|
| 开屏图 | 当前使用项目自带 `logo.rgba`；16 张私有随机包保留为可选构建输入，默认不打包 |
| 高德导航自车右偏 | 当前关闭旧 safeArea 修正，先验证上游布局选择器；保留重复手机请求标记修复，可用 `CN_MAP_SAFEAREA=1` 恢复居中补丁 |
| Sport 图层 | 使用上游的新 Java 图层管理；不复制旧版 Sport 像素平移控制器，需重新验证小图位置 |
| 导航道路、ETA、箭头和车道 | 使用上游 RGI 链路；手机/高德是否提供完整数据仍需实车采集 |
| 灰底栏试验 | 不带入 v36 的功能支持撤回、路名清空和罗盘隐藏试验；新基线用底栏显示手机导航信息 |
| 滚轮缩放 | 使用上游命令总线，不保留旧独立 CPZ2 控制器；不承诺解决 JYBOX-29 不转发缩放 |
| 无水印 | 保持上游透明水印处理 |
| 原厂动态库 | 不把原厂 CarPlay/NME 库替换成其他固件版本；新增独立 hook 和 renderer |

## 构建

原厂 JXE/JAR、动态库、个人图片与车机日志都留在本地，**不要提交到 GitHub**。
`build/`、`local_firmware/`、`local_assets/` 已忽略。

需要本车完整转换出的 stock JAR（包含 JCL/OSGi）、JDK 8 编译环境、带 C++
前端和标准头文件的 QNX GCC 8.5 工具链，以及宿主 LLVM 检查工具。
Java 检查工具可使用宿主 JDK 8 或更新 JDK；它不会把分析工具装进车机。

```sh
STOCK_JAR=/private/path/CN_P1002-combined.jar \
CN_STOCK_DIR=/private/path/CN-Port-Inputs \
CN_LLVM_BIN=/path/to/llvm/bin \
QNX_IMAGE=your-qnx65-c-and-cpp-image \
bash scripts/build_cn.sh
```

不设置 `PRIVATE_LOGO_DIR` 时沿用上游单张开屏；设置 `ALTSCREEN_FULL_FPS=0`
可构建使用原始读帧/轮询节奏的对照版本。
若以后恢复随机开屏，可另加 `PRIVATE_LOGO_DIR="$PWD/local_assets/mixed16"`。
`CN_MAP_SAFEAREA` 默认 `0`，使用上游原始安全区；设置为 `1` 可重新启用
此前验证过的中央 480 像素安全区。它是构建开关，GEM 的 `AltScreen default`
只取消额外布局请求，不会切换这个补丁。两种版本都保留重复手机请求标记修复。
`SKIP_BUILD=1 bash scripts/build_cn.sh` 可重用本地已有产物，但打包仍要求 CN
Java/native 审核报告通过，且与实际文件 SHA256 一致。

产物在 `build/sd/`，`SHA256SUMS-SD.txt` 覆盖全部文件，包括私有开屏。
生成的 `CN_P1002_BUILD.txt` 限定安装车机版本，并明确 `vehicle_validated=NO`。
包内不包含用于编译的原厂 JAR/动态库或本车日志。

## 从旧定制版迁移

新旧两套 JAR、缩放和图层控制器不能同时工作。首轮采用清理旧版后安装的方式，
不自动覆盖正在使用的旧版配置。CN 安装前检查在任何车机写入之前执行；检测到
旧 JAR、runtime 或独立缩放加载项就停止，并提示先恢复。

1. **先保留旧 SD 包，用车上已安装的旧版执行 STORE LOGS，再 RESTORE ORIGINAL。**
2. 完整重启 MMI，确认仪表原车地图正常。
3. 把新包 `build/sd/` 内容放到 SD 根目录，保留原有
   `MMI-Cockpit-Carplay/backup` 和日志，不格式化、不删除该目录。
4. 执行 **Update Toolbox**，退出再进入绿菜单。
5. 进入 **MMI-Cockpit-Carplay → INSTALL**，看到 PASS 后完整重启 MMI。
6. 执行 **START**，看到 PASS 后再完整重启 MMI。

如果另外安装过独立的 `NavActiveIgnore.jar`，也先用原来的工具卸载并重启；
新项目已包含相应功能，沿用上游不同时安装这份独立旧补丁的策略。安装前检查
会提示这项旧安装，不会自动删除来源未知的文件。

SD 写入与弹出是独立操作；构建脚本默认只生成本地包。旧版 v36 的 SD 不能仅凭
本仓库已经编译就当成已更新。相同/后续 CN 版本重装也先 RESTORE，再重启安装。

## 第一轮实车检查

先用有线 CarPlay 做基线：连接和重新连接观察开屏；进入高德导航，检查道路/
距离/时间/转向提示；切换 Classic、Sport，检查地图位置、缩放及箭头遮挡；
结束导航和断开 CarPlay，确认原车地图恢复。连接期间和断开后分别 STORE LOGS。
之后再对照 JYBOX-29 无线、播客音频和缩放，避免把无线盒子限制当成 CN 编译问题。

高德数据是否完整、CN renderer 在真实 Screen/EGL 上的加载、新 Sport 小图位置、
30 FPS 与无线音频的共同负载都是待验证项。不要只凭菜单 INSTALL=PASS 判断 RGI 已通。

实现与证据入口：[CN Java 适配](docs/cn-java-port.md)、[私有开屏](docs/private-splash.md)、
[CN 原生接口与几何](docs/cn-p1002-native.md)、
`build/java-build.json`、`build/cn-java-audit.json`、
`build/native-evidence/cn-native-build.json`。
