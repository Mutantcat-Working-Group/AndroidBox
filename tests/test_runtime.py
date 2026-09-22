import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from androidbox.runtime import (VMConfig, block_cache, build_command, choose_accelerator,
    normalize_arch, load_config, save_config, select_cpu, executable,
    display_quality_level, DISPLAY_QUALITY, QUALITY_LEVELS)


class RuntimeTests(unittest.TestCase):
    def test_qemu_discovery_without_shell_path(self):
        for system, target in [("Darwin", "/opt/homebrew/bin/qemu-system-aarch64"),
                               ("Windows", "C:/Program Files/qemu/qemu-system-aarch64.exe")]:
            with self.subTest(system=system), \
                    patch("androidbox.runtime.platform.system", return_value=system), \
                    patch.dict("os.environ", {"ProgramFiles": "C:/Program Files"}), \
                    patch("androidbox.runtime.shutil.which", side_effect=lambda value: value if value == target else None):
                self.assertEqual(executable(VMConfig(arch="aarch64")), target)

    def test_explicit_missing_qemu_does_not_fall_back(self):
        with patch("androidbox.runtime.shutil.which", side_effect=lambda value: None if value == "/missing/qemu" else value):
            with self.assertRaisesRegex(ValueError, "/missing/qemu"):
                executable(VMConfig(qemu="/missing/qemu"))

    def test_architectures(self):
        self.assertEqual(normalize_arch("AMD64"), "x86_64")
        self.assertEqual(normalize_arch("arm64"), "aarch64")
        with self.assertRaises(ValueError):
            normalize_arch("mips")

    def test_accelerators(self):
        for system, accelerator in [("Darwin", "hvf"), ("Windows", "whpx"), ("Linux", "kvm")]:
            self.assertEqual(choose_accelerator(system, "x86_64", "x86_64", {accelerator, "tcg"}), accelerator)
        self.assertEqual(choose_accelerator("Darwin", "arm64", "x86_64", {"hvf", "tcg"}), "tcg")
        self.assertEqual(choose_accelerator("Linux", "x86_64", "x86_64", {"tcg"}), "tcg")

    def test_command_is_local_only_and_disk_is_not_shell_interpolated(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk with spaces.qcow2"
            disk.touch()
            config = VMConfig(disk=str(disk))
            command = build_command(config, "qemu-system-x86_64", "tcg", 5907, 5908, 5909)
            self.assertIn("127.0.0.1:7,websocket=127.0.0.1:5909,password=on", command)
            self.assertIn("tcp:127.0.0.1:5908,server=on,wait=off", command)
            self.assertIn("-blockdev", command)
            block = json.loads(command[command.index("-blockdev") + 1])
            self.assertEqual(block["file"]["filename"], str(disk.resolve()))
            self.assertNotIn("shell", command)

    def test_cidata_seed_is_attached_when_present(self):
        from androidbox import seed as seed_module
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            seed_iso = seed_module.seed_path_for(disk)
            seed_module.write_iso(seed_iso, [("meta-data", b"instance-id: x\n"),
                                             ("user-data", b"#cloud-config\n")])
            command = build_command(VMConfig(disk=str(disk)), "qemu-system-x86_64", "tcg", 5907, 5908, 5909)
            blockdevs = [json.loads(command[index + 1]) for index, arg in enumerate(command) if arg == "-blockdev"]
            cidata = next(block for block in blockdevs if block.get("node-name") == "cidata")
            self.assertEqual(cidata["driver"], "raw")
            self.assertTrue(cidata["read-only"])
            self.assertEqual(cidata["file"]["filename"], str(seed_iso.resolve()))
            self.assertIn("virtio-blk-pci,drive=cidata,bootindex=1", command)
            self.assertIn("virtio-blk-pci,drive=os,bootindex=0", command)

    def test_missing_seed_leaves_no_cidata_device(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            command = build_command(VMConfig(disk=str(disk)), "qemu", "tcg", 5900, 6000, 6001)
            self.assertNotIn("cidata", " ".join(command))

    def test_arm_requires_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            with patch("androidbox.runtime.VMConfig.resolved_firmware", return_value=""), \
                    self.assertRaisesRegex(ValueError, "firmware"):
                build_command(VMConfig(disk=str(disk), arch="aarch64"), "qemu", "tcg", 5900, 6000, 6001)

    def test_single_firmware_compatible_display(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.raw"
            disk.touch()
            for arch, device in [("x86_64", "virtio-vga"), ("aarch64", "virtio-gpu-pci")]:
                with self.subTest(arch=arch):
                    command = build_command(VMConfig(disk=str(disk), arch=arch, firmware=str(disk)),
                                            "qemu", "tcg", 5900, 6000, 6001)
                    self.assertIn("-vga", command)
                    self.assertEqual(command[command.index("-vga") + 1], "none")
                    self.assertIn(device, command)

    def test_missing_disk_and_bad_resources(self):
        with self.assertRaises(ValueError):
            build_command(VMConfig(disk="/missing.qcow2"), "qemu", "tcg", 5900, 6000, 6001)
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            with self.assertRaises(ValueError):
                build_command(VMConfig(disk=str(disk), memory_mb=0), "qemu", "tcg", 5900, 6000, 6001)

    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = VMConfig(disk="/disk.qcow2", memory_mb=8192)
            save_config(config, path)
            self.assertEqual(load_config(path), config)
            path.write_text('{"memory_mb": "bad"}')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_invalid_field_types_are_validation_errors(self):
        for field in ("disk", "arch", "firmware", "qemu", "accelerator", "disk_format"):
            for value in (None, [], {}, 42):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    VMConfig(**{field: value}).validate(check_files=False)

    def test_cpu_model_selection(self):
        self.assertEqual(select_cpu("kvm", "auto"), "host")
        self.assertEqual(select_cpu("hvf", "auto"), "host")
        self.assertEqual(select_cpu("tcg", "auto"), "max")
        self.assertEqual(select_cpu("whpx", "auto"), "max")
        self.assertEqual(select_cpu("whpx", "host"), "max")
        self.assertEqual(select_cpu("hvf", "qemu64"), "qemu64")

    def test_disk_cache_values(self):
        self.assertIsNone(block_cache("writeback"))
        self.assertEqual(block_cache("none"), {"direct": True})
        self.assertEqual(block_cache("unsafe"), {"no-flush": True})

    def test_performance_options_reach_the_command(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            config = VMConfig(disk=str(disk), cpu_mode="qemu64", disk_cache="none", tcg_threads="multi")
            command = build_command(config, "qemu-system-x86_64", "tcg", 5900, 6000, 6001)
            self.assertEqual(command[command.index("-accel") + 1], "tcg,thread=multi")
            self.assertEqual(command[command.index("-cpu") + 1], "qemu64")
            block = json.loads(command[command.index("-blockdev") + 1])
            self.assertEqual(block["cache"], {"direct": True})
            for cache, expected in [("writeback", None), ("unsafe", {"no-flush": True}), ("none", {"direct": True})]:
                with self.subTest(cache=cache):
                    plain = build_command(VMConfig(disk=str(disk), disk_cache=cache), "qemu", "tcg", 5900, 6000, 6001)
                    block = json.loads(plain[plain.index("-blockdev") + 1])
                    self.assertEqual(block.get("cache"), expected)

    def test_hardware_acceleration_keeps_default_accel_property(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            command = build_command(VMConfig(disk=str(disk), tcg_threads="multi"), "qemu", "hvf", 5900, 6000, 6001)
            self.assertEqual(command[command.index("-accel") + 1], "hvf")

    def test_performance_options_are_validated(self):
        with self.assertRaisesRegex(ValueError, "CPU model"):
            VMConfig(cpu_mode="turbo").validate(check_files=False)
        with self.assertRaisesRegex(ValueError, "x86_64 CPU model"):
            VMConfig(arch="aarch64", cpu_mode="qemu64").validate(check_files=False)
        with self.assertRaisesRegex(ValueError, "disk cache"):
            VMConfig(disk_cache="magic").validate(check_files=False)
        with self.assertRaisesRegex(ValueError, "TCG thread"):
            VMConfig(tcg_threads="many").validate(check_files=False)
        with self.assertRaisesRegex(ValueError, "display quality"):
            VMConfig(display_quality="cinema").validate(check_files=False)

    def test_performance_options_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = VMConfig(disk="/disk.qcow2", cpu_mode="max", disk_cache="none",
                              tcg_threads="single", display_quality="responsive")
            save_config(config, path)
            self.assertEqual(load_config(path), config)

    def test_defaults_expose_performance_settings(self):
        config = VMConfig()
        self.assertEqual((config.cpu_mode, config.disk_cache, config.tcg_threads,
                          config.display_quality), ("auto", "writeback", "auto", "balanced"))

    def test_display_quality_levels_cover_the_whole_range(self):
        self.assertEqual(set(QUALITY_LEVELS), set(DISPLAY_QUALITY))
        for name, level in QUALITY_LEVELS.items():
            self.assertIsInstance(level, int)
            self.assertTrue(0 <= level <= 9)
        self.assertEqual(display_quality_level("responsive"), 3)
        self.assertEqual(display_quality_level("sharp"), 9)
        with self.assertRaises(ValueError):
            display_quality_level("cinema")


if __name__ == "__main__":
    unittest.main()
