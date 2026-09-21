import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from androidbox import seed


class SeedTests(unittest.TestCase):
    def test_seed_path_sits_next_to_the_guest_disk(self):
        self.assertEqual(
            seed.seed_path_for("/data/guests/androidbox-aarch64.qcow2"),
            Path("/data/guests/androidbox-aarch64-seed.iso"),
        )
        self.assertEqual(seed.seed_path_for("disk.raw").name, "disk-seed.iso")

    def test_write_seed_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "androidbox-x86_64.qcow2"
            disk.write_bytes(b"QFI\xfb")
            path = seed.write_seed(seed.seed_path_for(disk), "x86_64")
            label, files = seed.read_iso(path)
            self.assertEqual(label, seed.SEED_LABEL)
            self.assertEqual(set(files), {"META-DATA", "USER-DATA",
                                          seed.PAYLOAD_ARCHIVE.upper(),
                                          seed.VERSION_FILE.upper()})
            self.assertEqual(seed.seed_version(path), seed.__version__)
            self.assertIn("instance-id: androidbox-x86_64", files["META-DATA"].decode("utf-8"))
            user_data = files["USER-DATA"].decode("utf-8")
            self.assertIn("#cloud-config", user_data)
            self.assertIn("--autologin ubuntu", user_data)
            self.assertTrue(files[seed.PAYLOAD_ARCHIVE.upper()])

    def test_payload_archive_contains_the_provisioner(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = seed.write_payload_archive(Path(directory) / seed.PAYLOAD_ARCHIVE)
            with archive.open("rb") as stream, tarfile.open(fileobj=stream, mode="r:gz") as tar:
                names = tar.getnames()
        self.assertIn("androidbox/guest/provision.sh", names)
        self.assertIn("androidbox/Makefile", names)
        self.assertTrue(any(name.startswith("androidbox/tools/") for name in names))

    def test_write_payload_archive_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first = seed.write_payload_archive(Path(directory) / "a.tar.gz")
            second = seed.write_payload_archive(Path(directory) / "b.tar.gz")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_ensure_seed_is_idempotent_and_refreshes_on_new_version(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "androidbox-aarch64.qcow2"
            disk.write_bytes(b"QFI\xfb")
            path = seed.seed_path_for(disk)
            first = seed.ensure_seed(path, "aarch64")
            second = seed.ensure_seed(path, "aarch64")
            self.assertEqual(first, second)
            seed.write_seed(path, "aarch64", version="1.0.0")
            self.assertEqual(seed.seed_version(path), "1.0.0")
            refreshed = seed.ensure_seed(path, "aarch64")
            self.assertEqual(seed.seed_version(refreshed), seed.__version__)

    def test_read_iso_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.iso"
            path.write_bytes(b"\0" * 2048)
            with self.assertRaises(ValueError):
                seed.read_iso(path)
            self.assertIsNone(seed.seed_version(path))

    def test_user_data_documents_the_default_password(self):
        user_data = seed.user_data()
        self.assertIn("name: ubuntu", user_data)
        self.assertIn(f"password: {seed.DEFAULT_PASSWORD}", user_data)
        self.assertIn(f"echo 'ubuntu:{seed.DEFAULT_PASSWORD}' | chpasswd", user_data)

    def test_indent_keeps_block_scalar_line_structure(self):
        self.assertEqual(seed._indent("line one\n\n  indented\nline four", 6),
                         "      line one\n\n        indented\n      line four")

    def test_user_data_firstboot_script_survives_parsing(self):
        import yaml
        config = yaml.safe_load(seed.user_data())
        entries = {entry["path"]: entry["content"] for entry in config["write_files"]}
        firstboot = entries["/usr/local/bin/androidbox-firstboot"]
        self.assertTrue(firstboot.startswith("#!/bin/bash\n"))
        self.assertIn("\n", firstboot)
        self.assertIn('echo_progress "AndroidBox first boot: starting provisioning..."\n',
                      firstboot)
        self.assertIn("bash /opt/androidbox-src/androidbox/guest/provision.sh "
                      "--dedicated-guest", firstboot)
        self.assertIn("/usr/local/bin/androidbox-firstboot", config["runcmd"][-1])


if __name__ == "__main__":
    unittest.main()
