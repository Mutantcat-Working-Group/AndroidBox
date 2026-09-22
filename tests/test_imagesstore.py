from pathlib import Path
import tempfile
import unittest

from androidbox import imagesstore


class ImageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installer = self.root / "AndroidBox-Setup.exe"
        self.installer.write_bytes(b"MZ" + b"\x00" * 8192)
        self.raw = self.root / "androidbox-images.raw"
        self.raw.write_bytes(b"guest image disk" * 1024)

    def attached(self, *sizes):
        imagesstore.append(self.installer, self.raw)
        return imagesstore.locate(self.installer)

    def test_an_installer_without_an_attached_disk(self):
        self.assertIsNone(imagesstore.locate(self.installer))

    def test_a_file_too_short_to_hold_a_trailer(self):
        stub = self.root / "stub.exe"
        stub.write_bytes(b"MZ")
        self.assertIsNone(imagesstore.locate(stub))

    def test_append_leaves_the_installer_bytes_intact(self):
        before = self.installer.read_bytes()
        offset, _, _ = self.attached()
        self.assertEqual(self.installer.read_bytes()[:len(before)], before)
        self.assertGreaterEqual(offset, len(before))

    def test_the_attached_disk_round_trips(self):
        _, length, raw_size = self.attached()
        self.assertEqual(raw_size, self.raw.stat().st_size)
        self.assertLess(length, raw_size)
        target = self.root / "expanded.raw"
        self.assertEqual(imagesstore.extract(self.installer, target).read_bytes(), self.raw.read_bytes())
        self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_extraction_reports_progress_against_the_expanded_size(self):
        _, _, raw_size = self.attached()
        seen = []
        imagesstore.extract(self.installer, self.root / "expanded.raw",
                            progress=lambda received, total: seen.append((received, total)))
        self.assertTrue(seen)
        self.assertEqual(seen[0][1], raw_size)
        self.assertEqual(seen[-1][0], raw_size)

    def test_a_trailer_with_another_magic_carries_no_disk(self):
        original = self.installer.read_bytes()
        imagesstore.append(self.installer, self.raw)
        damaged = bytearray(self.installer.read_bytes())
        damaged[-imagesstore.TRAILER.size] ^= 0xFF
        self.installer.write_bytes(bytes(damaged))
        self.assertIsNone(imagesstore.locate(self.installer))
        self.assertGreater(len(damaged), len(original))

    def test_a_length_that_overruns_the_file_carries_no_disk(self):
        imagesstore.append(self.installer, self.raw)
        size = self.installer.stat().st_size
        with self.installer.open("r+b") as stream:
            stream.seek(size - imagesstore.TRAILER.size + 8)
            stream.write(imagesstore.TRAILER.pack(imagesstore.MAGIC, size, size)[8:])
        self.assertIsNone(imagesstore.locate(self.installer))

    def test_a_truncated_installer_reports_no_disk(self):
        imagesstore.append(self.installer, self.raw)
        size = self.installer.stat().st_size
        self.installer.write_bytes(self.installer.read_bytes()[:size - 4])
        self.assertIsNone(imagesstore.locate(self.installer))

    def test_a_damaged_archive_is_reported_and_leaves_no_partial_file(self):
        imagesstore.append(self.installer, self.raw)
        damaged = bytearray(self.installer.read_bytes())
        damaged[-64] ^= 0xFF
        self.installer.write_bytes(bytes(damaged))
        target = self.root / "expanded.raw"
        with self.assertRaises(Exception):
            imagesstore.extract(self.installer, target)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_an_existing_disk_is_replaced_only_when_the_new_one_is_whole(self):
        imagesstore.append(self.installer, self.raw)
        target = self.root / "expanded.raw"
        target.write_bytes(b"stale")
        imagesstore.extract(self.installer, target)
        self.assertEqual(target.read_bytes(), self.raw.read_bytes())

    def test_extract_rejects_an_installer_that_carries_no_disk(self):
        with self.assertRaisesRegex(ValueError, "no bundled Android image disk"):
            imagesstore.extract(self.installer, self.root / "expanded.raw")

    def test_append_rejects_a_missing_installer(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            imagesstore.append(self.root / "absent.exe", self.raw)

    def test_append_rejects_an_empty_disk(self):
        empty = self.root / "empty.raw"
        empty.touch()
        with self.assertRaisesRegex(ValueError, "is empty"):
            imagesstore.append(self.installer, empty)


if __name__ == "__main__":
    unittest.main()
