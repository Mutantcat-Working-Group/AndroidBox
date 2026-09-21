"""Build the NoCloud seed that makes the example guest usable on first boot.

The Ubuntu cloud image boots to a bare login prompt: no datasource is attached,
so the default user keeps a locked password and no Android container is ever
installed. The seed closes both gaps with one ISO9660 image labelled ``cidata``
that cloud-init finds on a virtio-blk device. It sets a known password, logs the
virtual console in automatically, and runs the in-guest provisioning once, which
installs the Android container and reboots into the Android session.

The image is written directly as ISO9660 instead of shelling out to a
platform-specific tool, so the frozen client produces the same seed on Windows,
macOS and Linux.
"""

from pathlib import Path
import gzip
import io
import struct
import sys
import tarfile
import tempfile

from . import __version__

SEED_SUFFIX = "-seed.iso"
SEED_LABEL = "cidata"
PAYLOAD_ARCHIVE = "androidbox-guest.tar.gz"
VERSION_FILE = "androidbox-seed-version"
PAYLOAD_DIRECTORY = "androidbox"
# Everything guest/provision.sh and its Makefile install need inside the guest.
PAYLOAD_ENTRIES = ("Makefile", "androidbox.py", "androidbox", "data", "tools",
                   "guest", "dbus", "systemd")
DEFAULT_PASSWORD = "androidbox"

SECTOR = 2048
SYSTEM_AREA_SECTORS = 16
_VOLUME_DATE = b"2026010100000000\x00"
_RECORD_DATE = bytes((126, 1, 1, 0, 0, 0, 0))  # 2026-01-01T00:00:00.00


def seed_path_for(disk):
    """Return the seed path that belongs to a guest disk."""
    disk = Path(disk)
    return disk.with_name(disk.stem + SEED_SUFFIX)


def payload_root():
    """Locate the in-guest payload: the frozen bundle or the source checkout."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def meta_data(arch, version=None):
    """Return the NoCloud meta-data for a guest disk.

    The instance-id carries the seed version on purpose: cloud-init only
    re-runs per-instance modules (``write_files``, ``runcmd``, ...) when the
    instance-id changes. A version-less id keeps the old, possibly broken
    first-boot result frozen on disks that have booted before, so every seed
    refresh restarts the cloud-init sequence.
    """
    version = version or __version__
    return f"instance-id: androidbox-{arch}-{version}\nlocal-hostname: androidbox\n"


def _indent(text, spaces):
    padding = " " * spaces
    # Block scalars need every line padded; blank lines stay blank so YAML does
    # not treat the padding as significant whitespace inside the literal block.
    return "\n".join(padding + line if line.strip() else ""
                     for line in text.splitlines())


def user_data(version=None):
    """Return the cloud-config that logs in and provisions the first boot."""
    version = version or __version__
    return f"""#cloud-config
hostname: androidbox
manage_etc_hosts: true
ssh_pwauth: true
disable_root: true

users:
  - name: ubuntu
    gecos: AndroidBox
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: false
    groups: [adm, sudo, dip, plugdev, video, render]

chpasswd:
  expire: false
  users:
    - name: ubuntu
      password: {DEFAULT_PASSWORD}
      type: text

write_files:
  - path: /etc/systemd/system/getty@tty1.service.d/10-autologin.conf
    permissions: "0644"
    owner: root:root
    content: |
      [Service]
      ExecStart=
      ExecStart=-/sbin/agetty --autologin ubuntu --noclear %I $TERM

  - path: /etc/profile.d/androidbox-firstboot.sh
    permissions: "0644"
    owner: root:root
    content: |
      # Report first-boot progress on the console login shell.
      if [ -e /var/lib/androidbox/.provisioning ] && [ -r /var/log/androidbox-firstboot.log ]; then
          echo ""
          echo "=========================================="
          echo " AndroidBox is installing the Android guest"
          echo " on first boot. This downloads system images"
          echo " and can take several minutes."
          echo ""
          echo " Progress: tail -f /var/log/androidbox-firstboot.log"
          echo "=========================================="
          echo ""
      fi

  - path: /usr/local/bin/androidbox-firstboot
    permissions: "0755"
    owner: root:root
    content: |
{_indent(firstboot_script(), 6)}

  - path: /etc/systemd/system/androidbox-firstboot.service
    permissions: "0644"
    owner: root:root
    content: |
      [Unit]
      Description=AndroidBox first-boot guest provisioning
      After=network-online.target
      Wants=network-online.target
      ConditionPathExists=!/var/lib/androidbox/.provisioned
      StartLimitIntervalSec=0

      [Service]
      Type=oneshot
      ExecStart=/usr/local/bin/androidbox-firstboot
      RemainAfterExit=yes

      [Install]
      WantedBy=multi-user.target
runcmd:
  - [ systemctl, daemon-reload ]
  - [ systemctl, restart, getty@tty1.service ]
  - [ systemctl, enable, --now, androidbox-firstboot.service ]
"""


def firstboot_script():
    """Return the one-shot in-guest provisioning script."""
    return f"""#!/bin/bash
# Install the AndroidBox Android guest on first boot; runs once, then reboots.
set -u
exec >>/var/log/androidbox-firstboot.log 2>&1
tty=/dev/console
echo_progress() {{
    echo "[androidbox-firstboot] $*"
    echo "$*" > "$tty" 2>/dev/null || true
    echo "$*" > /dev/tty1 2>/dev/null || true
}}
fail() {{
    echo "[androidbox-firstboot] FAILED: $*"
    echo "FAILED: $* See /var/log/androidbox-firstboot.log" > "$tty" 2>/dev/null || true
    echo "FAILED: $* See /var/log/androidbox-firstboot.log" > /dev/tty1 2>/dev/null || true
    rm -f "$state/.provisioning"
    exit 1
}}

state=/var/lib/androidbox
if [[ -e $state/.provisioned ]]; then
    exit 0
fi
mkdir -p "$state"
touch "$state/.provisioning"
export DEBIAN_FRONTEND=noninteractive

log() {{ echo "[androidbox-firstboot] $*"; }}
echo_progress "AndroidBox first boot: starting provisioning..."

# The console password must work even if a cloud-init release ignores the
# chpasswd schema used above.
echo 'ubuntu:{DEFAULT_PASSWORD}' | chpasswd

# cloud-init can reach the final stage before DNS is usable.
echo_progress "Waiting for network..."
for _ in $(seq 1 60); do
    getent hosts archive.ubuntu.com >/dev/null 2>&1 && break
    sleep 2
done

# Binder is a module of the generic kernel; the minimal cloud image ships the
# kernel without its extra modules.
echo_progress "Setting up binder kernel module..."
if ! modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null; then
    echo_progress "Installing binder modules (this may take a minute)..."
    apt-get update
    apt-get install -y "linux-modules-extra-$(uname -r)" || true
    if ! modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null; then
        if [[ -e $state/.kernel-reboot ]]; then
            fail "binder module still missing after kernel reboot"
        fi
        log "installing the generic kernel for binder support"
        apt-get install -y linux-image-generic || true
        touch "$state/.kernel-reboot"
        systemctl reboot
        exit 0
    fi
fi

# The seed is a read-only ISO; copy the AndroidBox payload out of it.
echo_progress "Extracting AndroidBox payload..."
seed=/dev/disk/by-label/{SEED_LABEL}
if [[ ! -b $seed ]]; then
    fail "no {SEED_LABEL} seed device attached"
fi
mkdir -p /mnt/androidbox-seed
mountpoint -q /mnt/androidbox-seed || mount -o ro "$seed" /mnt/androidbox-seed
# A plain ISO9660 mount may upper-case names depending on mount options, so
# resolve the payload case-insensitively instead of hard-coding it.
payload=$(find /mnt/androidbox-seed -maxdepth 1 -iname '{PAYLOAD_ARCHIVE}' | head -n 1)
[[ -n $payload ]] || fail "payload {PAYLOAD_ARCHIVE} missing from the seed"
rm -rf /opt/androidbox-src
mkdir -p /opt/androidbox-src
tar -xzf "$payload" -C /opt/androidbox-src || fail "failed to extract payload"

echo_progress "Downloading and installing Android (this takes several minutes)..."
bash /opt/androidbox-src/{PAYLOAD_DIRECTORY}/guest/provision.sh --dedicated-guest || fail "provision.sh failed"

# greetd takes over the virtual console from the automatic login shell.
echo_progress "Android installed; rebooting into Android session..."
systemctl disable --now getty@tty1.service || true
touch "$state/.provisioned"
rm -f "$state/.provisioning"
log "the guest is provisioned; rebooting into the Android session"
systemctl reboot
"""


def _skip_caches(info):
    if "__pycache__" in info.name or info.name.endswith((".pyc", ".pyo")):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    return info


def _add_payload(archive, source, arcname):
    archive.add(source, arcname=arcname, recursive=False, filter=_skip_caches)
    if source.is_dir():
        for child in sorted(source.iterdir()):
            _add_payload(archive, child, f"{arcname}/{child.name}")


def write_payload_archive(target, root=None):
    """Pack the files the in-guest provisioner needs into a deterministic tar.gz."""
    root = Path(root) if root else payload_root()
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for entry in PAYLOAD_ENTRIES:
            source = root / entry
            if not source.exists():
                raise ValueError(f"The guest payload is missing {entry} in {root}")
            _add_payload(archive, source, f"{PAYLOAD_DIRECTORY}/{entry}")
    with target.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as compressed:
            compressed.write(raw.getvalue())
    return target


def write_seed(path, arch, version=None, root=None):
    """Write the NoCloud seed for a guest disk and return its path."""
    path = Path(path)
    version = version or __version__
    with tempfile.TemporaryDirectory(prefix="androidbox-seed-") as directory:
        archive = write_payload_archive(Path(directory) / PAYLOAD_ARCHIVE, root)
        payload = archive.read_bytes()
    write_iso(path, [
        ("meta-data", meta_data(arch, version).encode("utf-8")),
        ("user-data", user_data(version).encode("utf-8")),
        (PAYLOAD_ARCHIVE, payload),
        (VERSION_FILE, f"{version}\n".encode("utf-8")),
    ])
    return path


def ensure_seed(path, arch, root=None):
    """Write the seed unless a seed for this application version exists."""
    path = Path(path)
    if path.is_file() and seed_version(path) == __version__:
        return path
    return write_seed(path, arch, root=root)


def _record_length(identifier):
    size = 33 + len(identifier)
    return size + (size % 2)


def _directory_record(identifier, extent_lba, length, directory=False):
    if isinstance(identifier, str):
        identifier = identifier.encode("ascii")
    record = bytearray(_record_length(identifier))
    record[0] = len(record)
    record[1] = 0  # extended attribute record length
    struct.pack_into("<I", record, 2, extent_lba)                # location of extent, little endian
    struct.pack_into(">I", record, 6, extent_lba)                # location of extent, big endian
    struct.pack_into("<I", record, 10, length)                   # data length, little endian
    struct.pack_into(">I", record, 14, length)                   # data length, big endian
    record[18:25] = _RECORD_DATE                                 # recording date and time
    record[25] = 0x02 if directory else 0x00                     # file flags
    record[26] = 0                                               # file unit size
    record[27] = 0                                               # interleave gap size
    struct.pack_into("<H", record, 28, 1)                        # volume sequence number, little endian
    struct.pack_into(">H", record, 30, 1)                        # volume sequence number, big endian
    record[32] = len(identifier)                                 # length of file identifier
    record[33:33 + len(identifier)] = identifier
    return bytes(record)


def _path_table(root_lba, big_endian=False):
    record = bytearray(10)
    record[0] = 1  # the root identifier is a single zero byte
    record[1] = 0
    struct.pack_into(">I" if big_endian else "<I", record, 2, root_lba)
    struct.pack_into(">H" if big_endian else "<H", record, 6, 1)  # the root is its own parent
    record[8] = 0                         # the root identifier is a single zero byte
    return bytes(record)


def _primary_volume_descriptor(label, total_sectors, root_record, path_table_size,
                               path_table_lba, path_table_m_lba):
    descriptor = bytearray(SECTOR)
    descriptor[0] = 1
    descriptor[1:6] = b"CD001"
    descriptor[6] = 1
    descriptor[8:40] = b"ANDROIDBOX".ljust(32)            # system identifier
    descriptor[40:72] = label.encode("ascii").ljust(32)   # volume identifier: the seed label
    struct.pack_into("<I", descriptor, 80, total_sectors)         # volume space size, little endian
    struct.pack_into(">I", descriptor, 84, total_sectors)         # volume space size, big endian
    struct.pack_into("<H", descriptor, 120, 1)                    # volume set size, little endian
    struct.pack_into(">H", descriptor, 122, 1)                    # volume set size, big endian
    struct.pack_into("<H", descriptor, 124, 1)                    # volume sequence number, little endian
    struct.pack_into(">H", descriptor, 126, 1)                    # volume sequence number, big endian
    struct.pack_into("<H", descriptor, 128, SECTOR)               # logical block size, little endian
    struct.pack_into(">H", descriptor, 130, SECTOR)               # logical block size, big endian
    struct.pack_into("<I", descriptor, 132, path_table_size)      # path table size, little endian
    struct.pack_into(">I", descriptor, 136, path_table_size)      # path table size, big endian
    struct.pack_into("<I", descriptor, 140, path_table_lba)   # type L path table
    struct.pack_into("<I", descriptor, 144, 0)                # optional type L path table
    struct.pack_into(">I", descriptor, 148, path_table_m_lba)  # type M path table
    struct.pack_into(">I", descriptor, 152, 0)                # optional type M path table
    descriptor[156:190] = root_record                      # root directory record
    descriptor[190:318] = b"ANDROIDBOX".ljust(128)        # volume set identifier
    descriptor[318:446] = b"MUTANTCAT".ljust(128)         # publisher identifier
    descriptor[446:574] = b"MUTANTCAT".ljust(128)         # data preparer identifier
    descriptor[574:702] = b"ANDROIDBOX".ljust(128)        # application identifier
    descriptor[702:739] = b" ".ljust(37)                  # copyright file identifier
    descriptor[739:776] = b" ".ljust(37)                  # abstract file identifier
    descriptor[776:813] = b" ".ljust(37)                  # bibliographic file identifier
    descriptor[813:830] = _VOLUME_DATE                    # creation date and time
    descriptor[830:847] = _VOLUME_DATE                    # modification date and time
    descriptor[847:864] = b"0" * 17                       # expiration date and time
    descriptor[864:881] = b"0" * 17                       # effective date and time
    descriptor[881] = 1                                   # file structure version
    return bytes(descriptor)


def _volume_descriptor_terminator():
    descriptor = bytearray(SECTOR)
    descriptor[0] = 255
    descriptor[1:6] = b"CD001"
    descriptor[6] = 1
    return bytes(descriptor)


def write_iso(path, entries, label=SEED_LABEL):
    """Write a minimal ISO9660 image holding entries in its root directory."""
    if not entries:
        raise ValueError("An ISO9660 image needs at least one file")
    files = [(name.upper(), bytes(data)) for name, data in entries]
    for name, _ in files:
        if not name or "/" in name or len(name) > 200:
            raise ValueError(f"Unsupported seed file name: {name}")
    path_table_lba = SYSTEM_AREA_SECTORS + 2
    path_table_m_lba = path_table_lba + 1
    root_lba = path_table_m_lba + 1
    root_size = 2 * _record_length(b"\x00") + sum(
        _record_length(f"{name};1") for name, _ in files)
    root_size = -(-root_size // SECTOR) * SECTOR
    root = bytearray()
    root += _directory_record(b"\x00", root_lba, root_size, directory=True)
    root += _directory_record(b"\x01", root_lba, root_size, directory=True)
    extent_lba = root_lba + root_size // SECTOR
    for name, data in files:
        root += _directory_record(f"{name};1", extent_lba, len(data))
        extent_lba += max(1, -(-len(data) // SECTOR))
    path_table = _path_table(root_lba)
    pvd = _primary_volume_descriptor(label, extent_lba, _directory_record(
        b"\x00", root_lba, root_size, directory=True), len(path_table),
        path_table_lba, path_table_m_lba)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(b"\0" * (SYSTEM_AREA_SECTORS * SECTOR))
        stream.write(pvd)
        stream.write(_volume_descriptor_terminator())
        stream.write(path_table.ljust(SECTOR, b"\0"))
        stream.write(_path_table(root_lba, big_endian=True).ljust(SECTOR, b"\0"))
        stream.write(root.ljust(root_size, b"\0"))
        for _, data in files:
            stream.write(data)
            if len(data) % SECTOR:
                stream.write(b"\0" * (SECTOR - len(data) % SECTOR))
    return path


def read_iso(path):
    """Return the volume label and the root files of an image written by write_iso."""
    data = Path(path).read_bytes()
    offset = SYSTEM_AREA_SECTORS * SECTOR
    if len(data) < offset + SECTOR or data[offset + 1:offset + 6] != b"CD001" or data[offset] != 1:
        raise ValueError(f"{path} is not an ISO9660 image")
    pvd = data[offset:offset + SECTOR]
    label = pvd[40:72].decode("ascii").rstrip()
    extent_lba = struct.unpack_from("<I", pvd, 158)[0]
    extent_size = struct.unpack_from("<I", pvd, 166)[0]
    extent = data[extent_lba * SECTOR:extent_lba * SECTOR + extent_size]
    files, position = {}, 0
    while position < len(extent):
        sector_end = (position // SECTOR + 1) * SECTOR
        length = extent[position]
        if length == 0 or position + length > sector_end:
            position = sector_end
            continue
        name_length = extent[position + 32]
        identifier = extent[position + 33:position + 33 + name_length]
        if identifier not in (b"\x00", b"\x01"):
            file_lba = struct.unpack_from("<I", extent, position + 2)[0]
            file_size = struct.unpack_from("<I", extent, position + 10)[0]
            name = identifier.decode("ascii")
            files[name[:-2] if name.endswith(";1") else name] = \
                data[file_lba * SECTOR:file_lba * SECTOR + file_size]
        position += length
    return label, files


def seed_version(path):
    """Return the application version a seed was built for, or None."""
    try:
        _, files = read_iso(path)
    except (OSError, ValueError):
        return None
    raw = files.get(VERSION_FILE.upper())
    return raw.decode("utf-8", errors="replace").strip() if raw else None
