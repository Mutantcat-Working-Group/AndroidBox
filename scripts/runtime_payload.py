"""Collect a native QEMU prefix for PyInstaller dependency analysis."""

from pathlib import Path
import platform


def collect_qemu(prefix, arch, system=None):
    prefix = Path(prefix).resolve(strict=True)
    if arch not in {"x86_64", "aarch64"}:
        raise ValueError(f"Unsupported QEMU architecture: {arch}")
    windows = (system or platform.system()) == "Windows"
    executable = prefix / f"qemu-system-{arch}.exe" if windows else prefix / "bin" / f"qemu-system-{arch}"
    data = prefix / ("share" if windows else "share/qemu")
    license_file = prefix / "COPYING"
    if not executable.is_file() or not data.is_dir() or not license_file.is_file():
        raise ValueError("QEMU prefix must contain bin/qemu-system-ARCH, share/qemu and COPYING")
    if arch == "aarch64" and not (data / "edk2-aarch64-code.fd").is_file():
        raise ValueError("QEMU ARM64 payload is missing its UEFI firmware")
    binaries = [(str(executable), "runtime/bin")]
    if windows:
        binaries += [(str(path), "runtime/bin") for path in sorted(prefix.glob("*.dll"))]
    files = [(str(data), "runtime/share/qemu"), (str(license_file), "licenses/qemu")]
    for name in ("COPYING.LIB", "LICENSE"):
        if (prefix / name).is_file():
            files.append((str(prefix / name), "licenses/qemu"))
    return binaries, files


def collect_adb(directory, system=None):
    directory = Path(directory).resolve(strict=True)
    windows = (system or platform.system()) == "Windows"
    names = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"] if windows else ["adb"]
    for name in [*names, "NOTICE.txt"]:
        if not (directory / name).is_file():
            raise ValueError(f"ADB payload is missing {name}")
    binaries = [(str(directory / name), "runtime/bin") for name in names]
    data = [(str(directory / "NOTICE.txt"), "licenses/adb")]
    if (directory / "source.properties").is_file():
        data.append((str(directory / "source.properties"), "licenses/adb"))
    return binaries, data
