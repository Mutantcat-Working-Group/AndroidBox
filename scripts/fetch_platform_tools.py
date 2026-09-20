#!/usr/bin/env python3
"""Fetch pinned Android SDK Platform Tools for bundling ADB into installers.

Google publishes Platform Tools for macOS and Windows as universal or x86_64
builds, but the Linux archive is x86_64 only. Linux AArch64 therefore stages
the distribution's own ADB together with the shared libraries it needs, so the
bundled runtime stays runnable instead of carrying an unusable x86_64 binary.
"""

import argparse
import hashlib
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
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

# Google publishes no AArch64 Linux Platform Tools archive, so those hosts take
# the distribution's own ADB instead of an x86_64 binary they cannot execute.
DISTRIBUTION_ADB = {("Linux", "aarch64")}

# Build scripts run before `pip install`, so the architecture aliases live here
# rather than in the package.
ARCH_ALIASES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}

# The dynamic loader and libc always come from the host, never from a bundle.
HOST_LIBRARIES = {
    "ld-linux-aarch64.so.1", "ld-linux-x86-64.so.2", "libc.so", "libc.so.6",
    "libcrypt.so.1", "libdl.so.2", "libm.so.6", "libpthread.so.0",
    "libresolv.so.2", "librt.so.1", "libutil.so.1",
}

DISTRIBUTION_ADB_PATHS = ("/usr/bin/adb", "/usr/lib/android-sdk-platform-tools/adb")
DISTRIBUTION_DOCUMENTS = ("android-tools-adb", "adb", "android-platform-tools")

NOTICE = """Android Debug Bridge (adb)

Android Open Source Project, licensed under the Apache License, Version 2.0.
https://developer.android.com/studio/releases/platform-tools

This build was staged from the operating system packages because Google
publishes no AArch64 Linux Platform Tools archive. The distribution license
text for the packaged binary and its libraries follows.

"""


def host_arch(value=None):
    try:
        return ARCH_ALIASES[(value or platform.machine()).lower()]
    except KeyError:
        raise ValueError(f"Unsupported architecture: {value or platform.machine()}") from None


def archive_for(system, arch):
    """Return the pinned Platform Tools archive, or None when the host package provides ADB."""
    return None if (system, arch) in DISTRIBUTION_ADB else ARCHIVES.get(system)


def _verified_payload(archive, name, expected):
    source = Path(archive).open("rb") if archive else urllib.request.urlopen(f"{BASE_URL}/{name}", timeout=120)
    with source as stream:
        payload = stream.read()
    if hashlib.sha1(payload).hexdigest() != expected["sha1"]:
        raise ValueError("Android Platform Tools SHA1 mismatch")
    if hashlib.sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError("Android Platform Tools SHA256 mismatch")
    return payload


def _staging(target):
    path = target.parent / f".{target.name}.extract"
    if path.exists():
        shutil.rmtree(path)
    return path


def _promote(staging, target):
    """Move a staged payload into place, restoring the previous one on failure."""
    backup = target.parent / f".{target.name}.old"
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists():
            backup.rename(target)
        raise


def install(target, archive=None, system=None, arch=None):
    system = system or platform.system()
    arch = host_arch(arch)
    if system not in ARCHIVES:
        raise ValueError(f"No pinned Android Platform Tools package for {system}")
    expected = archive_for(system, arch)
    target = Path(target).resolve()
    if expected is None:
        return install_distribution(target)
    payload = _verified_payload(archive, expected["name"], expected)
    staging = _staging(target)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive_file:
        extracted_root = archive_file.namelist()[0].split("/", 1)[0]
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
    _promote(source, target)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"Installed Android Platform Tools {VERSION} at {target}")
    return target


def distribution_adb():
    """Locate the ADB executable the operating system provides."""
    candidates = [shutil.which("adb")]
    candidates += [Path(path) for path in DISTRIBUTION_ADB_PATHS]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def shared_libraries(binary):
    """Resolve the shared libraries a binary loads, skipping host loader pieces."""
    completed = subprocess.run(["ldd", str(binary)], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, check=True, timeout=60)
    libraries = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[1] != "=>":
            continue
        name, path = fields[0], Path(fields[2])
        if name in HOST_LIBRARIES or not path.is_file() or path in libraries:
            continue
        libraries.append(path)
    return libraries


def set_runpath(binary):
    """Point a staged ADB at the libraries shipped beside it."""
    patchelf = shutil.which("patchelf")
    if patchelf is None:
        raise ValueError("Install patchelf to stage the distribution ADB shared libraries")
    subprocess.run([patchelf, "--set-rpath", "$ORIGIN/lib", str(binary)], check=True, timeout=60)


def distribution_copyright(documents=None):
    """Collect the distribution license text for the staged ADB packages."""
    documents = Path(documents) if documents else Path("/usr/share/doc")
    if not documents.is_dir():
        return ""
    for name in DISTRIBUTION_DOCUMENTS:
        path = documents / name / "copyright"
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def require_runnable(binary):
    """Fail the build rather than ship an ADB the host cannot execute."""
    environment = {name: value for name, value in os.environ.items() if name != "LD_LIBRARY_PATH"}
    completed = subprocess.run([str(binary), "version"], env=environment,
                               capture_output=True, text=True, timeout=60)
    if completed.returncode or not completed.stdout.strip():
        raise ValueError(f"Staged ADB did not run: {completed.stderr.strip()}")


def install_distribution(target, documents=None):
    """Stage the distribution's ADB and its shared libraries next to each other."""
    source = distribution_adb()
    if source is None:
        raise ValueError("Google publishes no AArch64 Linux Platform Tools archive; "
                         "install the distribution's adb package to bundle one")
    staging = _staging(target)
    (staging / "lib").mkdir(parents=True)
    binary = staging / "adb"
    shutil.copy2(source, binary)
    binary.chmod(0o755)
    for library in shared_libraries(source):
        shutil.copy2(library, staging / "lib" / library.name)
    set_runpath(binary)
    (staging / "NOTICE.txt").write_text(NOTICE + distribution_copyright(documents), encoding="utf-8")
    require_runnable(binary)
    _promote(staging, target)
    print(f"Staged distribution Android Platform Tools at {target}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[1] / "build/platform-tools")
    parser.add_argument("--archive", type=Path, help="Use an already downloaded archive, still verifying both checksums")
    parser.add_argument("--arch", choices=("auto", "amd64", "x86_64", "arm64", "aarch64"), default="auto")
    args = parser.parse_args()
    install(args.target, args.archive, arch=None if args.arch == "auto" else args.arch)


if __name__ == "__main__":
    main()
