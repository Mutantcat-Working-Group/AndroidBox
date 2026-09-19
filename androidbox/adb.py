"""Authenticated APK installation for a single loopback-forwarded guest."""

import shutil
import time

from .process import run
from . import bundled


def executable():
    return bundled.binary("adb") or shutil.which("adb")


def install_apk(adb, target, path):
    run([adb, "connect", target], timeout=15)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = run([adb, "-s", target, "get-state"], timeout=10)
        if state.returncode == 0 and state.stdout.strip() == "device":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Android device not ready. Authorize the host ADB key in the Android window, then retry.")
    result = run([adb, "-s", target, "install", "-r", path], timeout=180)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.strip()
