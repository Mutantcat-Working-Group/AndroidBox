"""Prepare a verified example guest disk without external tools.

The frozen desktop application bundles only qemu-system-*, so the managed
overlay is written directly as QCOW2: every read falls through to the backing
file, keeping the verified base image authoritative while the overlay stays
writable. Shared by the desktop client and scripts/fetch_guest_disk.py.
"""

import hashlib
from pathlib import Path
import shutil
import struct
import urllib.error
import urllib.request

from .runtime import normalize_arch, state_directory

RELEASE = "noble"
BASE_URL = f"https://cloud-images.ubuntu.com/minimal/releases/{RELEASE}/release/"
IMAGE_PREFIX = "ubuntu-24.04-minimal-cloudimg"
DEFAULT_DISK_SIZE = "32G"
DEBIAN_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}

QCOW2_MAGIC = b"QFI\xfb"
QCOW2_VERSION = 3
BACKING_FORMAT_EXTENSION = 0xE2792ACA
HEADER_LENGTH = 104
CLUSTER_BITS = 16
REFCOUNT_ORDER = 4  # 16-bit reference counts
_SIZE_SUFFIXES = {
    "K": 1024, "KIB": 1024, "KB": 1024,
    "M": 1024 ** 2, "MIB": 1024 ** 2, "MB": 1024 ** 2,
    "G": 1024 ** 3, "GIB": 1024 ** 3, "GB": 1024 ** 3,
    "T": 1024 ** 4, "TIB": 1024 ** 4, "TB": 1024 ** 4,
}


def image_remote_name(arch):
    return f"{IMAGE_PREFIX}-{DEBIAN_ARCH[normalize_arch(arch)]}.img"


def managed_disk_name(arch):
    return f"androidbox-{normalize_arch(arch)}.qcow2"


def managed_disk_path(arch, directory=None):
    return (Path(directory) if directory else state_directory() / "guests") / managed_disk_name(arch)


def parse_size(value):
    text = str(value).strip().upper()
    factor = 1
    for suffix in sorted(_SIZE_SUFFIXES, key=len, reverse=True):
        if text.endswith(suffix):
            factor, text = _SIZE_SUFFIXES[suffix], text[: -len(suffix)].strip()
            break
    try:
        size = int(float(text or "0") * factor)
    except ValueError:
        raise ValueError(f"Invalid disk size: {value}") from None
    if size < 512:
        raise ValueError(f"Disk size is below the 512 byte minimum: {value}")
    return (size + 511) // 512 * 512


def parse_sha256sums(text):
    checksums = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid SHA256SUMS line: {raw_line}")
        digest, name = parts
        if name.startswith("*"):
            name = name[1:]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError(f"Invalid SHA256 digest in line: {raw_line}")
        checksums[name] = digest.lower()
    if not checksums:
        raise ValueError("SHA256SUMS manifest is empty")
    return checksums


def _open(url, timeout):
    try:
        return urllib.request.urlopen(url, timeout=timeout)
    except (urllib.error.URLError, OSError) as error:
        raise ValueError(f"Cannot reach {url}: {error}") from error


def remote_checksums():
    url = f"{BASE_URL}SHA256SUMS"
    with _open(url, 60) as response:
        text = response.read().decode("utf-8", errors="replace")
    return parse_sha256sums(text), url


def sha256_checksum(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def download_verified(url, target, expected, progress=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.download")
    try:
        with _open(url, 120) as response, temporary.open("wb") as stream:
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            checksum, downloaded = hashlib.sha256(), 0
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                checksum.update(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
        if checksum.hexdigest().lower() != expected.lower():
            raise ValueError(f"SHA256 mismatch for {target.name}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def ensure_base_image(target, expected, local=None, progress=None):
    if local is not None:
        source = Path(local)
        if not source.is_file():
            raise ValueError(f"Local image does not exist: {source}")
        if sha256_checksum(source).lower() != expected.lower():
            raise ValueError(f"Local image checksum mismatch for {source.name}")
        if source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return target
    if target.is_file():
        if sha256_checksum(target).lower() == expected.lower():
            return target
        raise ValueError(f"Existing example image failed SHA256 verification: {target}")
    return download_verified(f"{BASE_URL}{target.name}", target, expected, progress)


def write_overlay(path, backing_name, virtual_size):
    """Write an empty QCOW2 overlay whose reads fall through to backing_name."""
    cluster_size = 1 << CLUSTER_BITS
    l2_entries = cluster_size // 8
    l1_size = max(1, -(-virtual_size // (cluster_size * l2_entries)))
    refcount_table_offset = cluster_size
    refcount_block_offset = 2 * cluster_size
    l1_table_offset = 3 * cluster_size
    backing = backing_name.encode("utf-8")
    # Header, backing-format extension, then the backing name on the 8-byte
    # grid QCOW2 header extensions use.
    backing_offset = HEADER_LENGTH + 16
    backing_offset += -backing_offset % 8
    if backing_offset + len(backing) > cluster_size:
        raise ValueError("Backing file name is too long")
    header = bytearray(HEADER_LENGTH)
    struct.pack_into(">4sIQIIQIIQQIIQQQQII", header, 0,
                     QCOW2_MAGIC, QCOW2_VERSION, backing_offset, len(backing),
                     CLUSTER_BITS, virtual_size, 0, l1_size, l1_table_offset,
                     refcount_table_offset, 1, 0, 0, 0, 0, 0,
                     REFCOUNT_ORDER, HEADER_LENGTH)
    extension = struct.pack(">II", BACKING_FORMAT_EXTENSION, 3) + b"raw".ljust(8, b"\0")
    refcount_block = bytearray(cluster_size)
    struct.pack_into(">4H", refcount_block, 0, 1, 1, 1, 1)
    refcount_table = bytearray(cluster_size)
    struct.pack_into(">Q", refcount_table, 0, refcount_block_offset)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(header + extension)
        stream.write(backing.ljust(cluster_size - HEADER_LENGTH - len(extension), b"\0"))
        stream.write(refcount_table)
        stream.write(refcount_block)
        stream.write(bytearray(l1_size * 8))
    return path


def create_overlay(overlay, backing, size=DEFAULT_DISK_SIZE):
    overlay, backing = Path(overlay), Path(backing)
    if overlay.is_file():
        return overlay
    if not backing.is_file():
        raise ValueError(f"Backing image does not exist: {backing}")
    write_overlay(overlay, backing.name, parse_size(size))
    return overlay


def prepare(arch, directory=None, size=DEFAULT_DISK_SIZE, local_image=None, dry_run=False, progress=None):
    """Return the managed overlay for arch, downloading only what is missing."""
    arch = normalize_arch(arch)
    directory = Path(directory) if directory else state_directory() / "guests"
    overlay = directory / managed_disk_name(arch)
    if overlay.is_file():
        return overlay
    remote_name = image_remote_name(arch)
    checksums, checksum_url = remote_checksums()
    try:
        expected = checksums[remote_name]
    except KeyError:
        raise ValueError(f"{checksum_url} has no entry for {remote_name}") from None
    if dry_run:
        return overlay
    base = directory / remote_name
    ensure_base_image(base, expected, local_image, progress)
    return create_overlay(overlay, base, size)
