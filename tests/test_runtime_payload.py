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

    def test_windows_qemu_accepts_share_qemu_layout_and_nested_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "qemu-system-x86_64.exe").touch()
            (root / "share/qemu").mkdir(parents=True)
            (root / "share/qemu/bios-256k.bin").touch()
            (root / "share/doc/qemu").mkdir(parents=True)
            (root / "share/doc/qemu/LICENSE").write_text("license")
            binaries, data = collect_qemu(root, "x86_64", system="Windows")
            self.assertIn((str(root / "share/qemu"), "runtime/share/qemu"), data)
            self.assertIn((str(root / "share/doc/qemu/LICENSE"), "licenses/qemu"), data)

    def test_windows_qemu_license_can_be_nested_under_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "qemu-system-x86_64.exe").touch()
            (root / "share").mkdir()
            (root / "share/doc/qemu-w64-setup").mkdir(parents=True)
            (root / "share/doc/qemu-w64-setup/COPYING.txt").write_text("license")
            binaries, data = collect_qemu(root, "x86_64", system="Windows")
            self.assertIn((str(root / "share"), "runtime/share/qemu"), data)
            self.assertIn((str(root / "share/doc/qemu-w64-setup/COPYING.txt"), "licenses/qemu"), data)

    def test_windows_qemu_prefers_share_qemu_when_both_layouts_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "qemu-system-x86_64.exe").touch()
            (root / "COPYING").touch()
            for name in ("share/root-only", "share/qemu/qemu-only"):
                (root / name).mkdir(parents=True)
            _, data = collect_qemu(root, "x86_64", system="Windows")
            self.assertIn((str(root / "share/qemu"), "runtime/share/qemu"), data)

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

    def test_accepts_debian_share_doc_copyright(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "bin").mkdir()
            (root / "bin/qemu-system-x86_64").touch()
            (root / "share/qemu").mkdir(parents=True)
            (root / "share/doc/qemu-system-common").mkdir(parents=True)
            (root / "share/doc/qemu-system-common/copyright").write_text("license")
            binaries, data = collect_qemu(root, "x86_64", system="Linux")
            self.assertIn((str(root / "share/doc/qemu-system-common/copyright"), "licenses/qemu"), data)

    def test_arm_payload_requires_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "bin/qemu-system-aarch64").touch()
            (root / "share/qemu").mkdir(parents=True)
            (root / "COPYING").touch()
            with self.assertRaisesRegex(ValueError, "firmware"):
                collect_qemu(root, "aarch64", system="Darwin")

    def test_arm_payload_stages_qemu_efi_firmware_from_debian_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "bin").mkdir()
            (root / "bin/qemu-system-aarch64").touch()
            (root / "share/qemu").mkdir(parents=True)
            (root / "share/qemu/openbios-common.elf").touch()
            (root / "share/doc/qemu-system-common").mkdir(parents=True)
            (root / "share/doc/qemu-system-common/copyright").write_text("license")
            (root / "share/qemu-efi-aarch64").mkdir(parents=True)
            (root / "share/qemu-efi-aarch64/QEMU_EFI.fd").touch()
            _, data = collect_qemu(root, "aarch64", system="Linux")
            self.assertIn((str(root / "share/qemu-efi-aarch64/QEMU_EFI.fd"), "runtime/share/qemu"), data)

    def test_arm_payload_stages_aavmf_firmware_into_share_qemu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "bin").mkdir()
            (root / "bin/qemu-system-aarch64").touch()
            (root / "share/qemu").mkdir(parents=True)
            (root / "share/AAVMF").mkdir(parents=True)
            (root / "share/AAVMF/AAVMF_CODE.fd").touch()
            (root / "COPYING").touch()
            _, data = collect_qemu(root, "aarch64", system="Linux")
            self.assertIn((str(root / "share/qemu"), "runtime/share/qemu"), data)
            self.assertIn((str(root / "share/AAVMF/AAVMF_CODE.fd"), "runtime/share/qemu"), data)
