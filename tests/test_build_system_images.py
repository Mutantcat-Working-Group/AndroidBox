import io
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_system_images


class SystemImageStagingTests(unittest.TestCase):
    def setUp(self):
        self.system = {
            "datetime": 1775194047,
            "filename": "lineage-20.0-20260403-VANILLA-waydroid_arm64_only-system.zip",
            "id": "a" * 64,
            "url": "https://example.invalid/system.zip",
            "version": "20.0",
        }
        self.vendor = {
            "datetime": 1775198504,
            "filename": "lineage-20.0-20260403-MAINLINE-waydroid_arm64_only-vendor.zip",
            "id": "b" * 64,
            "url": "https://example.invalid/vendor.zip",
            "version": "20.0",
        }

    def _channel(self, _arch, component):
        return self.system if component == "system" else self.vendor

    def _payloads(self):
        return {"https://example.invalid/system.zip": b"system archive",
                "https://example.invalid/vendor.zip": b"vendor archive"}

    def _download(self, payloads):
        def download(entry, target):
            Path(target).write_bytes(payloads[entry["url"]])
            # The real download() hands back the archive path, never the entry.
            return target
        return download

    def test_stage_verifies_and_describes_the_archives(self):
        payloads = self._payloads()
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            with patch.object(build_system_images, "read_channel",
                              side_effect=self._channel), \
                    patch.object(build_system_images, "download",
                                 side_effect=self._download(payloads)) as download:
                entries = build_system_images.stage("aarch64", staging)
            self.assertEqual(download.call_count, 2)
            self.assertEqual((staging / "system.zip").read_bytes(), b"system archive")
            self.assertEqual((staging / "vendor.zip").read_bytes(), b"vendor archive")
            self.assertEqual((staging / "SHA256SUMS").read_text(encoding="utf-8"),
                             f"{'a' * 64}  system.zip\n{'b' * 64}  vendor.zip\n")
            manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["arch"], "aarch64")
            self.assertEqual(manifest["ota_arch"], "arm64_only")
            self.assertEqual(manifest["images"]["system"]["datetime"], 1775194047)
            self.assertEqual(manifest["images"]["vendor"]["filename"], self.vendor["filename"])
            self.assertEqual(entries["vendor"]["id"], "b" * 64)

    def test_stage_stops_before_an_unverified_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            with patch.object(build_system_images, "read_channel",
                              side_effect=self._channel), \
                    patch.object(build_system_images, "download",
                                 side_effect=ValueError("corrupted")):
                with self.assertRaisesRegex(ValueError, "corrupted"):
                    build_system_images.stage("x86_64", staging)
            self.assertFalse((staging / "system.zip").exists())
            self.assertFalse((staging / "vendor.zip").exists())
            self.assertFalse((staging / "SHA256SUMS").exists())

    def test_stage_keeps_the_channel_entry_after_the_download(self):
        # download() returns the archive path. Staging that value used to turn
        # every checksum and manifest field into a PosixPath, which the guest
        # cannot verify, so the entry has to be captured separately.
        payloads = self._payloads()

        def download(entry, target):
            Path(target).write_bytes(payloads[entry["url"]])
            return target

        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            with patch.object(build_system_images, "read_channel",
                              side_effect=self._channel), \
                    patch.object(build_system_images, "download", side_effect=download):
                entries = build_system_images.stage("x86_64", staging)
            self.assertEqual(entries["system"]["id"], "a" * 64)
            self.assertEqual((staging / "SHA256SUMS").read_text(encoding="utf-8"),
                             f"{'a' * 64}  system.zip\n{'b' * 64}  vendor.zip\n")
            manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["ota_arch"], "x86_64")
            self.assertEqual(manifest["images"]["vendor"]["sha256"], "b" * 64)

    def test_read_channel_picks_the_newest_entry(self):
        older = dict(self.system, datetime=1, id="c" * 64)
        document = io.BytesIO(json.dumps({"response": [older, self.system]}).encode("utf-8"))
        with patch.object(build_system_images.urllib.request, "urlopen",
                          return_value=document):
            entry = build_system_images.read_channel("aarch64", "system")
        self.assertEqual(entry["id"], "a" * 64)

    def test_read_channel_rejects_an_empty_channel(self):
        document = io.BytesIO(json.dumps({"response": []}).encode("utf-8"))
        with patch.object(build_system_images.urllib.request, "urlopen",
                          return_value=document):
            with self.assertRaisesRegex(ValueError, "publishes no images"):
                build_system_images.read_channel("x86_64", "vendor")

    def test_architecture_maps_to_the_published_ota_channel(self):
        self.assertIn("waydroid_arm64_only", build_system_images.ota_url("aarch64", "system"))
        self.assertIn("waydroid_x86_64", build_system_images.ota_url("x86_64", "vendor"))
        self.assertIn("VANILLA.json", build_system_images.ota_url("x86_64", "system"))
        self.assertIn("MAINLINE.json", build_system_images.ota_url("aarch64", "vendor"))
        with self.assertRaisesRegex(ValueError, "No Android OTA channel"):
            build_system_images.ota_url("riscv64", "system")
        with self.assertRaisesRegex(ValueError, "Unknown Android image component"):
            build_system_images.ota_url("x86_64", "kernel")

    def test_download_rejects_a_mismatched_digest(self):
        entry = {"filename": "system.zip", "id": "d" * 64,
                 "url": "https://example.invalid/system.zip"}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system.zip"
            with patch.object(build_system_images.urllib.request, "urlopen",
                              return_value=io.BytesIO(b"tampered")):
                with self.assertRaisesRegex(ValueError, "does not match its published SHA256"):
                    build_system_images.download(entry, target)
            self.assertFalse(target.exists())
            self.assertFalse((Path(directory) / "system.zip.part").exists())

    def test_download_accepts_the_published_digest(self):
        entry = {"filename": "system.zip",
                 "id": "1bfefc79b77185639257480b7bd91ec719430531d457075317d5e10dcb655f1d",
                 "url": "https://example.invalid/system.zip"}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system.zip"
            with patch.object(build_system_images.urllib.request, "urlopen",
                             return_value=io.BytesIO(b"trusted archive")):
                self.assertEqual(build_system_images.download(entry, target), target)
            self.assertEqual(target.read_bytes(), b"trusted archive")

    def test_build_packs_the_disk_and_cleans_the_staging_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out" / "androidbox-images.raw"
            with patch.object(build_system_images, "stage",
                              side_effect=lambda component, target: (
                                  Path(target).mkdir(parents=True),
                                  (Path(target) / "system.zip").write_bytes(b"x"),
                                  Path(target))[2]), \
                    patch.object(build_system_images, "build_disk",
                                 side_effect=lambda source, target, label=None: (
                                     output.write_bytes(b"disk"), output)[1]) as packed:
                disk = build_system_images.build("aarch64", output)
            self.assertIs(disk, output)
            self.assertEqual(output.read_bytes(), b"disk")
            # The default working directory sits beside the disk, per architecture.
            self.assertEqual(Path(packed.call_args[0][0]), root / "out" / "images-aarch64")
            self.assertFalse((root / "out" / "images-aarch64").exists())

    def test_disk_size_reserves_room_for_ext4_overhead(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "system.zip").write_bytes(b"x" * 100000)
            self.assertGreater(build_system_images.filesystem_size(directory),
                               100000 + 4096 + 64 * 1024 * 1024)

    def test_a_staged_disk_unpacks_like_the_guest_expects(self):
        # provision.sh verifies SHA256SUMS relative to the mount point before it
        # unzips system.zip and vendor.zip beside it.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("system.img", b"raw system image")
        payloads = {"https://example.invalid/system.zip": buffer.getvalue(),
                    "https://example.invalid/vendor.zip": b"vendor"}
        system, vendor = dict(self.system), dict(self.vendor)
        for entry in (system, vendor):
            entry["id"] = hashlib.sha256(payloads[entry["url"]]).hexdigest()
        def channel(_arch, component):
            return system if component == "system" else vendor
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            with patch.object(build_system_images, "read_channel",
                              side_effect=channel), \
                    patch.object(build_system_images, "download",
                                 side_effect=self._download(payloads)):
                build_system_images.stage("x86_64", staging)
            verified = subprocess.run(["sha256sum", "--status", "-c", "SHA256SUMS"], cwd=staging)
            self.assertEqual(verified.returncode, 0)
            with zipfile.ZipFile(staging / "system.zip") as archive:
                self.assertEqual(archive.namelist(), ["system.img"])


if __name__ == "__main__":
    unittest.main()
