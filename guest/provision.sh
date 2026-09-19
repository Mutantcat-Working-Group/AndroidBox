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
apt-get install -y make lxc python3 python3-dbus python3-gi python3-gbinder \
    gir1.2-gtk-3.0 polkitd dbus-user-session pulseaudio iptables dnsmasq-base \
    cage greetd socat curl ca-certificates apparmor apparmor-utils

if ! modprobe binder_linux devices=binder,hwbinder,vndbinder; then
    echo "Install a guest kernel with CONFIG_ANDROID_BINDER_IPC and CONFIG_ANDROID_BINDERFS, then reboot." >&2
    exit 1
fi
install -m 0644 "$source_dir/guest/binder.conf" /etc/modules-load.d/androidbox.conf
make -C "$source_dir" install install_apparmor
id androidbox >/dev/null 2>&1 || useradd --create-home --shell /bin/bash androidbox
usermod -a -G video,render androidbox
install -m 0755 "$source_dir/guest/session.sh" /usr/local/bin/androidbox-guest-session
install -m 0755 "$source_dir/guest/adb-forward.sh" /usr/local/bin/androidbox-adb-forward
install -m 0644 "$source_dir/guest/adb-forward.service" /etc/systemd/system/androidbox-adb-forward.service
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
with path.open('w') as stream:
    config.write(stream)
PY
androidbox upgrade -o
systemctl daemon-reload
systemctl enable androidbox-container.service androidbox-adb-forward.service greetd.service
echo "Guest provisioned. Reboot this VM; first Android boot may take several minutes."
