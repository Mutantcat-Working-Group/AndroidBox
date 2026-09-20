# Local Verification

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
