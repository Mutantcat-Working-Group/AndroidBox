# Performance and Games

## What dominates performance

Hardware acceleration decides everything. Match the guest architecture to the
host so `auto` picks KVM (Linux), HVF (Apple Silicon) or WHPX (Windows).
Cross-architecture guests fall back to TCG emulation, which is roughly an order
of magnitude slower. Homebrew's `qemu-system-x86_64` on macOS supports TCG only,
so Intel Macs emulating an x86_64 guest get no accelerator at all.

All knobs below are in Settings, are stored per host, and default to the
previous behavior:

- CPU cores and memory: Android 13 with Waydroid wants at least 4 GiB RAM and
  2 vCPUs; 6-8 GiB and 4-6 cores are comfortable. Defaults scale with the host.
- CPU model: `host` passes the real CPU model through (fastest on KVM/HVF),
  `max` exposes the widest guest feature set, `qemu64` is the portable x86_64
  baseline. TCG and WHPX resolve to `max` automatically because they expose no
  host-passthrough model.
- TCG threads: `multi` spreads guest CPU emulation over host threads and helps
  cross-architecture guests; `single` is the fallback when a multi-threaded TCG
  build misbehaves. Hardware accelerators ignore this setting.
- Disk cache: `writeback` (default) uses the host page cache, `none` switches
  the disk to direct I/O, `unsafe` also drops guest flush requests. `none`
  needs `O_DIRECT` support and can fail on some filesystems; `unsafe` risks the
  guest filesystem when the host crashes.
- Disable log pane while gaming; it polls the QEMU log file on the GUI thread.

## Measured results

Apple Silicon host (macOS ARM64), QEMU 11.1.1, HVF, 4 vCPUs, 4096 MiB RAM:
Android 13 (LineageOS 20, arm64_only) on the Ubuntu 24.04 test guest, built-in
screen 1280x800 at 74 Hz.

- Notification shade animation, continuous swipes over 5 seconds: 331 frames,
  64.9 fps (second run: 321 frames, 63.8 fps). Janky frames 1.3-3.1%, frame
  time p50 5 ms, p90 7-9 ms, p99 69-113 ms.
- Host QEMU process during that animation: 1.5 cores busy, ~4.5 GiB RSS.
- Idle Android container: under 1% guest CPU.
- Android graphics pipeline is Skia/OpenGL inside Waydroid's software renderer;
  no host GPU is involved.

## Games

2D, casual and turn-based games are playable on HVF/KVM/WHPX with 4 GiB and four
cores: the UI itself sustains roughly 60 fps, as measured above. Demanding 3D
games are not: Android renders through Waydroid's software GL, every frame is
re-encoded by VNC, and neither GPU passthrough nor audio forwarding exists yet.

To make demanding games viable the backend needs guest 3D acceleration
(virtio-gpu with virglrenderer, or host GPU passthrough), audio forwarding, and
lower VNC latency. None of that is implemented; the safe advice is to treat
smooth 3D play as out of scope today and to raise RAM/vCPU only on hosts with
spare capacity.
