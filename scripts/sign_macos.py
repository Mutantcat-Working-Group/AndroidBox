"""Sign QEMU with HVF access, then seal the application without rewriting children."""

import argparse
from pathlib import Path
import subprocess


def sign_app(app):
    app = Path(app)
    entitlements = Path(__file__).resolve().parents[1] / "packaging/qemu-entitlements.plist"
    for binary in sorted((app / "Contents/Frameworks/runtime/bin").glob("qemu-system-*")):
        subprocess.run(["codesign", "--force", "--sign", "-", "--entitlements", str(entitlements), str(binary)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    sign_app(parser.parse_args().app)
