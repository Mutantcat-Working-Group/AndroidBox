## AndroidBox Desktop Preview

## AndroidBox 1.0.20260928

This release ships the Android system inside every installer, so an installed
AndroidBox reaches the Android launcher without downloading anything on first
boot. Preparing a guest disk still writes a NoCloud `cidata` seed beside the
QCOW2 overlay: the first boot creates the `ubuntu` account with the documented
default password `androidbox`, enables virtual-console autologin, builds the
in-guest gbinder stack from vendored sources (Ubuntu noble publishes no
`python3-gbinder` package), persists the binder device names through
`/etc/modprobe.d`, unpacks the bundled `system` and `vendor` images, and runs
the guest provisioner before rebooting into the Android session. Existing
managed disks get the same seed when the app starts.

The images ride on a read-only ext4 disk labelled `androidbox-img`, attached to
the guest after the system disk and the seed. The client falls back to the
Waydroid OTA channels only when that disk is missing or fails verification, so
first boot no longer depends on the host TLS chain reaching SourceForge.

The Android container survives reboots now: `binder_linux` keeps its device
names across restarts, so `/dev/binder` exists again and the container starts
unattended instead of dying with `Can't open /dev/binder`.

Logs are collapsed by default. First launch detects host architecture, CPU and
memory defaults, QEMU and ARM firmware. Select a compatible bootable guest disk
on first Start; the disk selection is saved for subsequent launches.

Artifacts: Windows x64 NSIS installer, macOS Apple Silicon and Intel DMGs,
Linux x64 and ARM64 AppImages, and SHA256SUMS. Installers are around 1 GiB each
because they carry the Android images.

The installers bundle the QEMU compatibility layer and Android Platform Tools.
A prepared bootable Linux guest disk is still a separate prerequisite.
See the repository's [guest image guide](https://github.com/Mutantcat-Working-Group/AndroidBox/blob/main/docs/guest-image.md)
and [verification record](https://github.com/Mutantcat-Working-Group/AndroidBox/blob/main/docs/verification.md)
for guest input, storage and platform validation gaps.

macOS applications and DMGs use ad-hoc signatures, not Developer ID or Apple
notarization. Gatekeeper may block downloaded applications. Windows installers
are unsigned and may trigger SmartScreen. AppImage requires an executable bit
and a compatible Linux desktop (glibc 2.35+); FUSE2 may be required, or use
APPIMAGE_EXTRACT_AND_RUN=1. No sandbox disabling is required by the launcher.

Existing guest disks and user settings are not removed by the Windows uninstaller.
