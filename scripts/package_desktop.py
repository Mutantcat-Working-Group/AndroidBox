"""Wrap a native PyInstaller output in an NSIS installer, signed DMG or AppImage."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from release_metadata import validate_versions, windows_version
from sign_macos import sign_app


ROOT = Path(__file__).resolve().parents[1]


def run(*command, **kwargs):
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def package_mac(version, arch, output):
    app = ROOT / "dist/AndroidBox.app"
    if not app.is_dir():
        raise ValueError("Build dist/AndroidBox.app first")
    sign_app(app)
    target = output / f"AndroidBox-{version}-macOS-{arch}.dmg"
    with tempfile.TemporaryDirectory(prefix="androidbox-dmg-") as temporary:
        stage = Path(temporary)
        run("ditto", app, stage / app.name)
        (stage / "Applications").symlink_to("/Applications")
        run("hdiutil", "create", "-volname", "AndroidBox", "-srcfolder", stage,
            "-format", "UDZO", "-ov", target)
    run("codesign", "--force", "--sign", "-", target)
    run("codesign", "--verify", "--verbose=2", target)
    run("hdiutil", "verify", target)
    return target


def package_windows(version, output):
    compiler = shutil.which("makensis") or str(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "NSIS/makensis.exe")
    target = output / f"AndroidBox-{version}-Windows-x86_64-Setup.exe"
    run(compiler, f"/DVERSION={version}",
        f"/DNUMERIC_VERSION={'.'.join(map(str, windows_version(version)))}",
        f"/DPAYLOAD={ROOT / 'dist/AndroidBox'}", f"/DOUTPUT={target}",
        f"/DLICENSE_FILE={ROOT / 'LICENSE'}",
        f"/DICON_FILE={ROOT / 'packaging/icons/AndroidBox.ico'}", ROOT / "packaging/windows.nsi")
    return target


def package_linux(version, output, appimagetool):
    if not appimagetool:
        raise ValueError("--appimagetool is required on Linux")
    target = output / f"AndroidBox-{version}-Linux-x86_64.AppImage"
    with tempfile.TemporaryDirectory(prefix="androidbox-appdir-") as temporary:
        appdir = Path(temporary) / "AndroidBox.AppDir"
        shutil.copytree(ROOT / "dist/AndroidBox", appdir / "usr/lib/androidbox", symlinks=True)
        shutil.copy2(ROOT / "packaging/AppRun", appdir / "AppRun")
        (appdir / "AppRun").chmod(0o755)
        shutil.copy2(ROOT / "packaging/androidbox-appimage.desktop", appdir / "org.mutantcat.androidbox.desktop")
        shutil.copy2(ROOT / "data/AppIcon.png", appdir / "org.mutantcat.androidbox.png")
        (appdir / ".DirIcon").symlink_to("org.mutantcat.androidbox.png")
        environment = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
        run(Path(appimagetool).resolve(), "--no-appstream", appdir, target, env=environment)
    target.chmod(0o755)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--appimagetool")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/installers")
    args = parser.parse_args()
    version = validate_versions(ROOT)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(platform.machine().lower())
    if sys.platform == "darwin" and arch:
        target = package_mac(version, arch, output)
    elif arch != "x86_64":
        raise ValueError("Windows and Linux installers currently require x86_64")
    elif sys.platform == "win32":
        target = package_windows(version, output)
    elif sys.platform.startswith("linux"):
        target = package_linux(version, output, args.appimagetool)
    else:
        raise ValueError("Unsupported packaging host")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Installer tool did not produce a nonempty artifact")
    print(target)


if __name__ == "__main__":
    main()
