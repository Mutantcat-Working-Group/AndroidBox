from pathlib import Path
import json
import platform
import tempfile
import unittest
from unittest.mock import patch

from androidbox import bundled
from androidbox.runtime import VMConfig, build_command, executable, normalize_arch
from androidbox.adb import executable as adb_executable


class BundledRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = patch("sys._MEIPASS", str(self.root), create=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.frozen = patch("sys.frozen", True, create=True)
        self.frozen.start()
        self.addCleanup(self.frozen.stop)
        self.binary = self.root / "runtime/bin/qemu-system-aarch64"
        self.binary.parent.mkdir(parents=True)
        self.binary.touch()
        self.binary.chmod(0o755)
        self.firmware = self.root / "runtime/share/qemu/edk2-aarch64-code.fd"
        self.firmware.parent.mkdir(parents=True)
        self.firmware.touch()
        self.disk = self.root / "test.raw"
        self.disk.touch()

    def test_bundled_qemu_precedes_path(self):
        with patch("androidbox.runtime.platform.system", return_value="Darwin"):
            self.assertEqual(executable(VMConfig(arch="aarch64")), str(self.binary))

    def test_bundled_adb_precedes_path(self):
        adb = self.binary.parent / "adb"
        adb.touch()
        with patch("androidbox.bundled.platform.system", return_value="Darwin"), \
                patch("androidbox.adb.shutil.which", return_value="/system/adb"):
            self.assertEqual(adb_executable(), str(adb))

    def test_adb_falls_back_to_system(self):
        with patch("androidbox.adb.shutil.which", return_value="/system/adb"):
            self.assertEqual(adb_executable(), "/system/adb")

    def test_explicit_binary_still_wins(self):
        with patch("androidbox.runtime.shutil.which", return_value="/custom/qemu"):
            self.assertEqual(executable(VMConfig(qemu="/custom/qemu")), "/custom/qemu")

    def test_bundled_arm_firmware_and_data_are_automatic(self):
        config = VMConfig(disk=str(self.disk), arch="aarch64", disk_format="raw")
        command = build_command(config, str(self.binary), "tcg", 5900, 5901, 5902)
        self.assertEqual(command[command.index("-bios") + 1], str(self.firmware.resolve()))
        self.assertEqual(command[command.index("-L") + 1], str(self.firmware.parent))
        self.assertEqual(config.firmware, "")

    def test_external_qemu_does_not_inherit_bundled_data(self):
        config = VMConfig(disk=str(self.disk), firmware=str(self.firmware))
        command = build_command(config, "/custom/qemu", "tcg", 5900, 5901, 5902)
        self.assertNotIn("-L", command)

    def test_bundled_guest_images_are_attached_read_only(self):
        images = self.root / "runtime/images/aarch64/androidbox-images.raw"
        images.parent.mkdir(parents=True)
        images.write_bytes(b"\x00" * 1024)
        self.assertEqual(bundled.images_disk("aarch64"), str(images))
        # A guest of another architecture never sees the foreign image disk.
        self.assertIsNone(bundled.images_disk("x86_64"))
        config = VMConfig(disk=str(self.disk), arch="aarch64", disk_format="raw")
        command = build_command(config, str(self.binary), "tcg", 5900, 5901, 5902)
        marker = "virtio-blk-pci,drive=androidbox-images,bootindex=2"
        self.assertIn(marker, command)
        device = command.index(marker)
        self.assertEqual(command[device - 3], "-blockdev")
        self.assertEqual(command[device - 1], "-device")
        blockdev = json.loads(command[device - 2])
        self.assertIs(blockdev["read-only"], True)
        self.assertEqual(blockdev["file"]["filename"], str(images.resolve()))

    def test_verify_images_requires_the_bundled_disk(self):
        with self.assertRaisesRegex(ValueError, "Missing bundled Android image disk"):
            bundled.verify_images()

    def test_verify_images_describes_the_bundled_disk(self):
        arch = normalize_arch(platform.machine())
        images = self.root / "runtime/images" / arch / bundled.IMAGES_DISK
        images.parent.mkdir(parents=True)
        images.write_bytes(b"\x00" * 2048)
        described = bundled.verify_images()
        self.assertEqual(described["arch"], arch)
        self.assertEqual(described["path"], str(images))
        self.assertEqual(described["bytes"], 2048)

    def test_source_checkout_does_not_use_meipass(self):
        with patch("sys.frozen", False), patch("androidbox.runtime.shutil.which", return_value="/system/qemu"):
            self.assertEqual(executable(VMConfig()), "/system/qemu")
