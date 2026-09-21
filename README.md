<div align="center">
<img src="./logo.png" width="100" alt="AndroidBox Logo"/>
<h2>AndroidBox</h2>
</div>

### 一、功能简述

AndroidBox 是基于 [Waydroid](https://github.com/waydroid/waydroid) 改造的 **Android 窗口化运行工具**，保留 Linux 原生容器后端，并提供基于 Qt、QEMU 和 noVNC 的跨平台桌面客户端。

- **窗口化界面**：内嵌 noVNC 显示，支持全屏、运行日志和虚拟机设置。
- **虚拟机管理**：配置磁盘、架构、内存、CPU 和固件，支持启动、正常关机与强制停止。
- **QEMU 兼容层**：探测 Linux KVM、macOS HVF、Windows WHPX；自动模式在跨架构或未发现可用硬件加速时回退 TCG。
- **APK 安装**：通过经过设备授权的 ADB 安装应用，优先使用安装包内置的 ADB。
- **原生 Linux 后端**：保留基于 LXC、Binder 和 Wayland 的 Android 容器运行方式。
- **统一应用标识**：软件名称为 AndroidBox，应用 ID 为 `org.mutantcat.androidbox`。

**当前版本：`1.0.20260923`。** 安装包构建流程已配置内置 Python、Qt、noVNC、QEMU 和 ADB；完整 Android 磁盘体积过大（每架构 220–250 MiB，且几乎无法压缩），不放入安装包。首次启动点击界面上的 **Prepare example guest disk** 即可：下载固定版本 Ubuntu 24.04 minimal 镜像、校验官方 SHA256，并生成客户端可自动识别的 QCOW2 磁盘，之后按 [客体镜像文档](./docs/guest-image.md) 完成 Android 客体配置。官方源不可达时自动回退到国内镜像，也可用 **Use a local image** 选择已下载的镜像。本次版本修复了示例盘 QCOW2 叠加层底层格式识别错误导致的 UEFI Shell 启动问题，并会在启动前自动修复已有磁盘。

### 二、平台支持

| 平台 | 架构 | 虚拟化后端 | 安装包格式 | 验证状态 |
| --- | --- | --- | --- | --- |
| Windows | x86_64 | QEMU / WHPX、TCG | NSIS `.exe` | 原生 CI 安装、应用自检和卸载通过 |
| macOS | Apple Silicon / ARM64 | QEMU / HVF、TCG | ad-hoc 签名 `.dmg` | CI 签名、挂载自检及本机固件启动通过 |
| macOS | Intel / x86_64 | QEMU / HVF、TCG | ad-hoc 签名 `.dmg` | 原生 CI 签名、挂载和应用自检通过 |
| Linux | x86_64 | QEMU / KVM、TCG | `.AppImage` | 原生 CI 提取和应用自检通过 |
| Linux | ARM64 / aarch64 | QEMU / TCG（公共 runner 无 KVM） | `.AppImage` | 原生 ARM runner 提取和应用自检（无 KVM，仅 `--version` 校验） |
| Linux 原生容器 | 依赖宿主内核与镜像 | LXC / Binder / Wayland | 源码安装 | 保留上游后端，仍需宿主验证 |

本地 macOS ARM64 上已运行准备好的 Ubuntu/Android 客体，并验证 Android 启动器显示、键盘输入、ADB 授权、测试 APK 安装及正常关机。鼠标定位、SystemUI 启动异常和共享存储仍存在问题，不能将该结果视为完整 Android 兼容性认证。

安装与兼容性注意事项：

- macOS 的 ad-hoc 签名不是 Developer ID 签名或 Apple 公证，下载后的应用仍可能被 Gatekeeper 阻止；本机 QEMU 面向 macOS 26 构建，不能据此保证旧系统兼容。
- Windows 安装器尚未使用代码签名证书，可能出现 SmartScreen 提示。
- Linux AppImage 面向较新 glibc（x86_64 基于 Ubuntu 22.04 / glibc 2.35 构建，aarch64 基于 Ubuntu 24.04 / glibc 2.39 构建）和桌面会话，可能需要执行权限、FUSE2，或使用 `APPIMAGE_EXTRACT_AND_RUN=1`。
- 硬件加速需要宿主支持并启用对应虚拟化能力；TCG 性能可能明显低于硬件加速。

详细测试记录见 **[验证文档](./docs/verification.md)**。CI 自检不代表所有干净机器、硬件加速或完整 Android 客体兼容性已通过认证。

### 三、快速上手

#### 桌面安装包

最近发布的完整版本是 [v1.0.20260923](https://github.com/Mutantcat-Working-Group/AndroidBox/releases/tag/v1.0.20260923)，包含五平台安装包及 `SHA256SUMS`。[标签触发的完整发布流水线](https://github.com/Mutantcat-Working-Group/AndroidBox/actions/runs/35565520650) 已通过；当前源码版本为 `1.0.20260923`。

1. 选择对应系统和架构的安装包，安装或启动 AndroidBox。
2. 首次打开会提示没有客体磁盘，点击 **Prepare example guest disk**。程序下载官方 Ubuntu 24.04 minimal 镜像、校验 SHA256，并在应用数据目录生成客户端可自动识别的 `androidbox-架构.qcow2`，全程不需要命令行。若所在网络访问官方源失败，可改用 **Use a local image** 选择已下载的同名镜像，校验方式完全相同。
3. 准备完成后点击 **Start**，程序自动选中刚生成的磁盘并进入运行视图；与宿主不同架构的客体仍需在设置中选择架构。
4. 启动虚拟机；安装 APK 前，在 Android 中确认 ADB 授权提示。

客体磁盘就绪后，按 [客体镜像文档](./docs/guest-image.md) 在虚拟机内完成 Android 客体配置（安装 Binder 模块、Waydroid 依赖并运行 `guest/provision.sh`）。

下载失败时的处理：准备过程会依次尝试官方源和两个国内镜像，并在三者之间自动重试、支持断点续传；TLS 校验使用安装包内置的 CA 证书，不依赖宿主系统的 OpenSSL 配置。仍失败时，错误框的 Details 会列出每个镜像的原因，可据此改用本地镜像或代理。

日志栏默认收起，可通过工具栏按钮展开。首次启动按宿主架构填写客体架构，CPU 默认取逻辑核心数的一半（1–6 核），内存取总内存的一半并按 GiB 向下取整（1–6 GiB）；无法检测时使用 2 核、2 GiB。已有设置不会被覆盖。性能相关设置还有 CPU 型号（host/max/qemu64）、TCG 线程数（单线程/多线程）和磁盘缓存（writeback/none/unsafe），均可在设置中调整，默认值保持原有行为。

QEMU 和 ARM 固件自动查找，设置中显示检测路径而不把安装位置写死；手动填写的路径优先。首次无配置时，也会查找应用数据目录下 `guests/androidbox-架构.qcow2` 或 `.raw`，其中架构为 `aarch64` 或 `x86_64`。不会扫描任意用户目录；只有点击 **Prepare example guest disk** 或 **Use a local image** 时才会下载或生成磁盘，生成的示例盘之后会被自动识别，无需再手动选择。

#### 从源码启动

需要 Python 3.10+、支持 VNC/WebSocket 的 QEMU；APK 安装还需要 Android SDK Platform Tools 中的 `adb`。

```sh
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 使用：.venv\Scripts\Activate.ps1
python scripts/fetch_novnc.py
python -m pip install -e '.[desktop]'
python -m androidbox
```

也可使用 `androidbox-desktop` 启动 Qt 客户端。源码运行时通过系统包管理器安装 QEMU，Windows 可安装 QEMU 后在设置中指定可执行文件或加入 PATH。noVNC 下载固定版本并校验归档；构建 wheel 前需先执行 `fetch_novnc.py`，以包含前端资源及许可证。

#### Linux 原生容器

原生后端依赖 LXC、支持 Binder 的内核、Wayland、D-Bus、PyGObject、python3-gbinder、polkit、PulseAudio/PipeWire-Pulse、iptables 和 dnsmasq。发行版依赖见 [debian/control](./debian/control) 和 [Waydroid 文档](https://docs.waydro.id)。

```sh
sudo make install
sudo make install_apparmor  # 使用 AppArmor 的宿主执行
sudo systemctl daemon-reload
sudo androidbox init
sudo systemctl enable --now androidbox-container
androidbox show-full-ui
androidbox app install example.apk
```

`androidbox` 是 Linux 原生命令，`androidbox-desktop` / `python -m androidbox` 是跨平台 Qt 客户端。客户端的 Linux 原生入口会启动独立 Android 窗口，不会把已有 Wayland 窗口嵌入 noVNC。

### 四、构建与发布

#### 本地构建

必须在目标系统上原生构建，PyInstaller 不进行跨平台编译。发布脚本建议使用 Python 3.12，至少需要 Python 3.11。

```sh
python scripts/fetch_novnc.py
python scripts/fetch_platform_tools.py
python -m pip install '.[desktop,build]'
```

构建时通过环境变量指定运行时位置：

| 环境变量 | 用途 | CI 配置 |
| --- | --- | --- |
| `ANDROIDBOX_QEMU_PREFIX` | QEMU 安装前缀，包含二进制、固件、数据和许可证 | Linux `/usr`；macOS Homebrew；Windows Chocolatey |
| `ANDROIDBOX_ADB_DIRECTORY` | 包含 ADB 及许可证的 Platform Tools 目录 | `build/platform-tools` |

macOS 示例：

```sh
ANDROIDBOX_QEMU_PREFIX="$(brew --prefix qemu)" \
ANDROIDBOX_ADB_DIRECTORY="$PWD/build/platform-tools" \
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/sign_macos.py dist/AndroidBox.app
python scripts/verify_frozen.py dist/AndroidBox.app/Contents/MacOS/AndroidBox --require-runtime
python scripts/package_desktop.py
python scripts/verify_frozen.py --dmg dist/installers/*.dmg --require-runtime
```

Windows PowerShell 构建示例，需预先安装 QEMU 和 NSIS：

```powershell
$env:ANDROIDBOX_QEMU_PREFIX = 'C:\Program Files\qemu'
$env:ANDROIDBOX_ADB_DIRECTORY = "$PWD\build\platform-tools"
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/verify_frozen.py dist/AndroidBox/AndroidBox.exe --require-runtime
python scripts/package_desktop.py
```

Linux 构建示例，需预先安装 QEMU 和 Qt 系统依赖，具体包列表见 [CI 配置](./.github/workflows/desktop.yaml)；ARM64 主机还需 `adb` 和 `patchelf`，因为 Google 不提供 AArch64 Linux 版 Platform Tools：

```sh
ANDROIDBOX_QEMU_PREFIX=/usr \
ANDROIDBOX_ADB_DIRECTORY="$PWD/build/platform-tools" \
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/verify_frozen.py dist/AndroidBox/AndroidBox --require-runtime
python scripts/fetch_appimagetool.py
python scripts/package_desktop.py --appimagetool build/appimagetool.AppImage
```

macOS 输出 `dist/AndroidBox.app`，Windows/Linux 输出完整的 `dist/AndroidBox` 目录，安装包位于 `dist/installers`。不设置运行时变量也可构建桌面客户端，但该产物不含 QEMU/ADB，无法通过 `--require-runtime` 检查。

内置运行时优先于系统 PATH，设置中显式指定的 QEMU 路径仍优先。macOS 签名仅向 QEMU 授予 Hypervisor 权限，封装应用时保留该权限。Platform Tools 固定为 `37.0.1` 并校验 SHA1、SHA256；Windows QEMU 固定为 Chocolatey `2026.8.11`，其他平台从系统包源获取。Google 不发布 AArch64 Linux 版 Platform Tools，因此 Linux ARM64 构建改为从发行版包安装 `adb` 与 `patchelf`，由 `scripts/fetch_platform_tools.py` 连同其依赖库一并打入包内，并实际执行 `adb version` 验证通过后才打包。依赖许可证和源码再分发的完整性仍需审核。

#### GitHub Actions 发布

[Build Desktop Installers](./.github/workflows/desktop.yaml) 监听 `v*` 标签。标签必须与源码版本一致，例如 `v1.0.20260923`；手动运行仅生成 CI artifacts，不发布 Release。只推送 `main` 或修改版本字符串不会触发安装包发布。

发布者在版本修改提交并推送后执行：

```sh
git tag -a v1.0.20260923 -m "AndroidBox 1.0.20260923"
git push origin v1.0.20260923
```

工作流验证版本后并行构建五份安装包，全部验证通过才创建并发布 Release；失败时不会发布缺少附件的版本。进度可在仓库的 [Actions 页面](https://github.com/Mutantcat-Working-Group/AndroidBox/actions/workflows/desktop.yaml) 查看。

| 平台 | 当前版本产物 |
| --- | --- |
| Windows x86_64 | `AndroidBox-1.0.20260923-Windows-x86_64-Setup.exe` |
| macOS ARM64 | `AndroidBox-1.0.20260923-macOS-arm64.dmg` |
| macOS Intel | `AndroidBox-1.0.20260923-macOS-x86_64.dmg` |
| Linux x86_64 | `AndroidBox-1.0.20260923-Linux-x86_64.AppImage` |
| Linux ARM64 | `AndroidBox-1.0.20260923-Linux-aarch64.AppImage` |

每个平台还随附一份免安装便携包 `AndroidBox-1.0.20260923-<平台>-<架构>.tar.gz`（解压即可运行），与安装包一同校验、上传和发布。

每个原生构建执行单元测试、Qt/noVNC 冒烟测试，以及包内 QEMU/ADB 检查；随后再次检查 Windows 实际安装目录、macOS 只读挂载的 DMG 或 Linux 解包后的 AppImage。Windows 安装测试使用含空格路径，并在结束后卸载。

五个安装包及随附便携包全部成功后，流程生成 `SHA256SUMS`，先上传到草稿 Release，再公开发布。已发布的 Release 不会被重复运行覆盖；只有发布任务获得 `contents: write` 权限，不需要签名密钥。

后续升级版本时，需同步更新 `pyproject.toml`、两处源码版本声明和 Debian changelog，运行 `python scripts/release_metadata.py --tag v版本号` 校验后再推送标签。

### 五、项目结构

```text
.
├── androidbox/          # Qt 客户端、QEMU/ADB 管理、noVNC 资源
├── tools/               # Linux 原生容器后端
├── guest/               # Linux/Android 客体配置脚本
├── data/                # 桌面入口、图标与应用元数据
├── packaging/           # PyInstaller、NSIS、AppImage 配置及原生图标
├── scripts/             # 下载、打包、签名和验证工具
├── tests/               # 单元测试
├── docs/                # 客体准备说明与验证记录
├── .github/workflows/   # CI 与 Release 流程
├── logo.png             # 应用图标源文件
├── pyproject.toml
└── README.md
```

产品和桌面 ID 为 `org.mutantcat.androidbox`，D-Bus/polkit 命名空间为 `org.mutantcat.androidbox.*`。Linux 服务为 `androidbox-container.service`，原生状态目录为 `/var/lib/androidbox` 和 `~/.local/share/androidbox`；Qt 客户端的配置及日志位于系统应用数据目录下的 `org.mutantcat.androidbox`，macOS 使用 `~/Library/Application Support`。

Android 镜像侧的 `lineageos.waydroid.*` 接口、属性、完整界面标记、临时 APK 路径、上游 OTA 地址及外部 `waydroid-sensord` 名称保留，以兼容已有镜像。这些不属于宿主产品 ID。现有 Waydroid 数据不会自动迁移，两个原生后端不应同时运行，以免 Binder、服务或网络冲突。

### 六、开发进度

- [x] AndroidBox 品牌与 `org.mutantcat.androidbox` 宿主命名改造。
- [x] Qt 窗口、虚拟机配置、日志、全屏及内嵌 noVNC。
- [x] QEMU 启动、正常关机、强制停止及授权 ADB 安装 APK。
- [x] 三平台四种目标组合的安装包流程配置，内置 QEMU 和 ADB。
- [x] 根目录 `logo.png` 生成 PNG、ICO、ICNS 图标，供窗口和安装器使用。
- [x] macOS ARM64 本机构建、ad-hoc 签名、DMG 校验和固件画面测试。
- [x] 四种目标组合的原生 CI 打包、自检和标签触发 Release 全流程验证。
- [x] Ubuntu 24.04 示例客体盘下载与校验工具，生成客户端自动识别的 QCOW2 磁盘。
- [ ] 各平台真实硬件加速与完整 Android 客体兼容性验证。
- [ ] 可直接分发的完整 Android 客体镜像；当前仅提供示例盘与配置流程。
- [ ] Android 鼠标定位、SystemUI 启动异常及共享存储问题修复。
- [ ] 音频转发、GPU 加速、宿主剪贴板和文件共享。
- [ ] 干净机器兼容性、完整依赖许可证及源码再分发审核。

开发检查命令：

```sh
python -m pip install -e '.[desktop,dev]'
python scripts/fetch_novnc.py
python -m unittest discover -s tests -v
ruff check .
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_desktop.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_qemu.py
```

单元测试不需要 Android 客体或实际 QEMU。`smoke_qemu.py` 需要 QEMU，使用临时空白磁盘检查固件画面，不会下载操作系统或修改用户配置的磁盘；ARM64 Mac 可传入 `--arch aarch64 --accel hvf` 及需要的 `--firmware` 路径。测试会保存截图，但固件检查不等于 Android 集成测试。

更新图标时，替换根目录的 1024×1024 `logo.png`，安装 Pillow 后运行 `python scripts/generate_icons.py`，并提交生成的 PNG、ICO 和 ICNS 文件。

### 七、相关文档与项目

- [客体镜像准备](./docs/guest-image.md)：Linux/Android 磁盘配置与验证。
- [性能与游戏](./docs/performance.md)：可调性能参数、实测帧率与游戏能力边界。
- [验证记录](./docs/verification.md)：本地与 CI 实测结果、平台限制及待解决问题。
- [Waydroid](https://github.com/waydroid/waydroid)：本项目的上游容器运行时。
- [QEMU](https://www.qemu.org/)：跨平台虚拟机后端。
- [问题反馈](https://github.com/Mutantcat-Working-Group/AndroidBox/issues)：AndroidBox 缺陷与功能建议。
- [许可证](./LICENSE)：保留上游版权声明、许可证及历史 changelog；应用图标使用本仓库的 `logo.png`。
