"""Collect a native QEMU prefix for PyInstaller dependency analysis."""

from pathlib import Path
import platform


def _qemu_license(prefix, windows=False):
    candidates = [prefix / name for name in ("COPYING", "COPYING.txt", "LICENSE", "LICENSE.txt")]
    for path in candidates:
        if path.is_file():
            return path
    # Debian/Ubuntu install the license as share/doc/<package>/copyright.
    docs = prefix / "share" / "doc"
    if docs.is_dir():
        for path in sorted(docs.rglob("copyright")):
            if path.is_file() and "qemu" in path.parent.name.lower():
                return path
    if windows:
        for pattern in ("COPYING*", "LICENSE*"):
            for path in sorted(prefix.rglob(pattern)):
                if path.is_file():
                    return path
    raise ValueError("QEMU prefix must include a COPYING, LICENSE or share/doc/<qemu>/copyright file")


def _qemu_data(prefix, windows):
    if not windows:
        return prefix / "share/qemu"
    for candidate in (prefix / "share/qemu", prefix / "share"):
        if candidate.is_dir():
            return candidate
    raise ValueError("QEMU prefix must contain a share or share/qemu data directory")


def collect_qemu(prefix, arch, system=None):
    prefix = Path(prefix).resolve(strict=True)
    if arch not in {"x86_64", "aarch64"}:
        raise ValueError(f"Unsupported QEMU architecture: {arch}")
    windows = (system or platform.system()) == "Windows"
    executable = prefix / f"qemu-system-{arch}.exe" if windows else prefix / "bin" / f"qemu-system-{arch}"
    data = _qemu_data(prefix, windows)
    license_file = _qemu_license(prefix, windows)
    if not executable.is_file() or not data.is_dir():
        raise ValueError("QEMU prefix must contain the qemu-system-ARCH executable and share/qemu data")
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
