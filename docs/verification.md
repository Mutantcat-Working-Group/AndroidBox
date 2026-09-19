# Local Verification

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
The wheel is a Python package. Installer generation is described below;
QEMU and a guest disk remain separate prerequisites.
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
Release. These are desktop client installers, not complete Android distributions:
QEMU, ADB, guest firmware and a clean provisioned guest still need distribution.

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
distribution need review before enabling this payload in published Releases.
The existing `dist/installers` client DMG remains separate from the experiment
in `dist/runtime-experiment`. A production guest is not bundled.

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
handling is implemented below but still requires native validation. Runtime bundling is still opt-in and not enabled in the
Release workflow: complete dependency licensing/source distribution, deployment
targets, native Windows/Linux validation and a clean production guest are pending.

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
