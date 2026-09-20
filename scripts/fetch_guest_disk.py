#!/usr/bin/env python3
"""Download a pinned Ubuntu cloud image and create a managed AndroidBox guest disk.

AndroidBox looks for state_directory()/guests/androidbox-{arch}.qcow2 at first
launch. Full prebuilt Android disks are too large to commit to the repository,
so this script downloads the fixed Ubuntu 24.04 minimal cloud image, verifies
its official SHA256 checksum, and creates a 32 GiB QCOW2 overlay with that name.
"""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request


RELEASE = "noble"
BASE_URL = f"https://cloud-images.ubuntu.com/minimal/releases/{RELEASE}/release/"
IMAGE_PREFIX = "ubuntu-24.04-minimal-cloudimg"
DEFAULT_DISK_SIZE = "32G"
ARCH_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}
DEBIAN_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}


def normalize_arch(value):
    try:
        return ARCH_ALIASES[value.lower()]
    except KeyError:
        raise ValueError(f"Unsupported architecture: {value}") from None


def state_directory():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "org.mutantcat.androidbox"


def image_remote_name(arch):
    return f"{IMAGE_PREFIX}-{DEBIAN_ARCH[arch]}.img"


def managed_disk_name(arch):
    return f"androidbox-{arch}.qcow2"


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


def remote_checksums():
    url = f"{BASE_URL}SHA256SUMS"
    with urllib.request.urlopen(url, timeout=60) as response:
        text = response.read().decode("utf-8", errors="replace")
    return parse_sha256sums(text), url


def sha256_checksum(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def download_verified(url, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.download")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
            checksum = hashlib.sha256()
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                checksum.update(chunk)
        if checksum.hexdigest().lower() != expected.lower():
            raise ValueError(f"SHA256 mismatch for {target.name}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Downloaded {target.name}: sha256:{expected.lower()}")


def ensure_base_image(target, expected, local=None):
    if local is not None:
        source = Path(local)
        if not source.is_file():
            raise ValueError(f"Local image does not exist: {source}")
        if sha256_checksum(source).lower() != expected.lower():
            raise ValueError(f"Local image checksum mismatch for {source.name}")
        if source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        print(f"Using local example image {target}")
        return target
    if target.is_file():
        if sha256_checksum(target).lower() == expected.lower():
            print(f"Existing example image already verified: {target}")
            return target
        raise ValueError(f"Existing example image failed SHA256 verification: {target}")
    download_verified(f"{BASE_URL}{target.name}", target, expected)
    return target


def create_overlay(qemu_img, base, overlay, size):
    overlay.parent.mkdir(parents=True, exist_ok=True)
    if overlay.is_file():
        print(f"Managed guest disk already exists: {overlay}")
        return overlay
    subprocess.run(
        [str(qemu_img), "create", "-f", "qcow2", "-b", str(base), "-F", "qcow2", str(overlay), size],
        check=True,
    )
    print(f"Created managed guest disk {overlay}")
    return overlay


def resolve_qemu_img(explicit=None):
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise ValueError(f"qemu-img does not exist: {path}")
        return path
    found = shutil.which("qemu-img")
    if not found:
        raise ValueError("qemu-img not found; install QEMU or pass --qemu-img")
    return Path(found)


def prepare(arch, output_dir, size, qemu_img=None, local_image=None, dry_run=False):
    arch = normalize_arch(arch)
    remote_name = image_remote_name(arch)
    checksums, checksum_url = remote_checksums()
    try:
        expected = checksums[remote_name]
    except KeyError:
        raise ValueError(f"{checksum_url} has no entry for {remote_name}") from None
    overlay = output_dir / managed_disk_name(arch)
    base = output_dir / remote_name
    print(f"Example image: {remote_name} (sha256:{expected})")
    if dry_run:
        print(f"Dry run: would download {remote_name} and create {overlay}")
        return overlay
    ensure_base_image(base, expected, local_image)
    create_overlay(resolve_qemu_img(qemu_img), base, overlay, size)
    print(f"AndroidBox will auto-detect {overlay} on next launch.")
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("auto", "amd64", "x86_64", "arm64", "aarch64"), default="auto")
    parser.add_argument("--output-dir", type=Path, help="Managed disk directory (defaults to the AndroidBox state directory)")
    parser.add_argument("--local-image", type=Path, help="Use an existing Ubuntu cloud image; its checksum is still verified")
    parser.add_argument("--size", default=DEFAULT_DISK_SIZE, help="Virtual disk size passed to qemu-img")
    parser.add_argument("--qemu-img", type=Path, help="Path to qemu-img when it is not on PATH")
    parser.add_argument("--dry-run", action="store_true", help="Print the pinned asset and checksum without downloading")
    args = parser.parse_args()
    arch = normalize_arch(platform.machine()) if args.arch == "auto" else args.arch
    output_dir = args.output_dir or (state_directory() / "guests")
    prepare(arch, output_dir, args.size, args.qemu_img, args.local_image, args.dry_run)


if __name__ == "__main__":
    main()
