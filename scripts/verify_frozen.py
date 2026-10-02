"""Start the built executable outside the checkout and require a self-test report."""

import argparse
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile


def verify(executable, require_runtime=False, require_images=False):
    executable = Path(executable).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="androidbox-frozen-") as directory:
        root = Path(directory)
        report = root / "result.json"
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu")
        environment.pop("PYTHONPATH", None)
        command = [str(executable), "--self-test", "--report", str(report),
                   "--screenshot", str(root / "desktop.png")]
        if require_runtime:
            command.append("--require-runtime")
        if require_images:
            command.append("--require-images")
        # A windowed frozen executable has no console, so its output is the only
        # way a failing self-test can explain itself inside CI logs.
        completed = subprocess.run(command, cwd=root, env=environment, timeout=90,
                                   capture_output=True, text=True, errors="replace")
        if completed.stdout:
            print(completed.stdout.strip())
        if completed.stderr:
            print(completed.stderr.strip(), file=sys.stderr)
        if completed.returncode != 0:
            if report.is_file():
                try:
                    print("self-test report: " + report.read_text(encoding="utf-8").strip())
                except OSError:
                    pass
            raise subprocess.CalledProcessError(completed.returncode, command,
                                                output=completed.stdout,
                                                stderr=completed.stderr)
        result = json.loads(report.read_text(encoding="utf-8"))
        if result.get("passed") is not True or result.get("frozen") is not True:
            raise ValueError(f"Frozen application self-test failed: {result}")
        if not (root / "desktop.png").is_file():
            raise ValueError("Frozen application did not render its window")
        if require_runtime and any(not result.get("runtime", {}).get(name, {}).get(field)
                                  for name in ("qemu", "adb") for field in ("path", "version")):
            raise ValueError("Frozen application did not verify its bundled runtime")
        if require_images and not result.get("images", {}).get("path"):
            raise ValueError("Frozen application did not bundle the Android image disk")
    print(f"Frozen Qt/noVNC self-test passed: {executable}")


def assert_adhoc_signed(target):
    """Reject a seal that a paid certificate could have produced instead."""
    completed = subprocess.run(["codesign", "-dv", str(target)],
                                capture_output=True, text=True)
    details = (completed.stdout + completed.stderr).strip()
    if "Signature=adhoc" not in details:
        raise ValueError(f"{target} is not ad-hoc signed: {details}")


def verify_dmg(image, require_runtime=False, require_images=False):
    image = Path(image).resolve(strict=True)
    assert_adhoc_signed(image)
    subprocess.run(["codesign", "--verify", "--verbose=2", str(image)], check=True)
    subprocess.run(["hdiutil", "verify", str(image)], check=True)
    with tempfile.TemporaryDirectory(prefix="androidbox-mount-") as directory:
        mount = Path(directory) / "volume"
        subprocess.run(["hdiutil", "attach", str(image), "-readonly", "-nobrowse",
                        "-mountpoint", str(mount)], check=True, timeout=120)
        try:
            shortcut = mount / "Applications"
            if not shortcut.is_symlink() or os.readlink(shortcut) != "/Applications":
                raise ValueError("The disk image is missing its /Applications shortcut")
            app = mount / "AndroidBox.app"
            assert_adhoc_signed(app)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            verify(app / "Contents/MacOS/AndroidBox", require_runtime=require_runtime,
                   require_images=require_images)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True, timeout=120)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--require-images", action="store_true",
                        help="Require the bundled Android image disk")
    parser.add_argument("--dmg", action="store_true", help="Mount and verify a macOS disk image")
    args = parser.parse_args()
    operation = verify_dmg if args.dmg else verify
    operation(args.executable, require_runtime=args.require_runtime, require_images=args.require_images)
