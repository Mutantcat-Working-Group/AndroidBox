"""Wrap a native PyInstaller output in an NSIS installer, signed DMG or AppImage."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

if __package__:
    # Imported as scripts.package_desktop, for example by the test suite.
    from scripts.release_metadata import validate_versions, windows_version
    from scripts.sign_macos import sign_app
else:
    # Executed directly as `python scripts/package_desktop.py`.
    from release_metadata import validate_versions, windows_version
    from sign_macos import sign_app


ROOT = Path(__file__).resolve().parents[1]
VOLUME_NAME = "AndroidBox"


def run(*command, **kwargs):
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def mounted_volumes(name=VOLUME_NAME):
    """List mounted volumes that already claim the installer's volume name."""
    completed = subprocess.run(["mount"], capture_output=True, text=True)
    volumes = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 3 or not fields[2].startswith("/Volumes/"):
            continue
        if Path(fields[2]).name.split(" ")[0] == name:
            volumes.append(fields[2])
    return volumes


def release_volume(name=VOLUME_NAME):
    """Detach a volume an earlier run left behind, which hdiutil reports as busy."""
    for volume in mounted_volumes(name):
        subprocess.run(["hdiutil", "detach", volume], capture_output=True)


def create_dmg(source, target, name=VOLUME_NAME):
    """Build the disk image, tolerating the transient busy state of a reused runner."""
    command = ["hdiutil", "create", "-volname", name, "-srcfolder", str(source),
               "-format", "UDZO", "-ov", str(target)]
    release_volume(name)
    if subprocess.run(command, capture_output=True, text=True).returncode == 0:
        return
    time.sleep(5)
    release_volume(name)
    run(*command)


def package_mac(version, arch, output):
    arch = "arm64" if arch in ("aarch64", "arm64") else "x86_64"
    app = ROOT / "dist/AndroidBox.app"
    if not app.is_dir():
        raise ValueError("Build dist/AndroidBox.app first")
    sign_app(app)
    target = output / f"AndroidBox-{version}-macOS-{arch}.dmg"
    with tempfile.TemporaryDirectory(prefix="androidbox-dmg-") as temporary:
        stage = Path(temporary)
        run("ditto", app, stage / app.name)
        (stage / "Applications").symlink_to("/Applications")
        create_dmg(stage, target)
    run("codesign", "--force", "--sign", "-", target)
    run("codesign", "--verify", "--verbose=2", target)
    run("hdiutil", "verify", target)
    return target


def package_windows(version, output, images_raw=None):
    compiler = shutil.which("makensis") or str(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "NSIS/makensis.exe")
    target = output / f"AndroidBox-{version}-Windows-x86_64-Setup.exe"
    defines = ["/DIMAGES_PKG=1"] if images_raw is not None else []
    with tempfile.TemporaryDirectory(prefix="androidbox-payload-", dir=ROOT) as temporary:
        stage = stage_payload(ROOT / "dist/AndroidBox", Path(temporary) / "payload")
        run(compiler, "/WX", f"/DVERSION={version}",
            f"/DNUMERIC_VERSION={'.'.join(map(str, windows_version(version)))}",
            f"/DPAYLOAD={stage}", f"/DOUTPUT={target}",
            f"/DLICENSE_FILE={ROOT / 'LICENSE'}",
            f"/DICON_FILE={ROOT / 'packaging/icons/AndroidBox.ico'}",
            *defines, ROOT / "packaging/windows.nsi")
    if images_raw is not None:
        from androidbox.imagesstore import append

        append(target, Path(images_raw))
    return target


def stage_payload(source, stage):
    """Hard-link the application payload, leaving the guest image disk behind.

    makensis fails to mmap a datablock that grew past its 16 MiB threshold,
    so the image disk cannot enter the NSIS database: it is appended to the
    finished installer instead and the installer copies it beside the
    runtime directory, where the client expands it on first boot.
    """
    from androidbox.bundled import IMAGES_DISK

    def ignore(directory, names):
        return {name for name in names if name in (IMAGES_DISK, f"{IMAGES_DISK}.part")}

    shutil.copytree(source, stage, copy_function=os.link, ignore=ignore, symlinks=True)
    return stage


def package_linux(version, output, appimagetool, arch):
    if not appimagetool:
        raise ValueError("--appimagetool is required on Linux")
    if arch not in ("x86_64", "aarch64"):
        raise ValueError(f"Unsupported Linux packaging architecture: {arch}")
    target = output / f"AndroidBox-{version}-Linux-{arch}.AppImage"
    with tempfile.TemporaryDirectory(prefix="androidbox-appdir-") as temporary:
        appdir = Path(temporary) / "AndroidBox.AppDir"
        shutil.copytree(ROOT / "dist/AndroidBox", appdir / "usr/lib/androidbox", symlinks=True)
        shutil.copy2(ROOT / "packaging/AppRun", appdir / "AppRun")
        (appdir / "AppRun").chmod(0o755)
        shutil.copy2(ROOT / "packaging/androidbox-appimage.desktop", appdir / "org.mutantcat.androidbox.desktop")
        shutil.copy2(ROOT / "data/AppIcon.png", appdir / "org.mutantcat.androidbox.png")
        (appdir / ".DirIcon").symlink_to("org.mutantcat.androidbox.png")
        environment = dict(os.environ, ARCH=arch, APPIMAGE_EXTRACT_AND_RUN="1")
        run(Path(appimagetool).resolve(), "--no-appstream", appdir, target, env=environment)
    target.chmod(0o755)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--appimagetool")
    parser.add_argument("--images-raw", type=Path,
                        help="Windows only: bundled Android image disk to append to the installer")
    parser.add_argument("--arch", choices=["x86_64", "aarch64", "arm64"])
    parser.add_argument("--output", type=Path, default=ROOT / "dist/installers")
    args = parser.parse_args()
    version = validate_versions(ROOT)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.arch:
        arch = args.arch
    elif sys.platform.startswith("linux"):
        arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    else:
        arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(platform.machine().lower())
    if sys.platform == "darwin" and arch in ("arm64", "x86_64"):
        target = package_mac(version, arch, output)
    elif sys.platform == "win32" and arch == "x86_64":
        target = package_windows(version, output, args.images_raw)
    elif sys.platform.startswith("linux") and arch in ("x86_64", "aarch64"):
        target = package_linux(version, output, args.appimagetool, arch)
    else:
        raise ValueError("Unsupported packaging host")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Installer tool did not produce a nonempty artifact")
    print(target)


if __name__ == "__main__":
    main()
