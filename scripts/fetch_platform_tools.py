#!/usr/bin/env python3
"""Fetch pinned Android SDK Platform Tools for bundling ADB into installers."""

import argparse
import hashlib
import io
from pathlib import Path
import platform
import shutil
import urllib.request
import zipfile


VERSION = "37.0.1"
BASE_URL = "https://dl.google.com/android/repository"
ARCHIVES = {
    "Darwin": {
        "name": f"platform-tools_r{VERSION}-darwin.zip",
        "sha1": "6ae73f4de6452dc57e62ec02b68eed92a4c21661",
        "sha256": "ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d",
    },
    "Linux": {
        "name": f"platform-tools_r{VERSION}-linux.zip",
        "sha1": "477254aa5f903c15cf51001717bdf347fb6b53e0",
        "sha256": "d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1",
    },
    "Windows": {
        "name": f"platform-tools_r{VERSION}-win.zip",
        "sha1": "e03e78b1d80b396f1c3358e31251cb31740e1110",
        "sha256": "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99",
    },
}


def _verified_payload(archive, name, expected):
    source = Path(archive).open("rb") if archive else urllib.request.urlopen(f"{BASE_URL}/{name}", timeout=120)
    with source as stream:
        payload = stream.read()
    if hashlib.sha1(payload).hexdigest() != expected["sha1"]:
        raise ValueError("Android Platform Tools SHA1 mismatch")
    if hashlib.sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError("Android Platform Tools SHA256 mismatch")
    return payload


def install(target, archive=None):
    system = platform.system()
    if system not in ARCHIVES:
        raise ValueError(f"No pinned Android Platform Tools package for {system}")
    expected = ARCHIVES[system]
    target = Path(target).resolve()
    payload = _verified_payload(archive, expected["name"], expected)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive_file:
        extracted_root = archive_file.namelist()[0].split("/", 1)[0]
        parent = target.parent
        staging = parent / f".{target.name}.extract"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        archive_file.extractall(staging)
    source = staging / extracted_root
    if not source.is_dir():
        raise ValueError("Android Platform Tools archive has an unexpected layout")
    if not (source / "NOTICE.txt").is_file():
        raise ValueError("Android Platform Tools archive is missing NOTICE.txt")
    for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll") if system == "Windows" else ("adb",):
        path = source / name
        if not path.is_file():
            raise ValueError(f"Android Platform Tools archive is missing {name}")
        path.chmod(0o755)
    backup = parent / f".{target.name}.old"
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    try:
        source.rename(target)
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists():
            backup.rename(target)
        raise
    print(f"Installed Android Platform Tools {VERSION} at {target}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[1] / "build/platform-tools")
    parser.add_argument("--archive", type=Path, help="Use an already downloaded archive, still verifying both checksums")
    args = parser.parse_args()
    install(args.target, args.archive)


if __name__ == "__main__":
    main()
