"""Fetch the pinned official AppImageTool release and verify its SHA256."""

import argparse
import hashlib
from pathlib import Path
import urllib.request


VERSION = "1.9.0"
ASSET = "appimagetool-x86_64.AppImage"
URL = f"https://github.com/AppImage/appimagetool/releases/download/{VERSION}/{ASSET}"
# Pinned from the official HTTPS release asset; this release has no API digest.
SHA256 = "46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1"


def fetch(target, archive=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    try:
        source = Path(archive).open("rb") if archive else urllib.request.urlopen(URL, timeout=120)
        with source as response, temporary.open("wb") as stream:
            checksum = hashlib.sha256()
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                checksum.update(chunk)
        if checksum.hexdigest() != SHA256:
            raise ValueError("AppImageTool SHA256 mismatch")
        temporary.chmod(0o755)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Verified AppImageTool {VERSION}: sha256:{SHA256}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an existing download, still verifying its checksum")
    args = parser.parse_args()
    fetch(Path(__file__).resolve().parents[1] / "build/appimagetool.AppImage", args.archive)


if __name__ == "__main__":
    main()
