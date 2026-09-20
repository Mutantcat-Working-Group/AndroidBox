import unittest

from androidbox.guestdisk import image_remote_name, managed_disk_name, normalize_arch, parse_sha256sums


class FetchGuestDiskTests(unittest.TestCase):
    def test_arch_aliases(self):
        self.assertEqual(normalize_arch("AMD64"), "x86_64")
        self.assertEqual(normalize_arch("arm64"), "aarch64")
        with self.assertRaises(ValueError):
            normalize_arch("riscv64")

    def test_asset_names_match_androidbox_discovery(self):
        self.assertEqual(image_remote_name("x86_64"), "ubuntu-24.04-minimal-cloudimg-amd64.img")
        self.assertEqual(image_remote_name("aarch64"), "ubuntu-24.04-minimal-cloudimg-arm64.img")
        self.assertEqual(managed_disk_name("x86_64"), "androidbox-x86_64.qcow2")
        self.assertEqual(managed_disk_name("aarch64"), "androidbox-aarch64.qcow2")

    def test_manifest_parser_accepts_and_rejects_lines(self):
        digest = "0" * 64
        parsed = parse_sha256sums(f"{digest} *ubuntu-24.04-minimal-cloudimg-amd64.img\n")
        self.assertEqual(parsed["ubuntu-24.04-minimal-cloudimg-amd64.img"], digest)
        parsed = parse_sha256sums(f"{digest}  ubuntu-24.04-minimal-cloudimg-arm64.img\n")
        self.assertEqual(parsed["ubuntu-24.04-minimal-cloudimg-arm64.img"], digest)
        with self.assertRaises(ValueError):
            parse_sha256sums("short  file.img")
        with self.assertRaises(ValueError):
            parse_sha256sums(f"{digest} one two")
        with self.assertRaises(ValueError):
            parse_sha256sums("")
