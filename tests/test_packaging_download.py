import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import fetch_appimagetool


class PackagingDownloadTests(unittest.TestCase):
    def test_verified_download_is_installed_atomically(self):
        payload = b"packaging tool fixture"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool.AppImage"
            with patch.object(fetch_appimagetool, "SHA256", hashlib.sha256(payload).hexdigest()), \
                    patch.object(fetch_appimagetool.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
                fetch_appimagetool.fetch(target)
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(target.with_suffix(".download").exists())

    def test_bad_checksum_preserves_existing_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool.AppImage"
            target.write_bytes(b"existing")
            with patch.object(fetch_appimagetool.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt")):
                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    fetch_appimagetool.fetch(target)
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertFalse(target.with_suffix(".download").exists())
