# CN P1002 集成分支

新基线为 Allemon 项目提交 `404ccc23450e385a0183d37fc93677a0c9a5637d`，
在 jamespan 的 fork 中继续维护。目标车机为 `MHI2Q_CN_AUG22_P1002`。

本分支保留上游的 RGI、AltScreen、上下文 80/81、方向盘缩放、布局菜单和
30 FPS 实现。上一版已有有线高德 RGI 实车结果；Sport 视频位置修复和透明转向卡片待实车验证。
**本地编译和测试通过不等于实车验证通过。**

## 与此前定制包的关系

| 项目 | 本分支处理 |
|---|---|
| 开屏图 | 当前使用项目自带 `logo.rgba`；16 张私有随机包保留为可选构建输入，默认不打包 |
| 高德导航自车右偏 | 关闭旧 safeArea 修正；上游 maneuver card on top 已让本车大图居中；保留重复手机请求标记修复 |
| Sport 图层 | 在上游单个 ScreenModule worker 中让视频层跟随 OEM 小图位置，回大图复位；开屏保持原点，待实车验证 |
| 导航道路、ETA、箭头和车道 | 有线已有路名、转向、距离及时间的实车结果；JYBOX-29 无线缺少 RGI，需对照详细日志定位，车道完整性也待验证 |
| RGI 转向卡片背景 | CarPlay 期间隐藏原厂银灰背景，保留透明箭头层；大图弹窗和仪表内提示均适用，断开后恢复原厂背景；待实车验证 |
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

## 已安装本项目时更新

已识别的本项目 CN 安装可直接 **Update Toolbox → INSTALL → 完整重启 MMI**，
不要求先 STORE LOGS + RESTORE。安装器核对项目所有权和已知组件身份；仅有同名目录
或 JAR 不足以被识别为可更新版本。更新保留布局、帧率选择和既有启动状态。

升级前先保存当前运行目录、JAR、RGI 文件、配置和状态。失败回退到升级前版本，
保留原厂 ORIGINAL 备份。若升级中断，下次 INSTALL 先恢复未完成的事务；
按屏幕提示重启后重试，不要把存在 pending 的半完成版本直接 START。
这条路径还需实车验证，宿主模拟测试不能代替车机断电恢复验证。

CN 安装锁使用原厂 `/ramdisk` 下的单个普通文件，避开 MMX `/tmp` 不能创建子目录、
共享内存文件类型不同的限制。
若旧包报 `CN install lock is invalid`，更新修复包后重新执行 **Update Toolbox**，
退出再进入绿菜单，然后 INSTALL。新脚本保留实际创建错误；若提示已有异常或遗留锁，
完整重启 MMI 后重试，不自动删除可能属于另一安装进程的锁。

首次安装或此前未启用时仍需 **INSTALL → 重启 → START → 重启**。
独立 STORE LOGS 只采集日志；STORE LOGS + RESTORE 仍是恢复原车操作。

## 从旧定制版迁移

新旧两套 JAR、缩放和图层控制器不能同时工作。首轮采用清理旧版后安装的方式，
不自动覆盖来源未知的配置。CN 安装前检查在任何车机写入之前执行；检测到
旧独立方案、无法识别的 JAR/runtime 或独立缩放加载项就停止，并提示先恢复。

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
本仓库已经编译就当成已更新。已识别的本项目版本使用上面的直接更新流程。

## 本轮实车检查

先用有线 CarPlay 做基线：连接和重新连接观察开屏；进入高德导航，检查道路/
距离/时间/转向提示；切换 Classic、Sport，检查地图位置、缩放及透明箭头的可读性；
确认 CarPlay 提示不带银灰底，断开后原车导航提示仍有正常背景；
结束导航和断开 CarPlay，确认原车地图恢复。连接期间和断开后分别 STORE LOGS。
之后再对照 JYBOX-29 无线、播客音频和缩放，避免把无线盒子限制当成 CN 编译问题。

有线 RGI 的箭头、距离和时间已有实车照片，但高德数据完整性、新 Sport 小图位置、
30 FPS 与无线音频的共同负载仍是待验证项。不要只凭菜单 INSTALL=PASS 判断 RGI 已通。

Sport 修复将 displayable 3 跟随 OEM `Layout` 的小图偏移（本车为 `-476, 0`），
不修改手机地图安全区。只有 sidecar 首个真实视频帧成功、ready 记录为 `direct-display`
并与当前 PID 文件一致时才允许偏移。sidecar 仅在首帧更新该标记，不逐帧写文件。
下一会话显示开屏前由同一 Java worker 确认复位；拿不到确认时记录失败，不带着旧偏移显示开屏。

## 单独采集 RGI / Sport 日志

将新版脚本和菜单放到 SD 后执行 **Update Toolbox**，退出再进入绿菜单。
新增 **STORE LOGS (keep CarPlay running)** 直接使用更新后的 Toolbox 脚本，
不需要重新 INSTALL / START，不会卸载、断开 CarPlay 或重启 MMI。
原来的 **STORE LOGS + RESTORE** 仍会在采集后恢复原车；仅排查问题时不要选它。

1. 先点一次 **STORE LOGS**：立即保留现有日志，并在 MMX 的 RAM 中创建
   `/tmp/carplay_verbose`，让下一次连接记录 INFO 级协商和 RGI 状态。
2. 断开再连接**有线 CarPlay**，在高德开始导航，切换大图和 Sport，点
   **STORE LOGS** 保存第一份；记下这份 `COLLECT_DIR` 对应有线。
3. 改用 **JYBOX-29 无线**，同一地图 App 开始导航并复现问题，再点
   **STORE LOGS** 保存第二份；两轮采集之间不要重启 MMI，避免 RAM 日志丢失。
4. 结束后可点 **CARPLAY VERBOSE OFF**，再重连 CarPlay 恢复默认日志级别。
   它只删除本采集器创建的临时标志；已有持久 `/mnt/app/carplay_verbose`
   会单独提示并保留。临时标志本身也会随重启消失。

每次结果保存在 SD 的 `MMI-Cockpit-Carplay/logs/rgi/collect_N/`，编号递增，
旧目录不覆盖。保存 hook、Java、renderer、wrapper、AltScreen 的有界日志及轮转，
ready / ctx / geom / layout 状态、两份运行配置和有超时限制的进程/加载库快照。
只采集指定文件，不复制共享内存、视频环、原厂固件、封面图片或 core dump。
`info.txt` 记录缺失、截断和探测失败，**没有文件不等于没有协议数据**。
`PASS` 仅表示采集完成，不表示 RGI 或 Sport 已通过实车验证。

有线、无线比较重点是：Identify 是否声明 RGI、是否发出 `0x5200`、是否收到
`0x5201/2/4`，以及 Java 是否进入 `RG activate`。默认 WARN/ERROR 日志不能
用于证明这些 INFO 级事件没有发生。

实现与证据入口：[CN Java 适配](docs/cn-java-port.md)、[私有开屏](docs/private-splash.md)、
[CN 原生接口与几何](docs/cn-p1002-native.md)、
`build/java-build.json`、`build/cn-java-audit.json`、
`build/native-evidence/cn-native-build.json`。
