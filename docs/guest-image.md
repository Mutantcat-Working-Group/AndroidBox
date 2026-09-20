# AndroidBox Guest Image

The desktop client needs a **bootable Linux VM disk**. Waydroid `system.img` and
`vendor.img` are Android filesystem partitions, not bootable QEMU disks.
This repository does not publish or automatically download a prepared VM image.
The recipe below has not yet been validated by booting Android on all hosts.

## Build a Dedicated Guest

1. Install a minimal Debian-family Linux system into a writable QCOW2 disk using
   QEMU or another VM installer. Allocate at least 32 GiB of disk and 4 GiB RAM.
   The guest requires systemd, virtio block/network/GPU drivers and a kernel with
   `CONFIG_ANDROID_BINDER_IPC=y/m` and `CONFIG_ANDROID_BINDERFS=y`.
   On Ubuntu a generic kernel plus its matching extra modules may be needed.
2. Install `python3-gbinder` from a trusted distribution/Waydroid package source
   if it is not in the distribution's repositories. The provisioning script does
   not add repositories or execute remote installer scripts.
3. Copy this checkout into the guest. Review `guest/provision.sh`, then run:

   ```sh
   sudo bash guest/provision.sh --dedicated-guest
   sudo reboot
   ```

   This installs the native AndroidBox runtime, downloads upstream Android
   images, enables the container service, and configures greetd to start a Cage
   Wayland session automatically as the unprivileged `androidbox` user.
   Use a minimal guest without another display manager. The script replaces
   `/etc/greetd/config.toml`; do not run it on a general-purpose desktop.
4. Shut down the guest cleanly before selecting its disk in AndroidBox Settings.
   Never open the same writable disk from two VM applications simultaneously.

### Ubuntu Minimal Cloud Images

The macOS ARM64 integration run uses Ubuntu 24.04 minimal cloud images with
NoCloud SSH-key provisioning. Download the matching architecture from
`https://cloud-images.ubuntu.com/minimal/releases/noble/release/` and verify its
SHA-256 against that directory's `SHA256SUMS` before booting it. A mirror download
must match the official checksum too. Keep the base image if using a QCOW2 overlay;
the overlay alone is not a portable, standalone disk.

The tested ARM64 image boots kernel `6.8.0-139-generic`, but does not include its
Binder module by default. Inside the guest, before running the provisioner:

```sh
sudo apt-get update
sudo apt-get install "linux-modules-extra-$(uname -r)"
sudo modprobe binder_linux devices=binder,hwbinder,vndbinder
```

The `python3-gbinder` dependency is available from the upstream Waydroid Debian
repository (`https://repo.waydro.id`, suite `noble`, component `main`). Configure
its signing key with an explicit `Signed-By` keyring; do not disable apt signature
checks. NoCloud credentials should use a unique SSH public key, locked passwords,
and an SSH host forward bound only to `127.0.0.1`. Do not distribute test keys or
seed media with a release image.

On Apple Silicon the guest may not support AArch32. Leave architecture detection
to `androidbox init`: this run selected the upstream `waydroid_arm64_only` system
and vendor channels. Do not substitute ordinary `arm64` partition images merely
because QEMU's machine architecture is `aarch64`.

## Architecture and Firmware

Use x86_64 guests for x86_64 hosts, aarch64 guests for Apple Silicon/ARM64 hosts.
Cross-architecture guests use slow TCG emulation in automatic acceleration mode.
Select the guest architecture explicitly when it differs from the host; disk
format detection does not determine CPU architecture.
ARM64 requires a compatible `QEMU_EFI.fd` (AAVMF/EDK2) firmware file. For x86_64,
leave firmware blank for BIOS boot, or select compatible firmware for a UEFI
installation. The current firmware interface uses `-bios`; mutable per-VM UEFI
NVRAM and Secure Boot are not implemented. Install the EFI fallback boot path
(`EFI/BOOT/BOOTAA64.EFI` or `BOOTX64.EFI`) so boot does not depend on saved NVRAM.

## Display and ADB

The client embeds QEMU's VNC display using noVNC. The guest compositor and Android
use software rendering as the compatibility baseline. Hardware GPU acceleration,
audio forwarding and host clipboard/file sharing are **not implemented** in this
first backend; do not assume gaming-level performance or media support.

The guest ADB bridge forwards guest port 5555 to the Android container. QEMU
forwards a random **host loopback-only** port to it. Install host Android SDK
Platform Tools to enable the Install APK action; accept Android's RSA authorization
prompt on first use. Do not disable `ro.adb.secure`, expose the forwarding port,
or use bridged/public guest networking with this configuration.

## Validation Checklist

- QEMU boots the Linux disk using the selected architecture/firmware.
- `systemctl status androidbox-container greetd androidbox-adb-forward` is healthy.
- `journalctl -u greetd -u androidbox-container` has no Binder/compositor errors.
- Android desktop is visible and keyboard/pointer input reaches it.
- APK installation succeeds after ADB authorization.
- Guest shutdown exits QEMU without requiring Force stop.
- Repeat on Windows/WHPX, macOS/HVF and Linux/KVM before declaring support.
