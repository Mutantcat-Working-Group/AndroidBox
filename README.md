<img align="left" src="data/AppIcon.png" width="64">

# AndroidBox

AndroidBox is a fork of [Waydroid](https://github.com/waydroid/waydroid), with a
Linux-native Android container runtime and a new cross-platform Qt/QEMU desktop
client. Application ID: **org.mutantcat.androidbox**.

## Current Status

The desktop client implements VM settings, start/shutdown/force-stop, embedded
noVNC display, full screen, runtime logs and APK installation through authenticated
ADB. Linux retains its native container backend. The QEMU backend needs a
**prepared bootable Linux guest disk**; this repository does not yet ship one.

Windows/macOS/Linux support is the target architecture, not a completed
three-platform certification. Android guest input and application compatibility
still require further integration testing. Audio
forwarding, GPU acceleration, host clipboard/file sharing and
automatic guest-image downloads are not implemented.

On the local macOS ARM64 host, a prepared Ubuntu/Android guest boots under HVF
and displays the Android launcher in the embedded window. Keyboard delivery,
ADB authorization, a test APK install and graceful shutdown were exercised. Mouse targeting and
SystemUI startup errors remain unresolved; Windows/Linux real-host validation
is still pending. See [Local Verification](docs/verification.md).

## Desktop Client

Requires Python 3.10+, QEMU with VNC/WebSocket support, and optionally Android SDK
Platform Tools (`adb`) for APK installation.

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python scripts/fetch_novnc.py
python -m pip install -e '.[desktop]'
python -m androidbox
```

For distributable wheels, fetch noVNC **before** building; the wheel then includes
those assets and their licenses. The `androidbox-desktop` entry point also starts
the Qt client. noVNC is pinned and its archive checksum is verified.

Install QEMU using your platform's trusted package source (for example Homebrew
on macOS or your Linux distribution). On Windows configure QEMU's executable in
Settings or add its directory to PATH. Enable the appropriate host virtualization
facility. The client probes available accelerators: KVM on Linux, HVF on macOS,
WHPX on Windows. Cross-architecture or unaccelerated operation requires explicit
TCG selection; performance can be substantially lower.

In Settings select the prepared Linux disk, guest architecture, resources and
firmware as needed. ARM64 guests require a suitable UEFI firmware file. See
[Guest Image Setup](docs/guest-image.md) for provisioning and validation.

## Standalone Desktop Builds

Build on each target OS; PyInstaller does not cross-compile:

```sh
python scripts/fetch_novnc.py
python -m pip install '.[desktop,build]'
python -m PyInstaller packaging/desktop.spec --noconfirm
# macOS; on Windows/Linux use dist/AndroidBox/AndroidBox[.exe]:
python scripts/verify_frozen.py dist/AndroidBox.app/Contents/MacOS/AndroidBox
```

macOS output is `dist/AndroidBox.app`; Windows/Linux output is the complete
`dist/AndroidBox` directory. Keep all files together. These clients include
Python, Qt and noVNC, but still require separately installed QEMU, a prepared
guest disk and optionally ADB. Installer packaging is implemented, but full
Android operation on each supported host still needs integration testing.

### Experimental Bundled Runtime on macOS

For local integration testing, a native QEMU installation prefix can be included:

```sh
ANDROIDBOX_QEMU_PREFIX="$(brew --prefix qemu)" \
ANDROIDBOX_ADB_DIRECTORY="$ANDROID_HOME/platform-tools" \
python -m PyInstaller packaging/desktop.spec --noconfirm
python scripts/sign_macos.py dist/AndroidBox.app
python scripts/verify_frozen.py dist/AndroidBox.app/Contents/MacOS/AndroidBox --require-runtime
dist/AndroidBox.app/Contents/MacOS/AndroidBox --qemu-test --arch aarch64 --accel hvf
python scripts/package_desktop.py --output dist/runtime-experiment
python scripts/verify_frozen.py --dmg dist/runtime-experiment/*.dmg --require-runtime
```

On Intel Macs use `--arch x86_64`. The bundle collects the host-architecture
QEMU binary, its linked libraries, firmware/data and QEMU license files. The
application discovers its bundled binary and ARM firmware automatically; an
explicit QEMU path in Settings still overrides it. Signing grants Hypervisor
access to QEMU alone and preserves that entitlement when sealing the app.
The test boots a disposable blank disk, not Android, and never alters user disks.
ADB is collected with its notice and version metadata; APK installation prefers
that bundled executable. `--require-runtime` rejects a bundle missing QEMU,
firmware/data or ADB and executes both version commands, without starting a guest
or ADB server. It never substitutes a system executable for a missing payload.

This mode is not enabled in Release CI yet. Dependency license/source
distribution, supported macOS deployment versions and guest provisioning
must be completed before treating it as a redistributable Android runtime.
Windows DLL and Linux prefix collection are implemented and unit-tested, but
their frozen runtime execution is not yet validated on those hosts.

## Installer Releases

Current version: **1.0.20260919**. The **Build Desktop Installers** workflow runs
on version tags such as `v1.0.20260919`. After all four native builds succeed,
it uploads the complete set with `SHA256SUMS` to a draft and then publishes it:

| Platform | Release artifact |
| --- | --- |
| Windows x86_64 | `AndroidBox-1.0.20260919-Windows-x86_64-Setup.exe` (NSIS, per-user) |
| macOS Apple Silicon | `AndroidBox-1.0.20260919-macOS-arm64.dmg` |
| macOS Intel | `AndroidBox-1.0.20260919-macOS-x86_64.dmg` |
| Linux x86_64 | `AndroidBox-1.0.20260919-Linux-x86_64.AppImage` |

Tag validation checks `pyproject.toml`, both source version declarations and the
current Debian changelog entry. Update those together for the next release.
Manual workflow runs only create downloadable CI artifacts, not a Release.
Published Releases are never overwritten by a rerun. The built-in `GITHUB_TOKEN`
gets `contents: write` only in the Release job; no signing secret is required.
Each build runs the packaged executable outside the checkout and requires a
passing Qt/noVNC self-test and a rendered screenshot before packaging. Linux
also repeats that check through the extracted AppImage launcher.
macOS repeats the check from a verified, read-only mounted DMG. Windows silently
installs to a path containing spaces, checks that installed application and
uninstalls it in a cleanup step. These CI steps still need remote execution.
Every native build runner also runs the unit suite, including a Windows-only
DLL inheritance test. External Windows QEMU/ADB processes use a cleaned DLL/PATH
environment, while bundled executables keep their packaged dependencies.

To package an existing native PyInstaller build locally (Python 3.11+):

```sh
# Linux only, first fetch the pinned packaging tool:
python scripts/fetch_appimagetool.py
python scripts/package_desktop.py --appimagetool build/appimagetool.AppImage
# Windows/macOS:
python scripts/package_desktop.py
```

Installers are written to `dist/installers`. Windows needs NSIS on the build host.
Both the macOS application and DMG receive ad-hoc signatures and are verified;
this is **not** Developer ID signing or notarization, so Gatekeeper may still
block a downloaded app. Windows installers are unsigned and may trigger
SmartScreen. Linux targets glibc 2.35+ and needs a desktop session; AppImage may
need FUSE2 (or `APPIMAGE_EXTRACT_AND_RUN=1`) and executable permission.

**Not yet click-and-use Android packages:** Python, Qt and noVNC are bundled,
but QEMU, ADB and a bootable Android-capable Linux guest are not. Do not distribute
the local test disk or its SSH seed as a production guest image. See
[Local Verification](docs/verification.md) for the remaining integration gaps.

## Linux-Native Runtime

Native runtime dependencies remain LXC, Binder-capable Linux, Wayland, D-Bus,
PyGObject, python3-gbinder, polkit, PulseAudio/PipeWire-Pulse, iptables and dnsmasq.
See `debian/control` and the upstream [Waydroid documentation](https://docs.waydro.id)
for distribution-specific prerequisites; use the AndroidBox names below.

```sh
sudo make install
sudo make install_apparmor  # If the host uses AppArmor
sudo systemctl daemon-reload
sudo androidbox init
sudo systemctl enable --now androidbox-container
androidbox show-full-ui
androidbox app install example.apk
```

`androidbox` is the native Linux CLI; `androidbox-desktop` / `python -m androidbox`
is the portable Qt client. The client's Linux-native action launches the native
Android window rather than embedding an existing Wayland surface.

## Naming and Compatibility

- Product/desktop ID: AndroidBox / `org.mutantcat.androidbox`.
- D-Bus and polkit namespace: `org.mutantcat.androidbox.*`.
- Native command/package/service: `androidbox` / `androidbox-container.service`.
- Native state: `/var/lib/androidbox`, user state: `~/.local/share/androidbox`.
- Desktop client settings/logs: platform application-data directory under
  `org.mutantcat.androidbox` (macOS: `~/Library/Application Support`).
- Android-side `lineageos.waydroid.*`, properties, full-UI token, temporary APK
  path, upstream OTA channels and external `waydroid-sensord` retain their names
  to remain compatible with existing images. They are not host product IDs.
- Existing Waydroid data is not automatically migrated. Do not run both native
  runtimes simultaneously: Binder, Android services and bridge subnets may clash.

Upstream copyright notices, license and historical changelog entries are retained.
The existing application icon is inherited from upstream and has not been redesigned.
Report AndroidBox issues in the [project repository](https://github.com/Mutantcat-Working-Group/AndroidBox/issues).

## Development

```sh
python -m pip install -e '.[desktop,dev]'
python scripts/fetch_novnc.py
python -m unittest discover -s tests -v
ruff check .
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_desktop.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_qemu.py
```

The smoke test saves a screenshot to the specified `--screenshot` path and exits.
Unit tests do not require QEMU, a Linux kernel, or an Android guest. They are not
a replacement for the real guest validation checklist.
`smoke_qemu.py` requires QEMU and tests its firmware framebuffer using a temporary
blank disk; it does not download an OS or alter the configured guest disk.
See [Local Verification](docs/verification.md) for completed checks and outstanding
integration tests.
