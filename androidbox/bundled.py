"""Locate runtime payloads within a frozen application, never the working directory."""

from pathlib import Path
import platform
import sys
import threading


def runtime_root():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "runtime"
    return None


def binary(name):
    root = runtime_root()
    if root is not None:
        suffix = ".exe" if platform.system() == "Windows" else ""
        path = root / "bin" / (name + suffix)
        if path.is_file():
            return str(path)
    return None


IMAGES_DISK = "androidbox-images.raw"
IMAGES_PACKAGE = "androidbox-images.pkg"

_materialize_lock = threading.Lock()


def images_directory(arch):
    """Return the bundled Android image directory for a guest architecture."""
    root = runtime_root()
    if root is None:
        return None
    path = root / "images" / arch
    return path if path.is_dir() else None


def images_disk(arch):
    """Return the bundled read-only Android image disk for a guest architecture.

    Release builds may ship the guest images per architecture; the block
    device is attached read-only so first boot can install them without
    reaching the OTA channels.
    Windows installers carry the disk as a compressed package beside the
    runtime directory, because a disk of this size cannot travel inside the
    NSIS database.
    """
    directory = images_directory(arch)
    if directory is not None:
        candidate = directory / IMAGES_DISK
        if candidate.is_file():
            return str(candidate)
        disk = materialize_images_disk(directory)
        if disk is not None:
            return str(disk)
    return None


def materialize_images_disk(directory):
    """Expand a packaged image disk the client has not seen yet, once."""
    disk = Path(directory) / IMAGES_DISK
    package = Path(directory) / IMAGES_PACKAGE
    with _materialize_lock:
        if disk.is_file() and disk.stat().st_size > 0:
            return disk
        if not package.is_file():
            return None
        from . import imagesstore

        imagesstore.extract(package, disk)
    try:
        # The expanded disk replaces the package it came from.
        package.unlink()
    except OSError:
        pass
    return disk


def qemu_data(executable):
    root = runtime_root()
    if root is not None and contains_binary(executable):
        path = root / "share/qemu"
        if path.is_dir():
            return path
    return None


def contains_binary(executable):
    root = runtime_root()
    return root is not None and bool(executable) and Path(executable).resolve().parent == (root / "bin").resolve()


def arm_firmware():
    root = runtime_root()
    if root is not None:
        # Distros ship the AArch64 UEFI firmware under different basenames; the
        # payload stage keeps whichever name it collected under share/qemu.
        for name in ("edk2-aarch64-code.fd", "AAVMF_CODE.fd", "QEMU_EFI.fd"):
            path = root / "share/qemu" / name
            if path.is_file():
                return str(path)
    return ""


def verify_runtime():
    from .process import run
    from .runtime import normalize_arch

    arch = normalize_arch(platform.machine())
    programs = {"qemu": (binary(f"qemu-system-{arch}"), "--version"),
                "adb": (binary("adb"), "version")}
    for name, (executable, _) in programs.items():
        if not executable:
            raise ValueError(f"Missing bundled {name}")
    if not qemu_data(programs["qemu"][0]):
        raise ValueError("Missing bundled QEMU data")
    if arch == "aarch64" and not arm_firmware():
        raise ValueError("Missing bundled ARM firmware")
    result = {}
    for name, (executable, argument) in programs.items():
        completed = run([executable, argument], timeout=10, check=True)
        version = completed.stdout.strip()
        if not version:
            raise ValueError(f"Bundled {name} returned no version")
        result[name] = {"path": executable, "version": version}
    return result


def verify_images():
    """Describe the bundled guest image disk the client attaches at boot."""
    from .runtime import normalize_arch

    arch = normalize_arch(platform.machine())
    disk = images_disk(arch)
    if disk is None:
        raise ValueError(f"Missing bundled Android image disk for {arch}")
    size = Path(disk).stat().st_size
    if size <= 0:
        raise ValueError(f"Bundled Android image disk is empty: {disk}")
    return {"path": disk, "arch": arch, "bytes": size}
