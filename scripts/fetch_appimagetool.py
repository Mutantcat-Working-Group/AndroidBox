"""Fetch the pinned official AppImageTool release and verify its SHA256."""

import argparse
import hashlib
from pathlib import Path
import platform
import urllib.request


VERSION = "1.9.0"
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}[platform.machine().lower()]
# Pinned from the official HTTPS release assets; this release has no API digest.
PINNED_SHA256 = {
    "x86_64": "46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1",
    "aarch64": "04f45ea45b5aa07bb2b071aed9dbf7a5185d3953b11b47358c1311f11ea94a96",
}
SHA256 = PINNED_SHA256[ARCH]


def asset(arch=ARCH):
    return f"appimagetool-{arch}.AppImage"


def url(arch=ARCH):
    return f"https://github.com/AppImage/appimagetool/releases/download/{VERSION}/{asset(arch)}"


ASSET = asset()
URL = url()


def fetch(target, arch=None, archive=None):
    arch = arch or ARCH
    if arch not in PINNED_SHA256:
        raise ValueError(f"Unsupported AppImageTool architecture: {arch}")
    expected_sha256 = PINNED_SHA256[arch]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    try:
        source = Path(archive).open("rb") if archive else urllib.request.urlopen(url(arch), timeout=120)
        with source as response, temporary.open("wb") as stream:
            checksum = hashlib.sha256()
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                checksum.update(chunk)
        if checksum.hexdigest() != expected_sha256:
            raise ValueError("AppImageTool SHA256 mismatch")
        temporary.chmod(0o755)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Verified AppImageTool {VERSION}/{arch}: sha256:{expected_sha256}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=sorted(PINNED_SHA256), default=ARCH)
    parser.add_argument("--archive", type=Path, help="Use an existing download, still verifying its checksum")
    args = parser.parse_args()
    fetch(Path(__file__).resolve().parents[1] / "build/appimagetool.AppImage", args.arch, args.archive)


if __name__ == "__main__":
    main()
