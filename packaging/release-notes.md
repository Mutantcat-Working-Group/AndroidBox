## AndroidBox Desktop Preview

## AndroidBox 1.0.20260923

This release fixes the UEFI Shell boot failure on prepared example disks.
Ubuntu's minimal cloud `.img` files are QCOW2 containers, and AndroidBox now
records the real backing format when creating an overlay and repairs an
existing mismatched overlay before QEMU starts, so the guest reaches GRUB
instead of the firmware shell. Existing guest disks are patched in place;
downloads, settings and guest data are preserved.

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
