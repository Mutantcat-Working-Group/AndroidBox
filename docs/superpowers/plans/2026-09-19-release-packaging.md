# AndroidBox Release Packaging

Goal: version 1.0.20260919 with NSIS, two ad-hoc-signed macOS DMGs,
and a Linux AppImage attached to a tag-triggered GitHub Release.

Architecture: native PyInstaller builds feed platform packaging scripts.
Validate all source version declarations and the triggering tag before building.
Collect exactly four named artifacts and stream their SHA256 digests before
creating a Release. Do not publish a partial set. Manual builds only upload CI
artifacts. Stage assets in a draft and publish only after every upload succeeds.
Release notes explicitly identify the incomplete one-click runtime requirement.

- [x] Add failing tests for version consistency, Windows numeric version
  encoding, invalid tags and complete artifact collection.
- [x] Update current source versions, retaining third-party and historical versions.
- [x] Implement release metadata and installer tooling with strict subprocess errors.
- [x] Add per-user NSIS installer, AppDir launcher/metadata, signed DMG creation.
- [x] Replace ZIP-only workflow with tests, native build matrix and Release job.
- [x] Run unit tests, Ruff, workflow/static checks and real macOS DMG build,
  signature verification, mount and bundle inspection.
- [ ] Bundle QEMU, ADB and provisioned guest images or provide a verified first-run
  bootstrap. The online/offline distribution choice is still awaiting user input.
- [x] Prototype local macOS native QEMU/firmware collection, bundled discovery
  and Hypervisor entitlement signing; validate frozen and mounted-DMG HVF/noVNC
  firmware boot. Release dependency sources/licenses and other hosts remain open.
- [x] Collect optional bundled ADB with notices and Windows companion DLLs;
  add strict bundled-runtime self-tests and installer-level DMG/NSIS CI checks.
- [ ] Validate installed Windows/macOS/Linux Android workflows and complete
  one-click runtime requirements.

Windows PE versions have four unsigned 16-bit fields. Encode 1.0.20260919
as 1.0.2026.919 in numeric metadata; display the full requested version in
ProductVersion, installer UI, package names and registry entries.

No commit, tag push or remote publication is part of local implementation.
