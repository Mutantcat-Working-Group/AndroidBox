# Verification History

This document includes historical checks with different test counts and payloads.
See the final section for the current release-workflow and installer validation.

Date: 2026-09-19. Host: macOS ARM64. Python: 3.12.10. PySide6: 6.11.2.
QEMU: Homebrew 11.1.1. PyInstaller: 6.22.3.

## Passed

- `python -m unittest discover -s tests`: 71 tests, 70 passed and one
  Windows-native DLL inheritance test skipped on this macOS host.
  Covers host IDs, preserved guest protocols, configuration, command generation,
  accelerator selection, single-display configuration, executable discovery,
  packaged Linux subprocess environment, fake QMP handshake, process cleanup
  local asset HTTP serving, and authenticated ADB installation waiting/error paths.
- `ruff check .`: no findings.
- Python AST parsing: 50 implementation/script files.
- XML parsing: four D-Bus, policy, AppStream and menu files.
- `bash -n`: six provisioning, networking, cleanup and package scripts.
- `make install install_apparmor DESTDIR=/tmp/androidbox-stage-20260919-final`:
  successful staging, with a verified relative CLI symlink. No host system installation.
- Qt smoke: initial control states, settings round trip, icon, resize and screenshot.
- Embedded noVNC smoke: real Qt WebEngine loads the bundled ES modules and reaches
  the expected disconnected state when pointed at an unused local port.
- Earlier `uv build --wheel`: built `androidbox-1.6.3-py3-none-any.whl`, with noVNC,
  vendor licenses and the application icon included.
  This predates the version update and is not a verified 1.0.20260919 wheel.
- Wheel installed without dependencies into a separate temporary directory.
- Real QEMU x86_64/TCG: authenticated noVNC connection, nonuniform canvas pixels,
  visible SeaBIOS framebuffer, QMP running state, accepted QMP Escape key command,
  QMP quit and process reaping.
- Real QEMU aarch64/HVF: same checks, visible TianoCore firmware framebuffer,
  using `/opt/homebrew/share/qemu/edk2-aarch64-code.fd`.
- PyInstaller built a macOS `dist/AndroidBox.app`; its frozen executable passed
  the Qt window/settings/resize and bundled noVNC self-test outside the checkout.
  This is not a frozen Android guest integration test.

GUI verification command:

```sh
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_desktop.py
```

The disconnected WebSocket messages are expected for this test. Offscreen
WebEngine produced GPU-context warnings without `--disable-gpu`; the software
rendering test passed without those warnings. This does not validate a guest framebuffer.

The separate real-QEMU framebuffer tests used:

```sh
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_qemu.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python scripts/smoke_qemu.py \
  --arch aarch64 --accel hvf --firmware /opt/homebrew/share/qemu/edk2-aarch64-code.fd
```

Both use disposable blank raw disks. The expected firmware screen reports no
bootable operating system; these checks do not establish Android compatibility.
QMP accepting a key command does not establish GUI-to-Android input delivery.
QMP quit is not an ACPI guest-shutdown test.

## Real Android Guest Integration

An Ubuntu 24.04.4 ARM64 minimal cloud guest was provisioned on this macOS host
using QEMU/HVF, kernel 6.8.0-139-generic plus its matching extra modules, and
the actual `guest/provision.sh --dedicated-guest` script. The Ubuntu base image
was checked against the official SHA256 manifest. The Android system/vendor
images are the upstream arm64_only LineageOS 20 builds dated 2026-04-03.

Passed in the source Qt application:

- Linux boot, Binder module loading, LXC container startup, Android
  `sys.boot_completed=1`, and an actual Android launcher in embedded noVNC.
- Qt/WebEngine keyboard events reach Android: Escape, Tab and Return operate
  the Android UI and its ADB authorization dialog.
- ADB rejects an unauthenticated connection; accepting its RSA prompt changes
  the transport to `device`. Secure ADB remains enabled.
- The desktop APK action installs the signed disposable test application
  `org.mutantcat.androidbox.smoke`; package manager confirms its installed path.
  The activity launches and Qt keyboard text appears in its EditText. This
  does not certify all key layouts, modifiers, Unicode or IME behavior.
- The desktop shutdown action sends ACPI powerdown and the guest exits cleanly
  without terminating QEMU forcibly.

Android guest networking (live check, 2026-09-20):

- Android 13 reported `sys.boot_completed=1`; its `eth0` received
  `192.168.240.112/24` with gateway and DNS `192.168.240.1` from the
  `androidbox0` dnsmasq bridge. ConnectivityManager showed an Ethernet
  network with `INTERNET` capability and a default route through that gateway.
- `ping -c 3 223.5.5.5` and `ping -c 3 8.8.8.8` both returned 0% packet loss
  (about 27 ms round trip through QEMU user-mode NAT).
- DNS resolution works inside Android: `ping -c 2 www.baidu.com` resolved and
  reached the Internet address.
- TCP/HTTPS works inside Android: `curl https://www.baidu.com` returned HTTP
  200 and `curl http://www.gstatic.com/generate_204` returned 204.
- The forwarding chain was confirmed from the Linux guest: `enp0s3` holds the
  QEMU NAT address `10.0.2.15/24` with default gateway `10.0.2.2`,
  `androidbox0` holds `192.168.240.1/24`, and the ADB bridge forwards Android
  port 5555 to a host-only QEMU forward.

Known integration issues:

- Mouse clicks can hit the notification shade instead of the visible target.
  DOM coordinates are correct; the downstream guest input path needs further
  investigation. Keyboard delivery is not evidence of correct pointer input.
- SystemUI repeatedly crashes in `AppOpsControllerImpl.setListening` during the
  first roughly 35-45 seconds, then stabilizes. This is not a clean boot result.
- The client waits up to 120 seconds for authorization; timeout and retry were
  exercised. The successful real install followed completed authorization.
  ADB first rejects incremental installation, then falls back to streamed
  installation and reports Success.
- Reading a UI hierarchy from Android shared storage failed with `Transport
  endpoint is not connected`; shared-storage/MediaProvider health needs work.
- AppArmor profiles are installed, but inherited profiles use complain mode.
  This test does not establish enforced container isolation.

The local guest and disposable integration assets are ignored under
`downloads/guest-test`; they are not a redistributable guest image. Its qcow2
overlay depends on its base disk. No Linux system was installed onto macOS.

## Not Yet Verified

Windows and Linux CI jobs have been added but not run remotely in this task.
Native Linux desktop runtime, KVM and WHPX need real-host validation. Running
the Linux container backend inside a VM is not native Linux host certification.
Frozen Windows/Linux builds, frozen noVNC/QEMU integration, Windows DLL search
behavior, and distribution signing/notarization still need validation.
The wheel is a Python package and needs a separately installed runtime. Desktop
installers now bundle QEMU and ADB; a bootable guest disk remains separate.
See [Guest Image](guest-image.md).

## Release Packaging (1.0.20260919)

On the local macOS ARM64 host:

- PyInstaller built the versioned AndroidBox application successfully.
- `scripts/package_desktop.py` generated the ARM64 DMG.
- Application deep/strict code-sign verification and DMG signature verification
  succeeded. Both use ad-hoc signatures, not Developer ID/notarization.
- `hdiutil verify` passed. The DMG mounted read-only and contained AndroidBox.app
  and an Applications shortcut; the image was detached after inspection.
- Mounted Info.plist reported `CFBundleShortVersionString=1.0.20260919` and
  `CFBundleVersion=2026.9.19`; the main executable was ARM64.
- actionlint 1.7.12 validated both GitHub workflows. An earlier actionlint version
  did not recognize GitHub's `macos-15-intel` runner label.
- Qt/noVNC desktop smoke test passed after the release changes.
- All 41 unit tests and Ruff passed. Download tests verify
  checksum rejection preserves an existing packaging tool and cleans up partial
  downloads. The official AppImageTool 1.9.0 x86_64 asset was downloaded and its
  pinned SHA256 verified locally, without executing the Linux binary on macOS.
- The frozen application passed `scripts/verify_frozen.py` in 1.61 seconds.
  After regenerating and ad-hoc signing the DMG, the same test passed from its
  read-only mounted application in 1.71 seconds. The image was then detached.
  The verifier clears PYTHONPATH, uses a temporary working/state directory and
  requires a passing frozen-app JSON report plus a rendered window screenshot.
  CI now runs it on every platform and through Linux's extracted AppImage.
- A frozen macOS startup stall was traced with process sampling to
  `HTTPServer.server_bind` performing reverse DNS on 127.0.0.1 on the GUI thread.
  The loopback-only asset server now skips unused hostname resolution; a
  regression test rejects any call to `socket.getfqdn` during its construction.
- `git diff --check` passed after the code and documentation changes.
- Local NSIS compilation was not performed: installing NSIS through Homebrew
  triggered a portable-Ruby update with a failed mirror URL and slow fallback;
  the installation was stopped. The Windows build job installs NSIS via Chocolatey.

Windows/Intel macOS/Linux installers and tag-to-Release publishing have not
been executed remotely. The workflow stages all four verified filenames and
SHA256SUMS before publishing, and refuses to overwrite an already-published
Release. These initial desktop client installers were not complete Android
distributions. Later runtime bundling is documented below; a clean provisioned
guest still needs distribution.

## Bundled QEMU Experiment

The macOS ARM64 application was rebuilt using
`ANDROIDBOX_QEMU_PREFIX=/opt/homebrew/opt/qemu`. PyInstaller collected QEMU
11.1.1, its dynamic dependencies, firmware/data and QEMU license files.

- Executed the frozen application's `--qemu-test --arch aarch64 --accel hvf`
  from `/tmp` with PATH restricted to `/usr/bin:/bin`, without a configured
  QEMU binary or firmware path. The embedded noVNC canvas showed TianoCore;
  nonuniform pixels, QMP running state, key submission and QMP quit passed.
- PyInstaller initially removed QEMU's Hypervisor entitlement, producing
  `HV_NO_DEVICE`. Targeted ad-hoc signing with `com.apple.security.hypervisor`
  fixed the reproduced failure. Bundle sealing no longer recursively overwrites
  that signature; deep/strict verification still checks nested code.
- A `DYLD_PRINT_LIBRARIES=1` QEMU version run reported 659 loaded images. A
  path audit accepted only the application bundle, `/System/` and `/usr/lib/`;
  no Homebrew or other external library path was used in that run.
- 51 unit tests passed, including bundled discovery/override, automatic ARM
  firmware, payload completeness and signing order. Ruff and diff checks passed.
- The experimental DMG passed signature and image checksum verification. The
  HVF/noVNC integration test also passed from its read-only mounted application,
  still using the restricted PATH and automatic firmware discovery. The test
  terminated QEMU and the image was detached afterwards.

This verifies a bundled firmware boot on this macOS host, not a bundled Android
guest or deployment on a clean/older machine. Homebrew's local QEMU was built
for macOS 26; CI deployment targets and complete dependency license/source
distribution need review before publishing Releases. At this stage the
`dist/installers` client DMG remained separate from the experiment in
`dist/runtime-experiment`; the current installer has since been rebuilt with
the runtime payload. A production guest is not bundled.

## Bundled ADB and Installer Checks

The experimental ARM64 app and DMG were rebuilt with QEMU plus
`ANDROIDBOX_ADB_DIRECTORY=/Volumes/Old_Solidity/Android/sdk/platform-tools`.
The latter collects ADB, NOTICE.txt and source.properties. On Windows it also
requires AdbWinApi.dll and AdbWinUsbApi.dll; the QEMU collector gathers adjacent
DLLs. These Windows payload rules are fixture-tested, not native execution tests.

- All 64 unit tests passed, as did Ruff, actionlint 1.7.12, version-tag validation
  for `v1.0.20260919`, and `git diff --check`.
- Frozen runtime verification from `/tmp` with PATH restricted to `/usr/bin:/bin`
  passed in 1.75 seconds. Reports identify bundle-local QEMU 11.1.1 and ADB
  37.0.0 (protocol version 1.0.41), not system fallbacks.
- The rebuilt app passed aarch64/HVF authenticated noVNC framebuffer, QMP status,
  key submission and shutdown checks using a disposable blank disk.
- The rebuilt ad-hoc-signed DMG passed image and application signature checks
  and `hdiutil verify`. Its read-only mounted application passed the strict
  runtime and Qt/noVNC checks in 1.76 seconds, still with restricted PATH.
  Both reported runtime paths were inside the mounted volume; it was detached.
- `scripts/verify_frozen.py --require-runtime` rejects absent payload reports;
  the application checks native QEMU, data/ARM firmware and ADB, executing version
  commands with bounded subprocess timeouts. This does not start an ADB server.
- The workflow now tests the mounted DMG and silently installed Windows package
  as well as the previously tested extracted AppImage. Windows installation uses
  a directory with spaces and uninstalls in cleanup. Remote CI is still unrun.

Linux bundled executables retain PyInstaller's private library search path;
external executables restore the original path. Windows inherited DLL search
handling is implemented below but still requires native validation. Runtime
bundling was opt-in at this stage. The current Release workflow enables it, but
complete dependency licensing/source distribution, deployment targets, native
Windows/Linux validation and a clean production guest are still pending.

## Subprocess Portability

QEMU probes, VM launch, bundled runtime verification and ADB commands now share
the same subprocess helper. On frozen Windows builds it restores the system DLL
search policy for external executables, removes only bundle-private PATH entries
from their environment, and restores the host application's DLL directory
immediately after process creation, including failed spawns. Bundled binaries
retain their private dependencies. Windows child console windows are suppressed.
Our Python spawns are serialized around the process-global DLL directory change;
this is not isolation from unrelated native threads loading DLLs at that moment.

The command helper captures UTF-8 output, propagates nonzero exit codes and
kills/reaps timed-out children. Unit tests exercise these paths, including real
short-lived Python children. All 70 applicable tests pass locally; the additional
Windows-native test sets a real DLL directory and checks that an external child
does not inherit it. It is skipped on macOS and will run in Windows CI.
The build matrix now runs the test suite on each native packaging runner.
Ruff and actionlint pass. A source-application aarch64/HVF QEMU/noVNC test passed
after these changes, with a disposable blank disk; it does not certify Android.
The macOS application was rebuilt and ad-hoc signed after the subprocess changes;
its frozen Qt/noVNC and required bundled QEMU/ADB verification passed from `/tmp`
with restricted PATH in 1.75 seconds. The experimental DMG from the preceding
section predates this subprocess change and was not regenerated in this check.

## Current Bundled Release Validation (2026-09-20)

The four-runner Release workflow now bundles native QEMU and Android Platform
Tools. Windows uses Chocolatey QEMU 2026.8.11, macOS uses Homebrew QEMU, and Linux
uses Ubuntu's qemu-system-x86 package. Platform Tools 37.0.1 archives are pinned
per OS and checked against both SHA1 and SHA256 before replacing the target.
Missing ADB license notices reject the archive without replacing an existing
installation. Windows QEMU data layouts and Debian license paths are covered
by fixture tests.

The workflow requires bundled-runtime checks on the frozen executable and again
on the installed NSIS payload, mounted DMG or extracted AppImage. NSIS's `/D=`
and `_?=` arguments are last and unquoted, as its command-line parser requires,
including for paths containing spaces. All four installers and `SHA256SUMS`
must be present before the draft Release is published. A pushed version tag
must match the code version; manual runs only upload CI artifacts.

Fresh local results on macOS ARM64:

- Unit suite: 78 tests, 77 passed and one Windows-native test skipped.
- Ruff, actionlint 1.7.12, `v1.0.20260919` metadata validation and diff whitespace
  checks passed.
- PyInstaller rebuilt `dist/AndroidBox.app` with QEMU 11.1.1 and ADB 37.0.1.
  Required-runtime and Qt/noVNC checks passed outside the checkout with restricted
  PATH, reporting bundle-local executables rather than system fallbacks.
- The signed frozen app passed the aarch64/HVF blank-disk test: authenticated
  noVNC, nonuniform framebuffer, QMP running state, key submission and QMP quit.
  The screenshot showed TianoCore. This is a firmware test, not an Android boot.
- `dist/installers/AndroidBox-1.0.20260919-macOS-arm64.dmg` was regenerated from
  this app. Ad-hoc signatures, app deep/strict verification and `hdiutil verify`
  passed. Its read-only mounted app passed the Qt/noVNC and required QEMU/ADB
  checks in 1.76 seconds; the volume was detached successfully.

Windows, Intel macOS and Linux installers, and GitHub tag-to-Release publication,
have not been executed remotely in this task. Ad-hoc signing is not notarization;
Gatekeeper can still block downloads, Windows may show SmartScreen warnings, and
AppImage use can require executable permission or FUSE setup. The local Homebrew
QEMU targets macOS 26, so this build does not establish older-macOS compatibility.
Complete dependency license/source redistribution still needs review. A clean
bootable guest is not bundled, and the Android integration issues above remain
open: these are not yet verified one-click Android distributions.

## First-Launch Defaults (2026-09-20)

- Unit suite: 88 tests, 87 passed and one Windows-native test skipped on macOS.
  Covers host-based CPU/RAM defaults and bounds, preservation of saved settings,
  partial configuration, managed-disk discovery, unreadable managed disks,
  disk-header format detection and external ARM firmware discovery.
- Ruff and diff whitespace checks passed.
- Source Qt/noVNC smoke passed, including initially hidden logs, toolbar toggling,
  first-start disk selection and persistence. The disk picker and VM submission
  are mocked in this UI test; it does not start a guest.
- A separate real x86_64 QEMU run on the ARM64 host with automatic acceleration
  selected TCG and passed authenticated noVNC framebuffer and QMP checks. The
  screenshot shows firmware with the log panel hidden. This blank-disk test
  does not establish Android bootability or hardware-accelerator failure recovery.
- Rebuilt the bundled macOS ARM64 app and ad-hoc-signed installer at
  `dist/installers/AndroidBox-1.0.20260919-macOS-arm64.dmg`.
  Signature and image checks passed. Its read-only mounted application passed
  the updated Qt/noVNC self-test and required QEMU/ADB verification in 2.22
  seconds, with restricted PATH. The volume was detached successfully.

Automatic defaults do not download or create a guest disk. Users still need a
compatible bootable disk and must select its architecture if it differs from
the host. The platform and distribution limitations above still apply.

## Published Release 1.0.20260920 (2026-09-20)

The remote checks below supersede earlier statements that CI and publication
had not run. Tag `v1.0.20260920` points to commit `aca5dac`.

- [Tag-triggered installer workflow](https://github.com/Mutantcat-Working-Group/AndroidBox/actions/runs/35481871760):
  validation, all four native build jobs and publication succeeded.
- Windows Server 2022: NSIS compilation with warnings treated as errors passed.
  Installation to a path containing spaces, correctly quoted registry uninstall
  commands, installed application Qt/noVNC and bundled-runtime checks, and
  silent uninstall passed.
- macOS 15 ARM64 and Intel: frozen application checks, ad-hoc app/DMG signing
  and verification, and read-only mounted DMG application checks passed.
- Ubuntu 22.04 x86_64: frozen application checks, AppImage creation, extraction
  and extracted AppRun Qt/noVNC and bundled QEMU/ADB checks passed.
- [Regular CI on the release commit](https://github.com/Mutantcat-Working-Group/AndroidBox/actions/runs/35481871722):
  portable tests and real QEMU display tests on Windows, macOS and Linux, lint
  and CodeQL all passed. QEMU tests use blank disks, not Android guest images.
- [Release v1.0.20260920](https://github.com/Mutantcat-Working-Group/AndroidBox/releases/tag/v1.0.20260920)
  was published at 2026-09-20 01:46:53 UTC, not as a draft or prerelease.
  It contains the Windows x86_64 NSIS installer, macOS ARM64 and x86_64 DMGs,
  Linux x86_64 AppImage and SHA256SUMS. The downloaded manifest's four hashes
  match GitHub's reported SHA256 asset digests.

The previous missing Release was caused by pushing only the branch: installer
publication requires a matching `v*` version tag. Manual dispatch builds
artifacts without publishing. Release commands explicitly target this fork
through `GH_REPO`, not the upstream repository.

## Real-Guest Performance Measurements (2026-09-20)

A live guest was started from the verified example disk
`downloads/guest-test/androidbox-test.qcow2` (Ubuntu 24.04 + Waydroid,
Android 13 arm64_only) with HVF, 4 vCPUs, 4096 MiB RAM, VNC and ADB on
127.0.0.1. The guest reported a 1280x800 display at 74 Hz and identified its
graphics pipeline as Skia/OpenGL, which confirms software rendering inside
Waydroid with no host GPU involvement.

- Notification shade animation over a 5 second continuous swipe: 331 frames at
64.9 fps, and 321 frames at 63.8 fps on a second run. Janky frames 1.3-3.1%,
frame time p50 5 ms, p90 7-9 ms, p99 69-113 ms. This is measured on the guest
display, so the VNC encoding path does not lower it.
- The host QEMU process consumed about 1.5 cores and 4.5 GiB RSS during that
animation, and idle Android used under 1% guest CPU.
- Launcher-drawer and smoke-app traces were inconclusive because those surfaces
were not animating during the capture window.

## Performance Options Boot Test

The new CPU model, disk cache and TCG thread options were exercised on a blank
ARM64 disk with every knob set to its most aggressive value
(`-accel tcg,thread=multi`, `-cpu max`, `cache none`). QEMU 11.1.1 accepted the
command line, QMP served requests for the full observation window, and the
ARM64 serial console showed edk2 firmware executing: it read the TPM, reported
the X64 image as unsupported on AARCH64 and stopped with no bootable image on a
disk that has no EFI partition, which is the expected result for a blank disk.

On the hardware-accelerated guest the same options are inert: KVM, HVF and WHPX
ignore the TCG thread setting, and `host` remains the CPU model whenever
passthrough is available.

These checks validate bundled desktop clients on CI runners. They do not
certify clean end-user machines, all hardware accelerators or full Android
compatibility. No bootable Linux/Android guest is included. The Android input,
SystemUI and shared-storage issues documented above remain open. macOS ad-hoc
signatures are not notarization; Gatekeeper and Windows SmartScreen warnings
remain possible, and AppImage may require executable permission or FUSE.
Complete dependency license/source redistribution still needs review.

## AArch64 Linux Bundled ADB (2026-09-20)

`scripts/fetch_platform_tools.py` selected its archive by operating system
only, so the Linux ARM64 build downloaded `platform-tools_r37.0.1-linux.zip`,
which is an x86_64 ELF build. The frozen application then failed its runtime
check with `[Errno 8] Exec format error` on the bundled `adb`, because a
bundled runtime takes precedence over the system `adb` on `PATH`.

Google publishes Platform Tools for macOS and Windows only; the repository
manifest at `dl.google.com/android/repository` carries no AArch64 Linux asset,
so there is nothing to pin for that host. Registering `qemu-user-static` with
`update-binfmts` was tried instead and also failed: `adb version` exited 255
under user-mode emulation, and the approach would still have shipped an x86_64
binary that end users could not execute.

The Linux ARM64 build now installs the distribution's `adb` package plus
`patchelf`, and `install_distribution()` stages that executable together with
the shared libraries `ldd` reports, skipping the loader and libc so those still
come from the host. `set_runpath()` gives the staged binary an `$ORIGIN/lib`
runpath so it resolves those libraries wherever the AppImage is extracted, and
`collect_adb()` stages them into `runtime/lib`. `require_runnable()` executes
`adb version` before the payload replaces the previous one, so a build fails
instead of shipping an ADB the host cannot run. Unit tests cover the archive
selection, the staging layout, the host-library exclusions and both
`require_runnable()` outcomes.

This makes the bundled ADB architecture-correct on all five release targets.
The AppImage still depends on the host for QEMU's kernel modules and for the
caveats listed under Not Yet Verified, which continue to apply.

## macOS Intel Disk Image (2026-09-21)

The `macos-15-intel` build of run 35511627755 reached `Create NSIS or signed
DMG` and failed there with `hdiutil: create failed - Resource busy`, while the
identical `macos-15` arm64 step succeeded minutes earlier on another runner.
Nothing in the application changed between the two jobs, so the failure came
from the runner state rather than the payload.

`scripts/package_desktop.py` now builds the image through `create_dmg()`, which
detaches any volume already claiming the `AndroidBox` name before it starts and
retries the create once after a short settle. The retry runs through the checked
`run()` helper, so a failure that persists still aborts the build with the
command output visible instead of being swallowed. `tests/test_dmg_packaging.py`
covers the mount-table parsing, the detach, both create outcomes and the staging
layout `package_mac()` hands to the helper.

## Linux Qt XCB Plugin Libraries (2026-09-21)

The `ubuntu-22.04` job of run 35542708425 finished every step, but its
PyInstaller analysis reported nine `Library not found` warnings, all of them
from Qt's xcb stack rather than from the bundled QEMU:

```text
WARNING: Library not found: could not resolve 'libxkbcommon-x11.so.0',
  dependency of '.../PySide6/Qt/plugins/platforms/libqxcb.so'.
WARNING: Library not found: could not resolve 'libxcb-shape.so.0',
  dependency of '.../PySide6/Qt/plugins/platforms/libqxcb.so'.
WARNING: Library not found: could not resolve 'libxcb-xkb.so.1',
  dependency of '.../PySide6/Qt/plugins/platforms/libqxcb.so'.
```

PyInstaller only bundles a dependency it can resolve on the analysis host, so
an AppImage built without those three libraries carries an xcb platform plugin
that cannot load. The result is the exact opposite of "click and it runs": on a
Linux machine that does not already provide `libxkbcommon-x11-0`,
`libxcb-shape0` and `libxcb-xkb1`, the frozen application aborts before its
first window appears.

No QEMU dependency was among the missing entries, which settles a question this
document previously answered the wrong way. PyInstaller's `Analysis` runs
`find_binary_dependencies()` over the collected binaries and resolves ELF
imports recursively through `ldd`, excluding only the loader and libc pieces.
QEMU's shared libraries are therefore bundled already, and the AppImage does not
lean on the host for them.

The fix is confined to the Linux prerequisite step of `.github/workflows/desktop.yaml`,
which now installs `libxkbcommon-x11-0`, `libxcb-shape0` and `libxcb-xkb1` in
both the x86_64 and the AArch64 branches. Note the Debian package that ships
`libxcb-xkb.so.1` is named `libxcb-xkb1`, not `libxcb-xkb0`; the library soname
and the package name diverge, and none of the three took the `t64` suffix that
`libasound2` and `libminizip1` picked up on Ubuntu 24.04 ARM. All three are
present under the same name for `amd64` and `arm64` in both jammy and noble.

Run 35542708425 built all five installers successfully, so this gap did not
block a release; it would have surfaced as a runtime failure on a minimal Linux
desktop instead.

## Installer Workflow Consolidation (2026-09-21)

The build job in `.github/workflows/desktop.yaml` had reached 24 steps, and most
of the growth was one step per operating system for the same action: three
prerequisite installs, two bundled-ADB path exports, three frozen-application
verifications and two packaging invocations. Each group differed only in the
path or flag it passed, so the file was describing five targets five times.

Those groups now run under `shell: bash` with a `case` on `runner.os`, or as a
single unconditional command. The job is 15 steps and does exactly what it did
before. Bash is present on all three runners, which is what makes the collapse
possible.

Two details were worth confirming rather than assuming. GitHub sets
`GITHUB_WORKSPACE` as a Windows path, so bash expands it with backslashes and
the ADB export ends up as `D:\a\AndroidBox\AndroidBox/build/platform-tools` with
mixed separators; `pathlib` normalises those when `desktop.spec` resolves the
directory, and the frozen self-test reports its ADB version, so the value is
usable as written. And `choco install` under Git Bash honours `set -e`, so a
failed package still aborts the step instead of being swallowed the way the
previous `$LASTEXITCODE` guards had to check explicitly.

The build job also no longer repeats the unit tests and the Qt smoke test on all
five runners. Those are pure Python and platform independent, and the
per-platform proof a build actually needs is `verify_frozen.py
--require-runtime`, which already fails when the frozen window does not render
or when the bundled QEMU and ADB do not report a version. The Windows-only DLL
inheritance test still runs in `check.yaml`, which covers all three operating
systems. The AppImage extraction step gained `set -euo pipefail` so a failed
extract aborts at the extract instead of leaning on the following `test` to
notice.

Run 35544783411 confirmed the result: `validate` in 39s, then all five build
jobs green, with `release` skipped as expected for a `workflow_dispatch`. The
artifact names are unchanged, so the ten-artifact contract in
`scripts/release_metadata.py` still holds.

## Guest Disk Preparation TLS Failure (2026-09-21)

A user installed `AndroidBox-1.0.20260921-macOS-arm64.dmg`, clicked **Prepare
example guest disk**, and got:

```text
Cannot reach https://cloud-images.ubuntu.com/minimal/releases/noble/release/SHA256SUMS:
<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate (_ssl.c:1010)>
```

The host could reach that URL directly with both `curl` and `urllib`, so this was
not a network problem.

### Root Cause

`strings` on the bundled `libcrypto.3.dylib` showed `OPENSSLDIR:
"/opt/homebrew/etc/openssl@3"`, sourced from Homebrew's
`openssl@3/3.6.3`. The library is not a direct dependency: it is dragged in by
the QEMU payload through `libgnutls` -> `libnettle`/`libhogweed` -> `libp11-kit`
-> `libcrypto`. That directory exists on the build machine but not on the user's
machine, so `SSL_CTX_set_default_verify_paths()` loaded zero CAs and every
verification failed with an issuer error. The bundle also shipped no CA
certificates of its own, so there was nothing to fall back to. The Windows build
has the same shape with the MSYS2 OpenSSL path.

### Fix

`guestdisk.ssl_context()` now builds its context with an explicit
`cafile=certifi.where()`. This is decisive rather than incidental: with `cafile`
set, CPython's `create_default_context` calls only `load_verify_locations` and
skips `load_default_certs()` entirely, so verification is anchored exclusively to
the bundled bundle and never consults the host OpenSSL configuration. `certifi`
joined the `desktop` extra and `packaging/desktop.spec` now collects its data
files, so the frozen application carries its own CA store.

Reproduced the failure mode by overriding OpenSSL's search path with
`SSL_CERT_FILE`/`SSL_CERT_DIR` pointing at nonexistent locations, which is what
the user's machine effectively sees:

```text
host store CAs: 0                    <- the user's failure
certifi-anchored CAs: 121
HTTPS with certifi: 200 2174 bytes
```

Also confirmed the mechanism survives freezing: a throwaway PyInstaller build
reported `CERTIFI_WHERE: .../\_internal/certifi/cacert.pem`, `EXISTS: True`,
`CA_COUNT: 121` and a 200 response, and its `certifi` data layout (only
`cacert.pem` and `py.typed` on disk, the module in the PYZ) is identical to the
rebuilt `AndroidBox.app`.

### Supporting Changes

- Mirror fallback to `mirrors.ustc.edu.cn` and `mirror.nju.edu.cn`, both verified
  to publish a manifest byte-identical to the official one (same 2174-byte
  `SHA256SUMS`, digest `2d430162ceddeea4...`), so the digest still comes from
  Ubuntu.
- Retries with backoff, and resumable transfers via HTTP `Range`; a partial file
  survives a failed attempt and is discarded only on a checksum mismatch.
- A **Use a local image** entry point wired to the `local_image` parameter that
  `ensure_base_image()` already accepted.
- Failures now report through a details-enabled dialog, since one line per mirror
  does not fit a plain message label.

An end-to-end run of `guestdisk.prepare("aarch64", ...)` against the live network
produced the managed `androidbox-aarch64.qcow2` (197120 bytes) plus a verified
base image, with 219 progress reports whose totals matched the manifest size.

### Bundling An Image Was Measured And Rejected

The image is effectively incompressible (229,113,856 bytes gzip to 225,597,382),
so shipping one inside each installer would roughly double installer size, about
+1.2 GiB across the five installers. The mirror fallback and the local-image path
cover the restricted-network and offline cases at no size cost.
Bundling an image was measured and rejected: it is effectively incompressible (229
MB gzips to 226 MB), so each installer would roughly double in size for about
+1.2 GiB across the five installers. The mirror fallback and the local-image path
cover the restricted-network and offline cases at no size cost.

## Published Release 1.0.20260922 (2026-09-21)

Tag `v1.0.20260922` points at `4f859bd`. Run
[35550816996](https://github.com/Mutantcat-Working-Group/AndroidBox/actions/runs/35550816996)
passed all seven jobs: `validate`, the five platform builds and `release`. The
published release carries the ten installers plus `SHA256SUMS`.

| Asset | Size |
| --- | --- |
| `AndroidBox-1.0.20260922-Windows-x86_64-Setup.exe` | 214 MiB |
| `AndroidBox-1.0.20260922-macOS-arm64.dmg` | 257 MiB |
| `AndroidBox-1.0.20260922-macOS-x86_64.dmg` | 264 MiB |
| `AndroidBox-1.0.20260922-Linux-x86_64.AppImage` | 224 MiB |
| `AndroidBox-1.0.20260922-Linux-aarch64.AppImage` | 218 MiB |

Each platform also ships a portable `tar.gz` alongside its installer. The two
macOS images grew by roughly 5-7 MiB against 1.0.20260921, which is the bundled
`certifi` CA store plus the local-image dialog.

The two macOS builds spent about 25 minutes queued for a runner before
executing, inside the 45 minute job timeout, so the release took roughly 40
minutes end to end. The queue wait is GitHub runner capacity, not a build
regression.
