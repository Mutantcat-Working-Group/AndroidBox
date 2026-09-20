import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from androidbox import runtime


class DefaultConfigTests(unittest.TestCase):
    def test_first_launch_uses_host_resources_and_managed_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "guests/androidbox-aarch64.qcow2"
            disk.parent.mkdir()
            disk.write_bytes(b"QFI\xfb")
            with patch.object(runtime, "state_directory", return_value=root), \
                    patch.object(runtime.platform, "machine", return_value="arm64"), \
                    patch.object(runtime.os, "cpu_count", return_value=6), \
                    patch.object(runtime, "host_memory_mb", return_value=6144):
                config = runtime.load_config()
            self.assertEqual(config.arch, "aarch64")
            self.assertEqual(config.cpus, 3)
            self.assertEqual(config.memory_mb, 3072)
            self.assertEqual(config.disk, str(disk))

    def test_saved_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            saved = runtime.VMConfig(disk="/chosen.raw", disk_format="raw", cpus=7, memory_mb=5120,
                                     qemu="/chosen/qemu", firmware="/chosen/firmware", accelerator="tcg")
            runtime.save_config(saved, path)
            self.assertEqual(runtime.load_config(path), saved)

    def test_unreadable_managed_disk_does_not_block_first_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "guests/androidbox-aarch64.qcow2"
            disk.parent.mkdir()
            disk.touch()
            with patch.object(runtime, "state_directory", return_value=root), \
                    patch.object(runtime.platform, "machine", return_value="arm64"), \
                    patch.object(runtime, "disk_format", side_effect=PermissionError("unreadable disk")):
                self.assertEqual(runtime.load_config().disk, "")

    def test_partial_settings_use_native_arch_and_resource_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"disk": "/chosen.raw", "disk_format": "raw"}))
            with patch.object(runtime.platform, "machine", return_value="arm64"), \
                    patch.object(runtime.os, "cpu_count", return_value=2), \
                    patch.object(runtime, "host_memory_mb", return_value=4096):
                config = runtime.load_config(path)
            self.assertEqual((config.arch, config.cpus, config.memory_mb), ("aarch64", 1, 2048))
            self.assertEqual(config.disk, "/chosen.raw")

    def test_resource_defaults_are_bounded(self):
        for cores, memory, expected in [(None, None, (2, 2048)), (1, 2048, (1, 1024)), (128, 131072, (4, 4096))]:
            with self.subTest(cores=cores), patch.object(runtime.os, "cpu_count", return_value=cores), \
                    patch.object(runtime, "host_memory_mb", return_value=memory):
                config = runtime.default_config()
                self.assertEqual((config.cpus, config.memory_mb), expected)

    def test_disk_format_uses_header_not_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.img"
            path.write_bytes(b"QFI\xfb\x00\x00\x00\x03")
            self.assertEqual(runtime.disk_format(path), "qcow2")
            path.write_bytes(b"\x00" * 8)
            self.assertEqual(runtime.disk_format(path), "raw")

    def test_firmware_next_to_external_qemu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "share/qemu/edk2-aarch64-code.fd"
            firmware.parent.mkdir(parents=True)
            firmware.touch()
            config = runtime.VMConfig(arch="aarch64", qemu=str(root / "bin/qemu-system-aarch64"))
            self.assertEqual(config.resolved_firmware(), str(firmware))

    def test_explicit_firmware_is_preserved(self):
        self.assertEqual(runtime.VMConfig(arch="aarch64", firmware="/chosen.fd").resolved_firmware(), "/chosen.fd")
