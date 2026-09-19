#!/usr/bin/env python3
"""Fetch the pinned noVNC sources for local use and distributable wheels."""

import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request


VERSION = "1.6.0"
URL = f"https://github.com/novnc/noVNC/archive/refs/tags/v{VERSION}.tar.gz"
SHA256 = "5066103959ef4e9b10f37e5a148627360dd8414e4cf8a7db92bdbd022e728aaa"


def install(archive=None):
    if archive:
        payload = Path(archive).read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            payload = response.read(5 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError("noVNC archive checksum mismatch")
    target = Path(__file__).resolve().parents[1] / "androidbox/web/novnc"
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive_file:
        for member in archive_file:
            relative = PurePosixPath(member.name).relative_to(f"noVNC-{VERSION}")
            if not relative.parts or relative.parts[0] not in {"core", "vendor", "LICENSE.txt", "AUTHORS"}:
                continue
            if ".." in relative.parts or not member.isfile():
                continue
            output = target.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive_file.extractfile(member) as source:
                output.write_bytes(source.read())
    print(f"Installed noVNC {VERSION} at {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", help="Use an already downloaded archive (checksum is still verified)")
    install(parser.parse_args().archive)
