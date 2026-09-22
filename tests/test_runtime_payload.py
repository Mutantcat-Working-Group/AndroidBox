from pathlib import Path
import tempfile
import unittest

from scripts.runtime_payload import collect_adb, collect_qemu, stage_images_disk
from androidbox.bundled import IMAGES_DISK


class RuntimePayloadTests(unittest.TestCase):
    def test_images_disk_is_staged_under_the_name_the_client_attaches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "androidbox-images-aarch64.raw"
            artifact.write_bytes(b"raw disk")
            staging = root / "build" / "bundled-images"
            source, destination = stage_images_disk(artifact, "aarch64", staging)
            # PyInstaller appends the source basename to the destination, and
            # the frozen client attaches runtime/images/ARCH/IMAGES_DISK.
            self.assertEqual(Path(source).name, IMAGES_DISK)
            self.assertEqual(destination, "runtime/images/aarch64")
            self.assertEqual(Path(source).parent, staging / "aarch64")
            self.assertEqual(Path(source).read_bytes(), b"raw disk")

    def test_staging_images_again_replaces_the_previous_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "androidbox-images-x86_64.raw"
            artifact.write_bytes(b"first")
            stage_images_disk(artifact, "x86_64", root / "build")
            artifact.write_bytes(b"second")
            source, _ = stage_images_disk(artifact, "x86_64", root / "build")
            self.assertEqual(Path(source).read_bytes(), b"second")

    def test_staging_rejects_an_unknown_guest_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "disk.raw"
            artifact.write_bytes(b"raw disk")
            with self.assertRaisesRegex(ValueError, "architecture"):
                stage_images_disk(artifact, "riscv64", Path(directory) / "build")

    def test_staging_reports_a_missing_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                stage_images_disk(Path(directory) / "absent.raw", "x86_64", Path(directory) / "build")

    def test_the_specifier_ships_the_disk_through_the_staging_helper(self):
        spec = (Path(__file__).resolve().parents[1] / "packaging/desktop.spec").read_text()
        self.assertIn("stage_images_disk(", spec)
        self.assertNotIn("androidbox-images.raw\"]", spec)

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

    def test_adb_collects_distribution_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "lib").mkdir()
            (root / "lib/android-libbase.so").touch()
            (root / "adb").touch()
            (root / "NOTICE.txt").touch()
            _, data = collect_adb(root, system="Linux")
            self.assertIn((str(root / "lib"), "runtime/lib"), data)

    def test_adb_without_libraries_stages_no_lib_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "adb").touch()
            (root / "NOTICE.txt").touch()
            _, data = collect_adb(root, system="Linux")
            self.assertEqual(data, [(str(root / "NOTICE.txt"), "licenses/adb")])

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
