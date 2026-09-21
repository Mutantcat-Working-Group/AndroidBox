# AndroidBox Guest Image

The desktop client needs a **bootable Linux VM disk**. Waydroid `system.img` and
`vendor.img` are Android filesystem partitions, not bootable QEMU disks.
AndroidBox does not bundle a full Android disk in its installers, but the source
tree includes a verified example-disk preparation script. It downloads the fixed
Ubuntu 24.04 minimal cloud image, verifies the official `SHA256SUMS` entry, and
creates the managed `androidbox-{arch}.qcow2` overlay that the desktop client
auto-detects. The recipe below has not been validated by booting Android on all
hosts.

## One Click From The Desktop Client

On first launch, with no guest disk present, the desktop client shows a
**Prepare example guest disk** button in the center of the window. Clicking it
downloads the same verified image for this computer's architecture and writes the
managed `androidbox-{arch}.qcow2` overlay directly, without a separate `qemu-img`
install, then saves the disk to the client settings and switches to the running
view. The same step writes a NoCloud seed next to the overlay so the first boot
can provision the Android guest automatically. The button disappears once a
guest disk is present. Use the script below when you prefer the terminal or need
a specific architecture or output directory.

### How The Download Is Made Reliable

Three details matter on a user's machine, and none of them are obvious from the
button label.

**The trust store is bundled.** The installer packages whatever OpenSSL its QEMU
payload pulled in, and that library's compiled-in CA directory (`/opt/homebrew/etc/
openssl@3` on a Homebrew-built macOS bundle, the MSYS2 path on Windows) does not
exist on the target machine. `SSL_CTX_set_default_verify_paths()` then finds no CA
at all and every HTTPS request fails with `unable to get local issuer
certificate`, which reads like a network problem but is not. The client therefore
verifies against the `certifi` bundle shipped inside the application, so
verification never depends on the host's OpenSSL configuration. When the desktop
extra is not installed, the host trust store is used instead, which is correct for
a source checkout whose interpreter and OpenSSL come from the same system.

**Mirrors are tried in order.** `cloud-images.ubuntu.com` is slow and has its TLS
intercepted on some networks, so preparation falls back to
`mirrors.ustc.edu.cn` and `mirror.nju.edu.cn`. The digest always comes from the
`SHA256SUMS` manifest, so a mirror can only ever serve the image Ubuntu published;
a tampered mirror image fails verification and is discarded. Both mirrors publish
a byte-identical manifest (verified against the official checksum), so the
verification strength is unchanged.

**A partial download survives.** Transfers are retried with backoff and resume
from the bytes already written using an HTTP `Range` request, so a dropped
connection resumes instead of restarting. Only a checksum mismatch discards the
partial file.

If every mirror fails, the error dialog lists the reason for each one behind a
Details button. The **Use a local image** button next to Prepare accepts an
`ubuntu-24.04-minimal-cloudimg-{amd64,arm64}.img` you downloaded yourself; its
SHA256 is still verified against the official manifest, and it is used to create
the same managed overlay.

## Example Guest Disks

Run from the checkout; the architecture defaults to the host:

```sh
python scripts/fetch_guest_disk.py
```

Pass `--arch x86_64` or `--arch aarch64` to prepare the other architecture,
`--output-dir` to override the state directory, and `--local-image` to reuse an
already downloaded cloud image while still verifying its checksum. `--dry-run`
prints the pinned file and official digest without downloading.

```sh
# x86_64 host (Windows or Linux)
python scripts/fetch_guest_disk.py --arch x86_64

# ARM64 host (Apple Silicon macOS)
python scripts/fetch_guest_disk.py --arch aarch64
```

The script places these files in the guest directory:

- `ubuntu-24.04-minimal-cloudimg-{amd64,arm64}.img` (verified base image)
- `androidbox-{arch}.qcow2` (32 GiB QCOW2 overlay by default)
- `androidbox-{arch}-seed.iso` (NoCloud `cidata` first-boot seed)

The guest directory is `%LOCALAPPDATA%\org.mutantcat.androidbox\guests` on
Windows, `~/Library/Application Support/org.mutantcat.androidbox/guests` on
macOS, and `${XDG_DATA_HOME:-~/.local/share}/org.mutantcat.androidbox/guests` on
Linux. Both example disks are bootable Linux guests and are recognized by the
desktop client without manual disk selection.

The overlay depends on its base image; keep both in the same directory and never
delete the base while the overlay is in use. A downloaded mirror is accepted only
when its official checksum matches.

### First Boot

The seed is attached as a read-only `cidata` virtio disk and is consumed by
cloud-init on the first boot. It creates the `ubuntu` account with the default
password **`androidbox`** (passwordless sudo), enables automatic login on the
virtual console, installs `linux-modules-extra-$(uname -r)` when Binder is not
present, extracts the bundled provisioning payload from the seed, and runs
`guest/provision.sh --dedicated-guest`. The first boot downloads the Android
images, installs the container service, and reboots into the Android session;
plan for several minutes the first time. If you provision the disk yourself,
delete the seed file or change the password so a published image never ships
with the documented default credentials.

## Build a Dedicated Guest

1. Prepare the example disk with `scripts/fetch_guest_disk.py`, or install a
   minimal Debian-family Linux system into a writable QCOW2 disk using QEMU or
   another VM installer. Allocate at least 32 GiB of disk and 4 GiB RAM. The
   guest requires systemd, virtio block/network/GPU drivers and a kernel with
   `CONFIG_ANDROID_BINDER_IPC=y/m` and `CONFIG_ANDROID_BINDERFS=y`. On Ubuntu a
   generic kernel plus its matching extra modules may be needed.
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
NoCloud SSH-key provisioning. `scripts/fetch_guest_disk.py` downloads the matching
architecture from `https://cloud-images.ubuntu.com/minimal/releases/noble/release/`,
verifies its SHA-256 against that directory's `SHA256SUMS`, and creates the managed
QCOW2 overlay. A mirror download must match the official checksum too. Keep the
base image if using a QCOW2 overlay; the overlay alone is not a portable,
standalone disk.

Pinned image sizes (uncompressed, essentially incompressible):

| Architecture | Image | Size |
| --- | --- | --- |
| `amd64` | `ubuntu-24.04-minimal-cloudimg-amd64.img` | 252 MiB |
| `arm64` | `ubuntu-24.04-minimal-cloudimg-arm64.img` | 218 MiB |

Bundling an image in the installers was measured and rejected: each installer
would roughly double in size (about +1.2 GiB across the five installers), the
image does not compress (229 MB gzips to 226 MB), and the mirror fallback plus
the local-image path already cover the offline and restricted-network cases. Use
**Use a local image** when you have the file, or download it once from a mirror
and point the client at it.

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
first backend; see [Performance](performance.md) for what that means for games.

## Performance

See [performance.md](performance.md).

Hardware acceleration dominates everything else. Match the guest architecture to
the host so `auto` can pick KVM (Linux), HVF (Apple Silicon) or WHPX (Windows);
cross-architecture guests fall back to TCG emulation and are an order of
magnitude slower. Homebrew's `qemu-system-x86_64` on macOS supports TCG only, so
Intel Macs running x86_64 guests use the emulator as well.

Settable in Settings and stored per host:

- CPU cores and memory. Android 13 with Waydroid wants at least 4 GiB and 2 vCPUs;
  6-8 GiB and 4-6 cores are comfortable. Defaults scale with the host.
- CPU model: `host` passes the real CPU through (fastest), `max` enables all guest
  features, `qemu64` is the portable x86_64 baseline. TCG and WHPX use `max`
  automatically because they expose no host-passthrough model.
- TCG threads: `multi` spreads emulation over host threads and helps
  cross-architecture guests; `single` is the safest fallback for hosts where the
  multi-threaded TCG build is unstable. Hardware accelerators ignore this setting.
- Disk cache: `writeback` (default) keeps the host page cache, `none` bypasses it
  with direct I/O, `unsafe` additionally ignores guest flush requests. `none` can
  fail on filesystems without `O_DIRECT`; `unsafe` risks the guest filesystem if
  the host crashes.

### Games

2D, casual and turn-based titles are usable on HVF/KVM/WHPX with 4 GiB and four
cores. Demanding 3D games are not: Android renders through Waydroid's software
rasteriser, the framebuffer travels over VNC, and there is no GPU passthrough or
audio forwarding yet. Expect single-digit to low-double-digit frame rates at
best, and treat smooth play as out of scope until guest 3D acceleration exists.

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
- Settings reports a hardware accelerator (KVM/HVF/WHPX), not TCG, when the guest
  architecture matches the host.
- Repeat on Windows/WHPX, macOS/HVF and Linux/KVM before declaring support.
