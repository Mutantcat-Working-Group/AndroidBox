## AndroidBox Desktop Preview

Artifacts: Windows x64 NSIS installer, macOS Apple Silicon and Intel DMGs,
Linux x64 AppImage, and SHA256SUMS.

QEMU, ADB and a prepared guest disk are still separate prerequisites.
These installers contain the desktop client, not yet a one-click Android runtime.
See docs/verification.md for guest input, storage and platform validation gaps.

macOS applications and DMGs use ad-hoc signatures, not Developer ID or Apple
notarization. Gatekeeper may block downloaded applications. Windows installers
are unsigned and may trigger SmartScreen. AppImage requires an executable bit
and a compatible Linux desktop (glibc 2.35+); FUSE2 may be required, or use
APPIMAGE_EXTRACT_AND_RUN=1. No sandbox disabling is required by the launcher.

Existing guest disks and user settings are not removed by the Windows uninstaller.
