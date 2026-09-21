import tempfile
import unittest
from pathlib import Path

from scripts.release_metadata import artifact_names, collect_checksums, validate_versions, windows_version


ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_nsis_uninstall_commands_quote_paths_with_spaces(self):
        installer = (ROOT / "packaging/windows.nsi").read_text(encoding="utf-8")
        self.assertIn("'\"$INSTDIR\\Uninstall.exe\"'", installer)
        self.assertIn("'\"$INSTDIR\\Uninstall.exe\" /S'", installer)

    def test_source_versions_match_requested_release(self):
        self.assertEqual(validate_versions(ROOT, "v1.0.20260922"), "1.0.20260922")

    def test_mismatched_or_unsafe_tag_is_rejected(self):
        for tag in ("v1.0.20260919", "1.0.20260920", "v1.0.20260920;echo bad"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate_versions(ROOT, tag)

    def test_windows_date_version_fits_pe_fields(self):
        self.assertEqual(windows_version("1.0.20260919"), (1, 0, 2026, 919))
        for value in ("1.0.20260230", "65536.0.20260919", "1.0.3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                windows_version(value)

    def test_checksums_require_all_installers_and_tar_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = artifact_names("1.0.20260919")
            self.assertEqual(len(names), 10)
            with self.assertRaises(ValueError):
                collect_checksums(root, "1.0.20260919")
            for name in names:
                (root / name).write_bytes(b"abc")
            text = collect_checksums(root, "1.0.20260919")
            self.assertEqual(len(text.splitlines()), 10)
            self.assertIn("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", text)
            (root / names[0]).write_bytes(b"")
            with self.assertRaises(ValueError):
                collect_checksums(root, "1.0.20260919")

    def test_unexpected_release_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in artifact_names("1.0.20260919"):
                (root / name).write_bytes(b"abc")
            (root / "surprise.exe").write_bytes(b"abc")
            with self.assertRaises(ValueError):
                collect_checksums(root, "1.0.20260919")
