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
                                         "NETWORK-CONFIG",
                                         seed.PAYLOAD_ARCHIVE.upper(),
                                         seed.VERSION_FILE.upper()})
            # The version line also carries a payload fingerprint, so two
            # builds that share a version number are still told apart.
            stamp = seed.seed_version(path)
            self.assertTrue(stamp.startswith(f"{seed.__version__}-"), stamp)
            self.assertEqual(seed.seed_matches(path, "x86_64"), True)
            # The instance-id carries the seed version so cloud-init re-runs
            # its per-instance modules whenever the seed changes.
            self.assertIn(f"instance-id: androidbox-x86_64-{stamp}",
                          files["META-DATA"].decode("utf-8"))
            user_data = files["USER-DATA"].decode("utf-8")
            self.assertIn("#cloud-config", user_data)
            self.assertIn("--autologin ubuntu", user_data)
            network = files["NETWORK-CONFIG"].decode("utf-8")
            self.assertIn("dhcp4: true", network)
            self.assertIn("name: e*", network)
            self.assertTrue(files[seed.PAYLOAD_ARCHIVE.upper()])

    def test_network_config_matches_every_virtio_ethernet_card(self):
        network = seed.network_config()
        self.assertIn("version: 2", network)
        self.assertIn("ethernets:", network)
        self.assertIn("match:", network)
        self.assertIn("name: e*", network)
        self.assertIn("dhcp4: true", network)
        self.assertIn("dhcp6: false", network)

    def test_network_config_never_blocks_boot_on_a_missing_lease(self):
        # Without optional: true, systemd-networkd-wait-online has no timeout to
        # fall back on and every boot sat at "Job .../start running" for minutes.
        network = seed.network_config()
        self.assertIn("optional: true", network)
        self.assertNotIn("critical: true", network)

    def test_network_config_carries_a_nameserver_for_the_android_container(self):
        # The Android container resolves names through this host, so a lease with
        # no DNS server leaves it with ERR_NAME_NOT_RESOLVED in every app.
        network = seed.network_config()
        self.assertIn("nameservers:", network)
        self.assertIn("10.0.2.3", network)  # QEMU user-mode resolver
        self.assertIn("use-dns: false", network)  # ignore a lease without one

    def test_write_seed_changes_instance_id_with_version(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "androidbox-aarch64.qcow2"
            disk.write_bytes(b"QFI\xfb")
            path = seed.seed_path_for(disk)
            seed.write_seed(path, "aarch64")
            label, files = seed.read_iso(path)
            first = files["META-DATA"].decode("utf-8")
            self.assertIn(f"instance-id: androidbox-aarch64-{seed.__version__}", first)
            seed.write_seed(path, "aarch64", version="1.0.1")
            _, files = seed.read_iso(path)
            self.assertIn("instance-id: androidbox-aarch64-1.0.1",
                          files["META-DATA"].decode("utf-8"))

    def test_payload_archive_contains_the_provisioner(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = seed.write_payload_archive(Path(directory) / seed.PAYLOAD_ARCHIVE)
            with archive.open("rb") as stream, tarfile.open(fileobj=stream, mode="r:gz") as tar:
                names = tar.getnames()
        self.assertIn("androidbox/guest/provision.sh", names)
        self.assertIn("androidbox/guest/net-portal.py", names)
        self.assertIn("androidbox/guest/net-portal.service", names)
        self.assertIn("androidbox/Makefile", names)
        self.assertIn("androidbox/guest/vendor/libglibutil/Makefile", names)
        self.assertIn("androidbox/guest/vendor/libgbinder/Makefile", names)
        self.assertIn("androidbox/guest/vendor/python-gbinder/setup.py", names)
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
            self.assertTrue(seed.seed_version(path).startswith("1.0.0-"))
            refreshed = seed.ensure_seed(path, "aarch64")
            self.assertTrue(seed.seed_version(refreshed).startswith(f"{seed.__version__}-"))

    def test_ensure_seed_refreshes_a_same_version_seed_with_a_different_payload(self):
        # This is the failure that shipped: an installer and a guest disk could
        # carry the same version number while the payload differed - one had
        # the camera provider, the other did not - and the seed was trusted as
        # current, so the provider never reached the guest.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "payload"
            (root / "guest").mkdir(parents=True)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            for entry in ("androidbox.py", "androidbox", "data", "tools",
                          "dbus", "systemd"):
                (root / entry).mkdir()
            (root / "guest" / "provision.sh").write_text("echo old\n", encoding="utf-8")

            path = Path(directory) / "androidbox-aarch64-seed.iso"
            seed.write_seed(path, "aarch64", root=root)
            self.assertTrue(seed.seed_matches(path, "aarch64", root=root))

            # Same application version, different payload.
            (root / "guest" / "provision.sh").write_text("echo new\n", encoding="utf-8")
            self.assertFalse(seed.seed_matches(path, "aarch64", root=root))

            refreshed = seed.ensure_seed(path, "aarch64", root=root)
            self.assertTrue(seed.seed_matches(refreshed, "aarch64", root=root))

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
        # Reproduce cloud-init's literal-block rules without importing a YAML
        # parser: every content line carries the indent, blank lines are blank.
        lines = self.user_data_lines()
        self.assertEqual(self.content_of(lines, "/usr/local/bin/androidbox-firstboot"),
                         seed.firstboot_script())
        runcmd = self.runcmd_items(lines)
        self.assertEqual(runcmd, ["[ systemctl, daemon-reload ]",
                                  "[ systemctl, restart, getty@tty1.service ]",
                                  "[ systemctl, enable, --now, androidbox-firstboot.service ]"])
        unit = self.content_of(lines, "/etc/systemd/system/androidbox-firstboot.service")
        self.assertIn("ConditionPathExists=!/var/lib/androidbox/.provisioned-", unit)
        # A bare marker would freeze an old first-boot result on disks that
        # already booted, so the version has to reach the unit condition.
        self.assertNotIn("ConditionPathExists=!/var/lib/androidbox/.provisioned\n", unit)
        self.assertIn("ExecStart=/usr/local/bin/androidbox-firstboot", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    @staticmethod
    def content_of(lines, path):
        entry = next(i for i, line in enumerate(lines)
                     if line == f"  - path: {path}")
        scalar = next(i for i in range(entry, len(lines))
                      if lines[i].strip() == "content: |")
        block = []
        for line in lines[scalar + 1:]:
            if line.strip() and not line.startswith(" " * 6):
                break
            block.append(line[6:] if line else "")
        # Clip chomping: the final line break survives, trailing empty lines
        # are not part of the scalar.
        while block and not block[-1]:
            block.pop()
        return "\n".join(block) + "\n"

    @staticmethod
    def user_data_lines():
        return seed.user_data().splitlines()

    @staticmethod
    def runcmd_items(lines):
        items = []
        for line in lines[lines.index("runcmd:") + 1:]:
            if line.strip() and not line.startswith("  "):
                break
            if line.startswith("  - "):
                items.append(line[4:].strip())
        return items


if __name__ == "__main__":
    unittest.main()
