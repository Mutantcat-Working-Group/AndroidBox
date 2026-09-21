## AndroidBox Desktop Preview

## AndroidBox 1.0.20260924

This release makes the example guest fully self-serve on first boot. Preparing
a guest disk now also writes a NoCloud `cidata` seed beside the QCOW2 overlay.
The first boot creates the `ubuntu` account with the documented default
password `androidbox`, enables virtual-console autologin, installs the Binder
modules, extracts the bundled provisioning payload, and runs the guest
provisioner before rebooting into the Android session. The first boot downloads
the Android images, so it can take several minutes; existing managed disks get
the same seed when the app starts.

Logs are collapsed by default. First launch detects host architecture, CPU and
memory defaults, QEMU and ARM firmware. Select a compatible bootable guest disk
on first Start; the disk selection is saved for subsequent launches.

Artifacts: Windows x64 NSIS installer, macOS Apple Silicon and Intel DMGs,
Linux x64 and ARM64 AppImages, and SHA256SUMS.

The installers bundle the QEMU compatibility layer and Android Platform Tools.
A prepared bootable Linux/Android guest disk is still a separate prerequisite.
See the repository's [guest image guide](https://github.com/Mutantcat-Working-Group/AndroidBox/blob/main/docs/guest-image.md)
and [verification record](https://github.com/Mutantcat-Working-Group/AndroidBox/blob/main/docs/verification.md)
for guest input, storage and platform validation gaps.

macOS applications and DMGs use ad-hoc signatures, not Developer ID or Apple
notarization. Gatekeeper may block downloaded applications. Windows installers
are unsigned and may trigger SmartScreen. AppImage requires an executable bit
and a compatible Linux desktop (glibc 2.35+); FUSE2 may be required, or use
APPIMAGE_EXTRACT_AND_RUN=1. No sandbox disabling is required by the launcher.

Existing guest disks and user settings are not removed by the Windows uninstaller.
