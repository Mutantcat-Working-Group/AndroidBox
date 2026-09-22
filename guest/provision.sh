#!/bin/bash
# Run only inside a disposable/dedicated Debian-family QEMU Linux guest.
set -euo pipefail

if [[ ${1:-} != --dedicated-guest ]]; then
    echo "Usage: sudo bash guest/provision.sh --dedicated-guest" >&2
    echo "This installs an automatic-login graphical session inside a dedicated VM." >&2
    exit 2
fi
if [[ $EUID != 0 ]] || ! systemd-detect-virt --vm --quiet; then
    echo "Run as root inside a dedicated Linux virtual machine." >&2
    exit 1
fi
source_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)

apt-get update
apt-get install -y make lxc python3 python3-dbus python3-gi python3-setuptools \
    gir1.2-gtk-3.0 polkitd dbus-user-session pulseaudio iptables dnsmasq-base \
    cage greetd socat curl ca-certificates apparmor apparmor-utils ffmpeg
# The emulated sound card and the loopback camera ship their drivers in the
# kernel packages. Best-effort on purpose: a guest whose cloud image carries a
# trimmed kernel keeps booting, it just comes up without sound or camera.
apt-get install -y "linux-modules-$(uname -r)" \
    "linux-modules-extra-$(uname -r)" v4l2loopback-dkms "linux-headers-$(uname -r)" \
    2>/dev/null || \
    echo "WARNING: kernel modules or v4l2loopback could not be installed" >&2

# Ubuntu noble has no gbinder packages, so build the binder stack from the
# vendored sources. Best-effort on purpose: if the build fails the guest still
# boots, but binder integration (clipboard, notifications, hardware, immersive
# mode) degrades and the androidbox CLI cannot import its bindings.
build_gbinder_stack() {
    apt-get install -y build-essential pkg-config libglib2.0-dev python3-dev cython3
    local multiarch py_version dist_packages
    multiarch=$(dpkg-architecture -qDEB_HOST_MULTIARCH)
    make -C "$source_dir/guest/vendor/libglibutil" release
    make -C "$source_dir/guest/vendor/libglibutil" pkgconfig
    make -C "$source_dir/guest/vendor/libglibutil" install-dev "LIBDIR=usr/lib/$multiarch"
    make -C "$source_dir/guest/vendor/libgbinder" release
    make -C "$source_dir/guest/vendor/libgbinder" pkgconfig
    make -C "$source_dir/guest/vendor/libgbinder" install-dev "LIBDIR=usr/lib/$multiarch"
    ldconfig
    (cd "$source_dir/guest/vendor/python-gbinder" && \
        python3 setup.py build_ext --inplace)
    py_version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    dist_packages=$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["platlib"])')
    install -d "$dist_packages" "/usr/local/lib/python${py_version}/dist-packages"
    install -m 0644 "$source_dir"/guest/vendor/python-gbinder/gbinder*.so "$dist_packages"
    install -m 0644 "$source_dir"/guest/vendor/python-gbinder/gbinder*.so \
        "/usr/local/lib/python${py_version}/dist-packages"
    python3 -c 'import gbinder'
}
if ! build_gbinder_stack; then
    echo "WARNING: gbinder bindings unavailable; Android integration degraded." >&2
fi

if ! modprobe binder_linux devices=binder,hwbinder,vndbinder; then
    echo "Install a guest kernel with CONFIG_ANDROID_BINDER_IPC and CONFIG_ANDROID_BINDERFS, then reboot." >&2
    exit 1
fi
install -m 0644 "$source_dir/guest/binder.conf" /etc/modules-load.d/androidbox.conf
# The emulated HDA controller is normally autoloaded from PCI, but a trimmed
# cloud kernel can miss it, and without a driver PulseAudio has no sound card
# to play the Android audio the host forwards through QEMU.
echo "snd-hda-intel" >> /etc/modules-load.d/androidbox.conf
# binderfs only creates the node names handed to the module, and the Android
# container expects /dev/binder exactly. Without the persistent options every
# reboot reloads binder_linux with its default names (anbox-binder and friends),
# and the container starts against a /dev/binder that no longer exists.
cat > /etc/modprobe.d/androidbox.conf <<'EOF'
options binder_linux devices=binder,hwbinder,vndbinder
EOF

# Android needs a video capture device. A v4l2loopback node is preferred
# because the host webcam can be streamed into it by the desktop client; the
# vivid fallback only shows a test pattern, but it still hands every camera app
# a device that opens and streams instead of failing outright.
camera_device=""
if modprobe v4l2loopback video_nr=0 card_label="AndroidBox Camera" exclusive_caps=1 max_buffers=2; then
    cat > /etc/modprobe.d/androidbox-video.conf <<'EOF'
options v4l2loopback video_nr=0 card_label="AndroidBox Camera" exclusive_caps=1 max_buffers=2
EOF
    printf 'v4l2loopback\n' > /etc/modules-load.d/androidbox-video.conf
    camera_device=/dev/video0
elif modprobe vivid; then
    printf 'vivid\n' > /etc/modules-load.d/androidbox-video.conf
    echo "WARNING: v4l2loopback unavailable; the camera shows a test pattern only." >&2
else
    echo "WARNING: no video capture driver could be loaded." >&2
fi

# Release builds carry the Android archives on a read-only block device, so a
# fresh install never depends on the guest network reaching the OTA channels.
# Anything that cannot be unpacked here falls back to the channel downloads
# performed by `androidbox init` below.
preinstalled_images=/usr/share/androidbox-extra/images
install_preinstalled_images() {
    local label="androidbox-img"
    local mount_point="/run/androidbox-images"
    local device attempt
    if [[ -f $preinstalled_images/system.img && -f $preinstalled_images/vendor.img ]]; then
        return 0
    fi
    apt-get install -y unzip
    mkdir -p "$mount_point"
    device=""
    for attempt in $(seq 1 30); do
        device=$(blkid -L "$label" 2>/dev/null || true)
        [[ -n $device ]] && break
        sleep 1
    done
    if [[ -z $device ]]; then
        echo "No bundled Android image disk found; the OTA channels will be used." >&2
        return 0
    fi
    if ! mount -o ro "$device" "$mount_point"; then
        echo "WARNING: could not mount the bundled Android image disk ${device}" >&2
        return 0
    fi
    if [[ -f $mount_point/system.zip && -f $mount_point/vendor.zip && -f $mount_point/SHA256SUMS ]] && \
        (cd "$mount_point" && sha256sum --status -c SHA256SUMS); then
        install -d "$preinstalled_images"
        unzip -o -q "$mount_point/system.zip" -d "$preinstalled_images"
        unzip -o -q "$mount_point/vendor.zip" -d "$preinstalled_images"
    else
        echo "WARNING: bundled Android archives failed verification; the OTA channels will be used." >&2
    fi
    umount "$mount_point"
    # Disks provisioned before the images were bundled kept them under the
    # default work path; move them beside the preinstalled images so a
    # version-triggered re-provision needs no channel access at all.
    if [[ ! -f $preinstalled_images/system.img ]] && \
        [[ -f /var/lib/androidbox/images/system.img && -f /var/lib/androidbox/images/vendor.img ]]; then
        install -d "$preinstalled_images"
        install -m 0644 /var/lib/androidbox/images/system.img "$preinstalled_images/system.img"
        install -m 0644 /var/lib/androidbox/images/vendor.img "$preinstalled_images/vendor.img"
        rm -f /var/lib/androidbox/images/system.img /var/lib/androidbox/images/vendor.img
    fi
    [[ -f $preinstalled_images/system.img && -f $preinstalled_images/vendor.img ]]
}
install_preinstalled_images || \
    echo "WARNING: no bundled Android image could be installed; falling back to the OTA channels." >&2

make -C "$source_dir" install install_apparmor
id androidbox >/dev/null 2>&1 || useradd --create-home --shell /bin/bash androidbox
usermod -a -G video,render,audio androidbox
install -m 0755 "$source_dir/guest/session.sh" /usr/local/bin/androidbox-guest-session
install -m 0755 "$source_dir/guest/adb-forward.sh" /usr/local/bin/androidbox-adb-forward
install -m 0644 "$source_dir/guest/adb-forward.service" /etc/systemd/system/androidbox-adb-forward.service
install -d /usr/local/lib/androidbox
install -m 0644 "$source_dir/guest/camera-bridge.py" /usr/local/lib/androidbox/camera-bridge.py
install -m 0644 "$source_dir/guest/camera-bridge.service" /etc/systemd/system/androidbox-camera-bridge.service
install -m 0644 "$source_dir/guest/greetd.toml" /etc/greetd/config.toml

androidbox init
python3 - <<'PY'
import configparser
from pathlib import Path

path = Path('/var/lib/androidbox/androidbox.cfg')
config = configparser.ConfigParser()
config.read(path)
if not config.has_section('properties'):
    config.add_section('properties')
# Software rendering is the portable baseline for the VNC guest display.
config['properties']['ro.hardware.gralloc'] = 'default'
config['properties']['ro.hardware.egl'] = 'swiftshader'
config['properties']['persist.waydroid.multi_windows'] = 'false'
config['properties']['ro.hardware.camera'] = 'v4l2'
with path.open('w') as stream:
    config.write(stream)
PY
androidbox upgrade -o
systemctl daemon-reload
systemctl enable androidbox-container.service androidbox-adb-forward.service greetd.service
if [[ -n $camera_device ]]; then
    systemctl enable androidbox-camera-bridge.service
fi
echo "Guest provisioned. Reboot this VM; first Android boot may take several minutes."
