<div align="center">
<img src="./logo.png" width="100" alt="AndroidBox Logo"/>
<h2>AndroidBox</h2>
<p><a href="./README_EN.md">English</a></p>
</div>

### 一、功能简述

- 基于 [Waydroid](https://github.com/waydroid/waydroid) 改造的 **Android 窗口化运行工具**，保留 Linux 原生容器后端，并提供基于 Qt、QEMU 和 noVNC 的跨平台桌面客户端。
- **窗口化界面**：内嵌 noVNC 显示，支持全屏、运行日志和虚拟机设置；日志栏默认收起，工具栏按钮一键展开。
- **虚拟机管理**：配置磁盘、架构、内存、CPU、CPU 型号、TCG 线程和磁盘缓存，支持启动、正常关机与强制停止。
- **QEMU 兼容层**：探测 Linux KVM、macOS HVF、Windows WHPX；自动模式在跨架构或未发现硬件加速时回退 TCG，一个客户端覆盖三平台。
- **内置系统镜像**：按客体架构打包整套 Android 镜像（`system` + `vendor`，位于只读 `androidbox-img` 磁盘），首次开机不再访问 Waydroid OTA 渠道。
- **APK 安装**：通过经过设备授权的 ADB 安装应用，优先使用安装包内置的 ADB。
- **开箱即用**：首次启动按宿主架构预填客体架构、CPU、内存与磁盘路径，无需命令行即可准备示例盘并启动。
- **休眠看门狗**：运行期间阻止宿主机合盖休眠与空闲睡眠，客体被宿主异常中断后自动重启，最多 5 次。
- **原生 Linux 后端**：保留基于 LXC、Binder 和 Wayland 的 Android 容器运行方式。
- **统一应用标识**：软件名称为 AndroidBox，应用 ID 为 `org.mutantcat.androidbox`。

**当前版本：`1.0.20260929`。** 安装包内置 Python、Qt、noVNC、QEMU、ADB 与整套 Android 系统镜像；Windows 安装器把镜像压缩后追加在自身上，首次启动自动展开。首次启动点击 **Prepare example guest disk** 即可准备 Ubuntu 24.04 minimal 客体盘：下载固定版本镜像、校验官方 SHA256，生成客户端可自动识别的 QCOW2 磁盘，并在磁盘旁生成 NoCloud 首次引导种子。官方源不可达时自动回退国内镜像，也可用 **Use a local image** 选择已下载镜像。开机后云端初始化自动登录、设置已知密码并一次性安装 Android 容器，不再停留在 `ubuntu login:`。

### 二、安装方式

从 [Releases](https://github.com/Mutantcat-Working-Group/AndroidBox/releases) 下载对应平台的安装包，双击即可使用，全部产物已通过 CI 安装自检。

| 平台 | 架构 | 虚拟化后端 | 安装包格式 | 验证状态 |
| --- | --- | --- | --- | --- |
| Windows | x86_64 | QEMU / WHPX、TCG | NSIS `.exe` | 原生 CI 安装、应用自检和卸载通过 |
| macOS | Apple Silicon / ARM64 | QEMU / HVF、TCG | ad-hoc 签名 `.dmg` | CI 签名、挂载自检及本机固件启动通过 |
| macOS | Intel / x86_64 | QEMU / HVF、TCG | ad-hoc 签名 `.dmg` | 原生 CI 签名、挂载和应用自检通过 |
| Linux | x86_64 | QEMU / KVM、TCG | `.AppImage` | 原生 CI 提取和应用自检通过 |
| Linux | ARM64 / aarch64 | QEMU / TCG（公共 runner 无 KVM） | `.AppImage` | 原生 ARM runner 提取和应用自检（无 KVM，仅 `--version` 校验） |
| Linux 原生容器 | 依赖宿主内核与镜像 | LXC / Binder / Wayland | 源码安装 | 保留上游后端，仍需宿主验证 |

同时提供免安装便携包 `AndroidBox-<版本>-<平台>-<架构>.tar.gz`，解压即可运行。每个 Release 附带 `SHA256SUMS`。

注意事项：

- macOS 的 ad-hoc 签名不是 Developer ID 签名或 Apple 公证，下载后的应用仍可能被 Gatekeeper 阻止；本机 QEMU 面向 macOS 26 构建，不能据此保证旧系统兼容。
- Windows 安装器尚未使用代码签名证书，可能出现 SmartScreen 提示。
- Linux AppImage 面向较新 glibc（x86_64 基于 Ubuntu 22.04 / glibc 2.35，aarch64 基于 Ubuntu 24.04 / glibc 2.39）和桌面会话，可能需要执行权限、FUSE2，或使用 `APPIMAGE_EXTRACT_AND_RUN=1`。
- 硬件加速需要宿主支持并启用对应虚拟化能力；TCG 性能明显低于硬件加速。

从源码启动需要 Python 3.10+、支持 VNC/WebSocket 的 QEMU，APK 安装还需要 `adb`：

```sh
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell：.venv\Scripts\Activate.ps1
python scripts/fetch_novnc.py
python -m pip install -e '.[desktop]'
python -m androidbox              # 或使用 androidbox-desktop
```

Linux 原生容器后端依赖 LXC、支持 Binder 的内核、Wayland、D-Bus、PyGObject、python3-gbinder、polkit、PulseAudio/PipeWire-Pulse、iptables 和 dnsmasq，发行版依赖见 [debian/control](./debian/control)。执行 `sudo make install && sudo make install_apparmor` 后使用 `androidbox init`、`androidbox show-full-ui`。`androidbox` 是 Linux 原生命令，`androidbox-desktop` / `python -m androidbox` 是跨平台 Qt 客户端；客户端的原生入口会启动独立 Android 窗口，不会把已有 Wayland 窗口嵌入 noVNC。

### 三、使用教程

1. 安装并打开 AndroidBox。首次打开提示没有客体磁盘，点击 **Prepare example guest disk**。程序下载官方 Ubuntu 24.04 minimal 镜像、校验 SHA256，并在应用数据目录生成 `androidbox-架构.qcow2`，全程不需要命令行。网络访问官方源失败时，可改用 **Use a local image** 选择已下载的同名镜像，校验方式相同。
2. 准备完成后点击 **Start**，程序自动选中刚生成的磁盘并进入运行视图；与宿主不同架构的客体仍需在设置中选择架构。
3. 第一次开机由云端初始化自动登录并安装 Android 容器（内置镜像、安装 Binder 模块并运行 `guest/provision.sh`，通常数分钟，完成后自动重启进入 Android 会话）；安装 APK 前，在 Android 中确认 ADB 授权提示。

客体系统账户为 `ubuntu`，默认密码为 **`androidbox`**，控制台自动登录，无需手动输入。

客体网卡由 NoCloud `network-config` 自动配置 DHCP（匹配 QEMU virtio 网卡 `e*`），首次开机即带默认路由，安卓容器开箱即可联网；首次引导脚本也会检查默认路由，缺失时在屏幕告警并尝试 `dhclient`。

如果启动后停在 `ubuntu@androidbox:~$` 命令行、没有出现首次引导进度，说明自动初始化没有执行；重启一次客体通常会继续重试。进度与失败原因会同时打印在屏幕和客体内的 `/var/log/androidbox-firstboot.log`，可复制给客服排查。

下载失败时，准备过程依次尝试官方源和两个国内镜像，自动重试并支持断点续传；TLS 校验使用安装包内置 CA 证书，不依赖宿主 OpenSSL 配置。仍失败时错误框的 Details 会列出每个镜像的原因。

**休眠看门狗**：运行期间客户端会请求宿主机保持唤醒（Windows 执行状态、macOS `caffeinate`、Linux `systemd-inhibit`），合盖或空闲睡眠不会中断客体；若 QEMU 仍被宿主中断，客户端自动重启客体，最多 5 次，之后把控制权交回用户。客体主动关机（退出码 0）不会被重启，也可以随时用 Start 手动重试。

**默认参数**：首次启动按宿主架构填写客体架构，CPU 取逻辑核心数的一半（1–6 核），内存取总内存一半并按 GiB 向下取整（1–6 GiB），检测失败时用 2 核、2 GiB；已有设置不会被覆盖。QEMU 与 ARM 固件自动查找，手动填写的路径优先。可调项还有 CPU 型号（host/max/qemu64）、TCG 线程数（单线程/多线程）、磁盘缓存（writeback/none/unsafe）和显示质量（responsive/balanced/sharp，画质越低编码越少、操作越跟手），默认值保持原有行为，实测数据见 [性能与游戏](./docs/performance.md)。

工具栏是一列纯图标：左侧依次为启动、关机、安装 APK，右侧依次为设置、日志、全屏，两侧图标大小一致，中间没有分割线；日志栏默认收起，点右侧感叹号图标展开。把文件拖进窗口即会上传到 Android 的 Download 目录，拖入 APK 时推送完成后会自动触发安装。运行日志同时写入应用数据目录下的 `qemu.log`。磁盘与设置位于系统应用数据目录的 `org.mutantcat.androidbox`，macOS 为 `~/Library/Application Support`。

### 四、专注的点

- 用 QEMU 兼容层把 Linux 原生 Android 容器带到 Windows、macOS 与 Linux，窗口化界面与虚拟化管理保持一致。
- 安装包真正开箱即用：内置 QEMU、ADB 与整套 Android 镜像，默认参数按宿主资源预填，首次启动不需要命令行。
- 客体准备可复现：固定版本镜像、官方 SHA256 校验、NoCloud 种子自动登录，国内镜像与本地镜像作为等价备选。
- 宿主机休眠、合盖、异常退出都不让用户丢会话：请求保持唤醒，客体中断后有界自动重启。
- 五个安装包全部由原生 runner 构建，并在各自平台完成安装、挂载、自检与卸载验证后才允许发布。
- 保留上游 `lineageos.waydroid.*` 接口、属性、界面标记与 OTA 兼容性，同时把宿主侧产品 ID 收敛到 `org.mutantcat.androidbox`。

### 五、开发进度

- [X] AndroidBox 品牌与 `org.mutantcat.androidbox` 宿主命名改造。
- [X] Qt 窗口、虚拟机配置、日志、全屏及内嵌 noVNC；日志栏默认收起。
- [X] QEMU 启动、正常关机、强制停止及授权 ADB 安装 APK。
- [X] 三平台五种目标组合的安装包流程，内置 QEMU、ADB 与整套 Android 镜像。
- [X] 根目录 `logo.png` 生成 PNG、ICO、ICNS 图标，供窗口和安装器使用。
- [X] macOS ARM64 / Intel 本机构建、ad-hoc 签名、DMG 挂载自检与固件画面测试。
- [X] Ubuntu 24.04 示例客体盘下载、校验与自动识别，NoCloud 种子自动登录。
- [X] 首次启动按宿主资源预填默认参数，无需命令行即可使用。
- [X] 宿主机休眠看门狗与客体异常退出有界自动重启。
- [X] 五种目标组合的原生 CI 打包、自检和标签触发 Release 全流程。
- [ ] 各平台真实硬件加速与完整 Android 客体兼容性验证。
- [ ] Android 鼠标定位、SystemUI 启动异常及共享存储问题修复。
- [ ] 音频转发、GPU 加速、宿主剪贴板和文件共享。
- [ ] 干净机器兼容性、完整依赖许可证及源码再分发审核。

开发检查：

```sh
python -m pip install -e '.[desktop,dev]'
python scripts/fetch_novnc.py
python -m unittest discover -s tests -v
ruff check .
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_desktop.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_qemu.py
```

客体磁盘配置见 [客体镜像准备](./docs/guest-image.md)，实测记录见 [验证记录](./docs/verification.md)。上游项目：[Waydroid](https://github.com/waydroid/waydroid)、[QEMU](https://www.qemu.org/)。问题反馈请到 [issues](https://github.com/Mutantcat-Working-Group/AndroidBox/issues)。许可证见 [LICENSE](./LICENSE)。


### 六、构建与发布

必须在目标系统上原生构建，PyInstaller 不跨平台编译。发布脚本建议 Python 3.12，至少 3.11。

开发自检（需要 Python 3.10+ 与桌面依赖）：

```sh
python -m pip install -e '.[desktop,dev]'
python scripts/fetch_novnc.py
python -m unittest discover -s tests -v
ruff check .
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_desktop.py
```

单元测试不需要 Android 客体或实际 QEMU。需要 QEMU 的固件画面冒烟使用临时空白磁盘，ARM64 Mac 可传 `--arch aarch64 --accel hvf` 及 `--firmware`。更换应用图标时替换根目录 1024×1024 `logo.png`，安装 Pillow 后运行 `python scripts/generate_icons.py`，再构建安装包。

仓库内容分布：

```text
.
├── androidbox/          # Qt 客户端、QEMU/ADB 管理、noVNC 资源
├── tools/               # Linux 原生容器后端
├── guest/               # Linux/Android 客体配置脚本
├── data/                # 桌面入口、图标与应用元数据
├── packaging/           # PyInstaller、NSIS、AppImage 配置及原生图标
├── scripts/             # 下载、打包、签名和验证工具
├── tests/               # 单元测试
├── docs/                # 客体准备、性能与验证记录
├── .github/workflows/   # CI 与 Release 流程
├── logo.png             # 应用图标源文件
├── pyproject.toml
└── README.md
```

```sh
python scripts/fetch_novnc.py
python scripts/fetch_platform_tools.py
python -m pip install '.[desktop,build]'
```

| 环境变量 | 用途 | CI 配置 |
| --- | --- | --- |
| `ANDROIDBOX_QEMU_PREFIX` | QEMU 安装前缀，含二进制、固件、数据和许可证 | Linux `/usr`；macOS Homebrew；Windows Chocolatey |
| `ANDROIDBOX_ADB_DIRECTORY` | 含 ADB 及许可证的 Platform Tools 目录 | `build/platform-tools` |

macOS：

```sh
ANDROIDBOX_QEMU_PREFIX="$(brew --prefix qemu)" \
ANDROIDBOX_ADB_DIRECTORY="$PWD/build/platform-tools" \
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/sign_macos.py dist/AndroidBox.app
python scripts/verify_frozen.py dist/AndroidBox.app/Contents/MacOS/AndroidBox --require-runtime
python scripts/package_desktop.py
python scripts/verify_frozen.py --dmg dist/installers/*.dmg --require-runtime
```

Windows PowerShell（需预装 QEMU 与 NSIS）：

```powershell
$env:ANDROIDBOX_QEMU_PREFIX = 'C:\Program Files\qemu'
$env:ANDROIDBOX_ADB_DIRECTORY = "$PWD\build\platform-tools"
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/verify_frozen.py dist/AndroidBox/AndroidBox.exe --require-runtime
python scripts/package_desktop.py
```

Linux（需预装 QEMU、Qt 系统依赖与 appimagetool；ARM64 还需 `adb` 和 `patchelf`，因为 Google 不提供 AArch64 Linux 版 Platform Tools）：

```sh
ANDROIDBOX_QEMU_PREFIX=/usr \
ANDROIDBOX_ADB_DIRECTORY="$PWD/build/platform-tools" \
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/verify_frozen.py dist/AndroidBox/AndroidBox --require-runtime
python scripts/fetch_appimagetool.py
python scripts/package_desktop.py --appimagetool build/appimagetool.AppImage
```

macOS 输出 `dist/AndroidBox.app`，Windows/Linux 输出完整 `dist/AndroidBox` 目录，安装包位于 `dist/installers`。不设置运行时变量也能构建桌面客户端，但产物不含 QEMU/ADB，无法通过 `--require-runtime`。

内置 Android 镜像由 `scripts/build_system_images.py` 生成。Windows 安装器因为 makensis 无法把超大文件压进数据库，改为把压缩后的镜像追加在安装器尾部，安装时放进运行时目录，首次启动自动展开，展开后删除压缩包以节省空间。Platform Tools 固定 `37.0.1` 并校验 SHA1、SHA256；Windows QEMU 固定 Chocolatey `2026.8.11`。依赖许可证和源码再分发的完整性仍需审核。

[Build Desktop Installers](./.github/workflows/desktop.yaml) 监听 `v*` 标签，标签必须与源码版本一致，例如 `v1.0.20260929`；手动运行只生成 CI artifacts，不发布 Release。发布流程：

```sh
git tag -a v1.0.20260929 -m "AndroidBox 1.0.20260929"
git push origin v1.0.20260929
```

工作流验证版本后并行构建五份安装包与两份镜像盘，全部通过才创建并发布 Release；失败不会发布缺少附件的版本。每次原生构建都会执行单元测试、Qt/noVNC 冒烟测试与包内 QEMU/ADB 检查，随后再检查 Windows 实际安装目录、macOS 只读挂载的 DMG 或 Linux 解包后的 AppImage。全部成功后生成 `SHA256SUMS`，先上传草稿再公开发布。已发布的 Release 不会被重复运行覆盖；只有发布任务拥有 `contents: write`，不需要签名密钥。进度见 [Actions 页面](https://github.com/Mutantcat-Working-Group/AndroidBox/actions/workflows/desktop.yaml)。

| 平台 | 当前版本产物 |
| --- | --- |
| Windows x86_64 | `AndroidBox-1.0.20260929-Windows-x86_64-Setup.exe` |
| macOS ARM64 | `AndroidBox-1.0.20260929-macOS-arm64.dmg` |
| macOS Intel | `AndroidBox-1.0.20260929-macOS-x86_64.dmg` |
| Linux x86_64 | `AndroidBox-1.0.20260929-Linux-x86_64.AppImage` |
| Linux ARM64 | `AndroidBox-1.0.20260929-Linux-aarch64.AppImage` |
