import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import fetch_appimagetool, fetch_platform_tools


class PackagingDownloadTests(unittest.TestCase):
    def test_verified_download_is_installed_atomically(self):
        payload = b"packaging tool fixture"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool.AppImage"
            expected = hashlib.sha256(payload).hexdigest()
            with patch.dict(fetch_appimagetool.PINNED_SHA256, {"x86_64": expected}), \
                    patch.object(fetch_appimagetool.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
                fetch_appimagetool.fetch(target, arch="x86_64")
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(target.with_suffix(".download").exists())

    def test_bad_checksum_preserves_existing_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool.AppImage"
            target.write_bytes(b"existing")
            expected = hashlib.sha256(b"packaging tool fixture").hexdigest()
            with patch.dict(fetch_appimagetool.PINNED_SHA256, {"x86_64": expected}), \
                    patch.object(fetch_appimagetool.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt")):
                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    fetch_appimagetool.fetch(target, arch="x86_64")
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertFalse(target.with_suffix(".download").exists())

    def test_appimagetool_publishes_per_arch_release_assets(self):
        self.assertEqual(fetch_appimagetool.asset("x86_64"), "appimagetool-x86_64.AppImage")
        self.assertEqual(fetch_appimagetool.asset("aarch64"), "appimagetool-aarch64.AppImage")
        self.assertIn("appimagetool-aarch64.AppImage", fetch_appimagetool.url("aarch64"))
        self.assertEqual(set(fetch_appimagetool.PINNED_SHA256), {"x86_64", "aarch64"})

    def test_fetch_rejects_unknown_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool.AppImage"
            with self.assertRaisesRegex(ValueError, "Unsupported AppImageTool architecture"):
                fetch_appimagetool.fetch(target, arch="sparc64")
            self.assertFalse(target.exists())

    def test_platform_tools_are_extracted_and_verified(self):
        payload = self._platform_tools_zip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "platform-tools.zip"
            archive.write_bytes(payload)
            target = root / "platform-tools"
            expected = {
                "name": "fixture.zip",
                "sha1": hashlib.sha1(payload).hexdigest(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            with patch.object(fetch_platform_tools, "ARCHIVES", {"Darwin": expected}), \
                    patch.object(fetch_platform_tools.platform, "system", return_value="Darwin"):
                fetch_platform_tools.install(target, archive=archive)
            self.assertTrue((target / "adb").is_file())
            if os.name != "nt":
                self.assertEqual((target / "adb").stat().st_mode & 0o111, 0o111)

    def test_platform_tools_bad_checksum_preserves_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "platform-tools.zip"
            archive.write_bytes(b"corrupt")
            target = root / "platform-tools"
            target.mkdir()
            (target / "keep").write_text("existing")
            expected = {"name": "fixture.zip", "sha1": "0" * 40, "sha256": "0" * 64}
            with patch.object(fetch_platform_tools, "ARCHIVES", {"Darwin": expected}), \
                    patch.object(fetch_platform_tools.platform, "system", return_value="Darwin"):
                with self.assertRaisesRegex(ValueError, "SHA1 mismatch"):
                    fetch_platform_tools.install(target, archive=archive)
            self.assertEqual((target / "keep").read_text(), "existing")

    def test_platform_tools_missing_notice_preserves_target(self):
        payload = self._platform_tools_zip(include_notice=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "platform-tools.zip"
            archive.write_bytes(payload)
            target = root / "platform-tools"
            target.mkdir()
            (target / "keep").write_text("existing")
            expected = {
                "name": "fixture.zip",
                "sha1": hashlib.sha1(payload).hexdigest(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            with patch.object(fetch_platform_tools, "ARCHIVES", {"Darwin": expected}), \
                    patch.object(fetch_platform_tools.platform, "system", return_value="Darwin"):
                with self.assertRaisesRegex(ValueError, "NOTICE.txt"):
                    fetch_platform_tools.install(target, archive=archive)
            self.assertEqual((target / "keep").read_text(), "existing")

    def _platform_tools_zip(self, include_notice=True):
        from zipfile import ZipFile, ZipInfo

        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as archive:
            names = ["platform-tools/", "platform-tools/adb"]
            if include_notice:
                names.append("platform-tools/NOTICE.txt")
            for name in names:
                info = ZipInfo(name)
                info.external_attr = 0o100755 << 16
                archive.writestr(info, b"adb" if name.endswith("adb") else b"")
        return buffer.getvalue()
