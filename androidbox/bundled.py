"""Locate runtime payloads within a frozen application, never the working directory."""

from pathlib import Path
import platform
import sys


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
        path = root / "share/qemu/edk2-aarch64-code.fd"
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
