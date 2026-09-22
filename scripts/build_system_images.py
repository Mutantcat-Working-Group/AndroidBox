#!/usr/bin/env python3
"""Stage the guest Android images on a read-only disk for the installers.

First boot used to download the Android archives from the Waydroid OTA
channels, which breaks on hosts that cannot reach SourceForge or verify its TLS
chain. This script fetches the very same archives the channels publish, proves
their SHA256 against the channel metadata and packs them onto an ext4
filesystem labelled ``androidbox-img``. The desktop packager attaches that
image read-only to every guest, so first boot unpacks Android with no network
access at all.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request

CHANNEL_BASE = "https://ota.waydro.id"
ROM_TYPE = "lineage"
SYSTEM_TYPE = "VANILLA"
VENDOR_TYPE = "MAINLINE"
# ext4 keeps 16 bytes of label, and the guest finds the disk with blkid -L,
# so this name is part of the guest contract (guest/provision.sh reads it too).
LABEL = "androidbox-img"
# The channels publish per-architecture builds; the tracked set is the one the
# QEMU guests can run.
OTA_ARCHITECTURES = {"x86_64": "x86_64", "aarch64": "arm64_only"}
COMPONENTS = ("system", "vendor")


def ota_url(arch, component):
    """Return the OTA channel JSON that publishes the newest entry for a component."""
    try:
        ota_arch = OTA_ARCHITECTURES[arch]
    except KeyError:
        raise ValueError(f"No Android OTA channel for architecture: {arch}")
    if component == "system":
        return f"{CHANNEL_BASE}/system/{ROM_TYPE}/waydroid_{ota_arch}/{SYSTEM_TYPE}.json"
    if component == "vendor":
        return f"{CHANNEL_BASE}/vendor/waydroid_{ota_arch}/{VENDOR_TYPE}.json"
    raise ValueError(f"Unknown Android image component: {component}")


def read_channel(arch, component):
    """Return the newest published entry of an OTA channel."""
    with urllib.request.urlopen(ota_url(arch, component)) as response:
        document = json.loads(response.read().decode("utf-8"))
    entries = document.get("response") or []
    if not entries:
        raise ValueError(f"The {component} channel publishes no images for {arch}")
    return max(entries, key=lambda entry: entry["datetime"])


def digest(path):
    """Return the SHA256 hex digest of a file on disk."""
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def download(entry, destination):
    """Download a channel entry and refuse anything but the published digest."""
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    with urllib.request.urlopen(entry["url"]) as response, partial.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    if digest(partial) != entry["id"]:
        partial.unlink(missing_ok=True)
        raise ValueError(f"{entry['filename']} does not match its published SHA256")
    partial.replace(destination)
    return destination


def stage(arch, destination):
    """Download and verify both image archives, then describe them on the disk."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    entries = {}
    for component in COMPONENTS:
        entry = read_channel(arch, component)
        entries[component] = download(entry, destination / f"{component}.zip")
    # The guest proves the archives before unpacking them, so the checksums
    # file has to name the staged copies exactly as they sit on the disk.
    checksums = "".join(f"{entries[component]['id']}  {component}.zip\n"
                        for component in COMPONENTS)
    (destination / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    manifest = {"arch": arch, "ota_arch": OTA_ARCHITECTURES[arch],
                "system_type": SYSTEM_TYPE, "vendor_type": VENDOR_TYPE,
                "images": {component: {"filename": entries[component]["filename"],
                                       "sha256": entries[component]["id"],
                                       "datetime": entries[component]["datetime"]}
                           for component in COMPONENTS}}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                               encoding="utf-8")
    return entries


def filesystem_size(staging):
    """Estimate the blocks the staged files need plus the ext4 overhead."""
    staging = Path(staging)
    data = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file())
    # Every file rounds up to a whole 4 KiB block; the journal and the inode
    # tables take a flat share. The image is shrunk to its minimum afterwards.
    blocks = sum((path.stat().st_size + 4095) // 4096
                 for path in staging.rglob("*") if path.is_file())
    return data + blocks * 4096 + 64 * 1024 * 1024


def build_disk(staging, output, label=LABEL):
    """Create the image disk and shrink it to the bytes its files need."""
    staging, output = Path(staging), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with output.open("wb") as stream:
        stream.truncate(filesystem_size(staging))
    # A small journal keeps the estimate above predictable; the disk is attached
    # read-only, so it only ever sees a clean filesystem.
    subprocess.run(["mkfs.ext4", "-F", "-q", "-b", "4096", "-J", "size=4",
                    "-L", label, "-d", str(staging), str(output)], check=True)
    subprocess.run(["e2fsck", "-fy", str(output)],
                  check=False, capture_output=True, text=True)
    # resize2fs reports the result on stdout ("... is now N (4k) blocks long.")
    # and older releases on stderr, so both streams are searched.
    shrunken = subprocess.run(["resize2fs", "-M", "-f", str(output)],
                              check=True, capture_output=True, text=True)
    report = re.search(r"is now ([0-9]+) ", shrunken.stdout + shrunken.stderr)
    if not report:
        raise ValueError(f"resize2fs did not report a block count for {output}")
    blocks = int(report.group(1))
    with output.open("r+b") as stream:
        stream.truncate(blocks * 4096)
    subprocess.run(["e2fsck", "-fn", str(output)],
                   check=True, capture_output=True, text=True)
    return output


def build(arch, output, work=None):
    """Stage the images and pack them into a read-only disk for one architecture."""
    output = Path(output)
    work = Path(work) if work else output.parent / f"images-{arch}"
    shutil.rmtree(work, ignore_errors=True)
    try:
        stage(arch, work)
        return build_disk(work, output)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", choices=sorted(OTA_ARCHITECTURES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    disk = build(args.arch, args.output)
    print(f"{disk} ({disk.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
