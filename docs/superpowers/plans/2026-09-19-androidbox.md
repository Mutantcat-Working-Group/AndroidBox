# AndroidBox Cross-Platform Implementation Plan

**Goal:** Rename the host product to AndroidBox (org.mutantcat.androidbox) and add a Qt desktop application controlling a QEMU Linux guest, with Linux-native access retained.

**Architecture:** The portable `androidbox` package must not import the Linux-only `tools` package. QEMU provides a Linux guest, whose existing LXC runtime runs Android. A local-only noVNC display is embedded in Qt WebEngine. Guest provisioning is explicit; upstream Android partition images are not bootable VM disks.

**Tech Stack:** Python 3.10+, PySide6, QEMU with native WebSocket support, noVNC; existing Linux LXC, D-Bus and Binder backend. A separate websockify process is not required.

## Scope and Compatibility

- Host name: AndroidBox; desktop/application ID: org.mutantcat.androidbox.
- Native command and package: androidbox; native runtime state: /var/lib/androidbox.
- Preserve image-side lineageos.waydroid interfaces, waydroid properties, special full-UI token, OTA URLs and external waydroid-sensord executable.
- Do not migrate or delete existing Waydroid data.
- QEMU guests: x86_64 and aarch64. Prefer same-architecture KVM/HVF/WHPX if advertised and available; explicit TCG fallback, never a silent performance downgrade.
- Guest display is embedded; no GPU acceleration or universal APK compatibility claim.
- Windows, Linux and macOS runtime validation requires actual hosts and prepared guest images.

## Tasks

- [x] Add regression tests for product IDs, desktop/service references and guest protocol compatibility. Run failing tests before renaming.
- [x] Rename host files, paths, D-Bus/polkit IDs and packaging. Preserve external contracts and attribution; document retained names.
- [x] Test and implement portable configuration, QEMU architecture/accelerator selection, command construction, lifecycle cleanup and QMP shutdown.
- [x] Add a Qt desktop window with settings, embedded noVNC display, start/stop, APK installation, native Linux launch and logs. Missing dependencies and guest disks must produce actionable errors.
- [x] Add reproducible noVNC asset acquisition and guest provisioning instructions/scripts. Do not download multi-GB OS images automatically or run host system installation scripts.
- [x] Verify unit tests, lint, shell/XML syntax, packaging staging and offscreen UI behavior; report unverified platform/guest functionality.
- [x] Build and start a frozen macOS client; add Windows/Linux/macOS build workflows.
- [x] Validate actual authenticated QEMU firmware display on macOS with x86_64/TCG and aarch64/HVF.
- [x] Provision and boot a real ARM64 Android guest on macOS/HVF; verify the launcher, keyboard, ADB authorization and ACPI shutdown.
- [ ] Provision and boot a real Android guest; validate input, APK installation and graceful shutdown on Windows/WHPX, macOS/HVF and Linux/KVM.

## Verification

Run `python -m unittest discover -s tests -v`, `ruff check .`, shell syntax checks, and a temporary-directory `make install DESTDIR=...` staging run. GUI tests use `QT_QPA_PLATFORM=offscreen`; real Android guest checks remain separate from firmware and unit tests.

Local results are recorded in [Verification](../../verification.md).
