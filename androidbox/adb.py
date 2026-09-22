"""Authenticated APK installation and file transfer for a loopback-forwarded guest."""

import shutil
import time
from pathlib import Path

from .process import run
from . import bundled

DOWNLOAD_DIRECTORY = "/sdcard/Download"


def executable():
    return bundled.binary("adb") or shutil.which("adb")


def connect_device(adb, target):
    """Connect to the guest and wait until ADB is allowed to talk to it."""
    run([adb, "connect", target], timeout=15)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = run([adb, "-s", target, "get-state"], timeout=10)
        if state.returncode == 0 and state.stdout.strip() == "device":
            return
        time.sleep(1)
    raise RuntimeError("Android device not ready. Authorize the host ADB key in the Android window, then retry.")


def install_apk(adb, target, path):
    connect_device(adb, target)
    result = run([adb, "-s", target, "install", "-r", path], timeout=180)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.strip()


def push_file(adb, target, path, directory=DOWNLOAD_DIRECTORY):
    """Copy one host file into the guest's Download directory."""
    result = run([adb, "-s", target, "push", str(path), f"{directory}/{Path(path).name}"], timeout=600)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip() or f"Could not upload {Path(path).name}")


def transfer_files(adb, target, paths, progress=None):
    """Upload files into the guest, installing anything with an APK suffix.

    A file that fails does not stop the rest of the batch; the failures are
    collected and raised together once every path has been tried.
    """
    connect_device(adb, target)
    uploaded, installed, failures = [], [], []
    for path in paths:
        name = Path(path).name
        try:
            if progress is not None:
                progress(f"Uploading {name}...")
            push_file(adb, target, path)
            uploaded.append(name)
            if name.lower().endswith(".apk"):
                if progress is not None:
                    progress(f"Installing {name}...")
                install_apk(adb, target, path)
                installed.append(name)
        except (RuntimeError, OSError) as error:
            failures.append(f"{name}: {error}")
    summary = f"Uploaded {len(uploaded)} file(s) to {DOWNLOAD_DIRECTORY}"
    if installed:
        summary += f"; installed {len(installed)} package(s): {', '.join(installed)}"
    if failures:
        raise RuntimeError(summary + " | failed: " + "; ".join(failures))
    return summary
