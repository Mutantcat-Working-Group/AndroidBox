#!/usr/bin/env python3
"""Download a pinned Ubuntu cloud image and create a managed AndroidBox guest disk.

AndroidBox looks for state_directory()/guests/androidbox-{arch}.qcow2 at first
launch. Full prebuilt Android disks are too large to commit to the repository,
so this command downloads the fixed Ubuntu 24.04 minimal cloud image, verifies
its official SHA256 checksum, and writes a 32 GiB QCOW2 overlay with that name.
The implementation lives in androidbox.guestdisk so the frozen application's
in-app preparation and this command share one code path.
"""

import argparse
from pathlib import Path
import platform

from androidbox import guestdisk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("auto", "amd64", "x86_64", "arm64", "aarch64"), default="auto")
    parser.add_argument("--output-dir", type=Path, help="Managed disk directory (defaults to the AndroidBox state directory)")
    parser.add_argument("--local-image", type=Path, help="Use an existing Ubuntu cloud image; its checksum is still verified")
    parser.add_argument("--size", default=guestdisk.DEFAULT_DISK_SIZE, help="Virtual disk size of the overlay")
    parser.add_argument("--dry-run", action="store_true", help="Print the pinned asset and checksum without downloading")
    args = parser.parse_args()
    arch = guestdisk.normalize_arch(platform.machine()) if args.arch == "auto" else args.arch
    directory = args.output_dir or (guestdisk.state_directory() / "guests")
    overlay = guestdisk.prepare(arch, directory, args.size, local_image=args.local_image, dry_run=args.dry_run)
    print(f"Example guest disk ready: {overlay}")


if __name__ == "__main__":
    main()
