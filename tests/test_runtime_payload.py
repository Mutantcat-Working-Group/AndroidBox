from pathlib import Path
import tempfile
import unittest

from scripts.runtime_payload import collect_qemu, collect_adb


class RuntimePayloadTests(unittest.TestCase):
    def test_windows_qemu_collects_adjacent_dlls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ("qemu-system-x86_64.exe", "libglib-2.0-0.dll", "COPYING", "share/bios-256k.bin"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            binaries, data = collect_qemu(root, "x86_64", system="Windows")
            self.assertIn((str(root / "qemu-system-x86_64.exe"), "runtime/bin"), binaries)
            self.assertIn((str(root / "libglib-2.0-0.dll"), "runtime/bin"), binaries)
            self.assertIn((str(root / "share"), "runtime/share/qemu"), data)

    def test_adb_collects_windows_dlls_and_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt", "source.properties"):
                (root / name).touch()
            binaries, data = collect_adb(root, system="Windows")
            self.assertEqual({Path(source).name for source, _ in binaries},
                             {"adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"})
            self.assertIn((str(root / "NOTICE.txt"), "licenses/adb"), data)

    def test_adb_requires_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "adb").touch()
            with self.assertRaisesRegex(ValueError, "NOTICE"):
                collect_adb(root, system="Darwin")

    def test_collects_native_binary_firmware_and_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ("bin/qemu-system-aarch64", "share/qemu/edk2-aarch64-code.fd", "COPYING"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            binaries, data = collect_qemu(root, "aarch64", system="Darwin")
            self.assertIn((str(root / "bin/qemu-system-aarch64"), "runtime/bin"), binaries)
            self.assertIn((str(root / "share/qemu"), "runtime/share/qemu"), data)
            self.assertIn((str(root / "COPYING"), "licenses/qemu"), data)

    def test_rejects_incomplete_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "QEMU"):
                collect_qemu(Path(directory), "x86_64")

    def test_arm_payload_requires_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "bin/qemu-system-aarch64").touch()
            (root / "share/qemu").mkdir(parents=True)
            (root / "COPYING").touch()
            with self.assertRaisesRegex(ValueError, "firmware"):
                collect_qemu(root, "aarch64", system="Darwin")
