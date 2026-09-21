import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import importlib.util
import io
import json
import shutil
import struct
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from androidbox import guestdisk


QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None
CERTIFI_AVAILABLE = importlib.util.find_spec("certifi") is not None


class OverlayWriterTests(unittest.TestCase):
    def test_overlay_header_matches_the_qcow2_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.img"
            base.write_bytes(b"\0" * 4096)
            overlay = Path(directory) / "androidbox-aarch64.qcow2"
            guestdisk.write_overlay(overlay, base.name, 32 * 1024 ** 3)
            data = overlay.read_bytes()
        self.assertEqual(data[:4], b"QFI\xfb")
        self.assertEqual(struct.unpack_from(">I", data, 4)[0], 3)
        cluster_bits = struct.unpack_from(">I", data, 20)[0]
        self.assertEqual(cluster_bits, 16)
        size = struct.unpack_from(">Q", data, 24)[0]
        self.assertEqual(size, 32 * 1024 ** 3)
        l1_size = struct.unpack_from(">I", data, 36)[0]
        self.assertEqual(l1_size, 64)
        l1_offset = struct.unpack_from(">Q", data, 40)[0]
        self.assertEqual(l1_offset, 3 * 65536)
        self.assertEqual(struct.unpack_from(">Q", data, 48)[0], 65536)
        self.assertEqual(struct.unpack_from(">I", data, 56)[0], 1)
        self.assertEqual(struct.unpack_from(">I", data, 60)[0], 0)
        self.assertEqual(struct.unpack_from(">I", data, 96)[0], 4)
        self.assertEqual(struct.unpack_from(">I", data, 100)[0], 104)
        self.assertEqual(struct.unpack_from(">I", data, 104)[0], 0xE2792ACA)
        self.assertEqual(data[112:115], b"raw")
        offset, length = struct.unpack_from(">QI", data, 8)[0], struct.unpack_from(">I", data, 16)[0]
        self.assertEqual(data[offset:offset + length], base.name.encode())
        self.assertEqual(struct.unpack_from(">4H", data, 2 * 65536), (1, 1, 1, 1))
        self.assertEqual(struct.unpack_from(">Q", data, 65536)[0], 2 * 65536)
        self.assertEqual(data[l1_offset:], bytearray(l1_size * 8))
        self.assertEqual(len(data), l1_offset + l1_size * 8)

    def test_small_overlay_keeps_one_l1_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.img"
            base.write_bytes(b"\0" * 4096)
            overlay = Path(directory) / "small.qcow2"
            guestdisk.write_overlay(overlay, base.name, 1024 ** 2)
            data = overlay.read_bytes()
        self.assertEqual(struct.unpack_from(">I", data, 36)[0], 1)
        self.assertEqual(len(data), 3 * 65536 + 8)

    def test_create_overlay_requires_the_backing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                guestdisk.create_overlay(Path(directory) / "o.qcow2", Path(directory) / "missing.img")

    @unittest.skipUnless(shutil.which("qemu-img"), "qemu-img is not installed")
    def test_qemu_img_validates_the_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.img"
            overlay = Path(directory) / "androidbox-x86_64.qcow2"
            subprocess.run(["qemu-img", "create", "-f", "raw", str(base), "4M"],
                           check=True, capture_output=True)
            guestdisk.create_overlay(overlay, base)
            for command in (["check", str(overlay)], ["info", str(overlay)]):
                result = subprocess.run(["qemu-img", *command], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("qemu-img") and shutil.which("qemu-io"), "QEMU tools are not installed")
    def test_reads_fall_through_and_writes_stay_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.img"
            overlay = Path(directory) / "androidbox-aarch64.qcow2"
            subprocess.run(["qemu-img", "create", "-f", "raw", str(base), "8M"],
                           check=True, capture_output=True)
            subprocess.run(["qemu-io", "-f", "raw", "-c", "write -P 0x5a 1M 512", str(base)],
                           check=True, capture_output=True)
            guestdisk.create_overlay(overlay, base)
            read_backing = subprocess.run(["qemu-io", "-f", "qcow2", "-c", "read -P 0x5a 1M 512", str(overlay)],
                                          capture_output=True, text=True)
            self.assertEqual(read_backing.returncode, 0, read_backing.stderr)
            write = subprocess.run(["qemu-io", "-f", "qcow2", "-c", "write -P 0x33 2M 512", str(overlay)],
                                   capture_output=True, text=True)
            self.assertEqual(write.returncode, 0, write.stderr)
            read_overlay = subprocess.run(["qemu-io", "-f", "qcow2", "-c", "read -P 0x33 2M 512", str(overlay)],
                                           capture_output=True, text=True)
            self.assertEqual(read_overlay.returncode, 0, read_overlay.stderr)
            untouched = base.read_bytes()[2 * 1024 ** 2:2 * 1024 ** 2 + 512]
            self.assertEqual(untouched, bytearray(512))


class DownloadVerificationTests(unittest.TestCase):
    def test_download_accepts_matching_checksum(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "payload.img"
            source.write_bytes(b"androidbox-example")
            digest = hashlib.sha256(b"androidbox-example").hexdigest()
            target = Path(directory) / "nested" / "payload.img"
            guestdisk.download_verified(source.as_uri(), target, digest.upper())
            self.assertEqual(target.read_bytes(), b"androidbox-example")
            self.assertFalse((Path(directory) / "nested" / ".payload.img.download").exists())

    def test_download_rejects_checksum_mismatch(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "payload.img"
            source.write_bytes(b"androidbox-example")
            target = Path(directory) / "payload.img.downloaded"
            with self.assertRaises(ValueError):
                guestdisk.download_verified(source.as_uri(), target, hashlib.sha256(b"other").hexdigest())
            self.assertFalse(target.exists())

    def test_progress_reports_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "payload.img"
            source.write_bytes(b"x" * 2048)
            digest = hashlib.sha256(b"x" * 2048).hexdigest()
            reports = []
            guestdisk.download_verified(source.as_uri(), Path(directory) / "out.img", digest,
                                        progress=lambda done, total: reports.append((done, total)))
            self.assertEqual(reports, [(2048, 2048)])

    def test_download_resumes_a_partial_transfer(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "payload.img"
            temporary = target.with_name(f".{target.name}.download")
            temporary.write_bytes(b"andro")
            digest = hashlib.sha256(b"androidbox").hexdigest()
            ranges = []

            class Response(io.BytesIO):
                status = 206
                headers = {"Content-Length": "5"}

            def fake_open(url, timeout, headers=None):
                ranges.append(headers.get("Range") if headers else None)
                return Response(b"idbox")

            reports = []
            with patch.object(guestdisk, "_open", side_effect=fake_open):
                guestdisk.download_verified("https://example/payload.img", target, digest,
                                            progress=lambda done, total: reports.append((done, total)))
            self.assertEqual(target.read_bytes(), b"androidbox")
            self.assertEqual(ranges, ["bytes=5-"])
            # The bytes already on disk are reported first, with no total yet.
            self.assertEqual(reports[0], (5, None))
            self.assertEqual(reports[-1], (10, 10))
            self.assertFalse(temporary.exists())

    def test_download_restarts_when_the_server_ignores_the_range(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "payload.img"
            temporary = target.with_name(f".{target.name}.download")
            temporary.write_bytes(b"stale")
            digest = hashlib.sha256(b"androidbox").hexdigest()

            class Response(io.BytesIO):
                status = 200
                headers = {"Content-Length": "10"}

            with patch.object(guestdisk, "_open", return_value=Response(b"androidbox")):
                guestdisk.download_verified("https://example/payload.img", target, digest)
            self.assertEqual(target.read_bytes(), b"androidbox")

    def test_download_keeps_the_partial_transfer_when_a_retry_fails(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "payload.img"
            temporary = target.with_name(f".{target.name}.download")
            digest = hashlib.sha256(b"androidbox").hexdigest()
            with patch.object(guestdisk, "_open", side_effect=ValueError("Cannot reach host")):
                with self.assertRaises(ValueError):
                    guestdisk.download_verified("https://example/payload.img", target, digest)
            self.assertFalse(target.exists())
            self.assertFalse(temporary.exists())


class TrustStoreTests(unittest.TestCase):
    def _captured_context_kwargs(self):
        captured = {}
        real = guestdisk.ssl.create_default_context

        def capture(**kwargs):
            captured.update(kwargs)
            return real(**kwargs)

        return captured, capture

    @unittest.skipUnless(CERTIFI_AVAILABLE, "Install the desktop extra to bundle a CA store")
    def test_context_trusts_the_bundled_ca_bundle(self):
        import certifi
        captured, capture = self._captured_context_kwargs()
        with patch.object(guestdisk.ssl, "create_default_context", side_effect=capture):
            context = guestdisk.ssl_context()
        self.assertIsInstance(context, guestdisk.ssl.SSLContext)
        self.assertEqual(captured.get("cafile"), certifi.where())

    def test_context_falls_back_to_the_host_trust_store_without_certifi(self):
        captured, capture = self._captured_context_kwargs()
        with patch.object(guestdisk.ssl, "create_default_context", side_effect=capture), \
                patch.dict(sys.modules, {"certifi": None}):
            guestdisk.ssl_context()
        self.assertNotIn("cafile", captured)


class MirrorFallbackTests(unittest.TestCase):
    def test_manifest_falls_back_to_a_mirror(self):
        digest = "0" * 64
        requested = []

        def fake_open(url, timeout, headers=None):
            requested.append(url)
            if "cloud-images.ubuntu.com" in url:
                raise ValueError("Cannot reach the official host")
            return io.BytesIO(f"{digest} *ubuntu-24.04-minimal-cloudimg-amd64.img\n".encode())

        with patch.object(guestdisk, "_open", side_effect=fake_open):
            checksums, url = guestdisk.remote_checksums()
        self.assertEqual(checksums["ubuntu-24.04-minimal-cloudimg-amd64.img"], digest)
        self.assertIn("mirrors.ustc.edu.cn", url)
        self.assertEqual(len(requested), 2)

    def test_manifest_reports_every_failed_mirror(self):
        with patch.object(guestdisk, "_open", side_effect=ValueError("Cannot reach host")):
            with self.assertRaises(ValueError) as caught:
                guestdisk.remote_checksums()
        message = str(caught.exception)
        self.assertIn("Use a local image", message)
        self.assertEqual(message.count("Cannot reach host"), len(guestdisk.MIRRORS))

    def test_base_image_falls_back_to_a_mirror(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / guestdisk.image_remote_name("x86_64")
            digest = hashlib.sha256(b"payload").hexdigest()
            requested = []

            def fake_download(url, target_path, expected, progress=None):
                requested.append(url)
                if "mirrors.ustc.edu.cn" not in url:
                    raise ValueError("Cannot reach host")
                target_path.write_bytes(b"payload")
                return target_path

            with patch.object(guestdisk, "download_verified", side_effect=fake_download):
                self.assertEqual(guestdisk.ensure_base_image(target, digest), target)
            self.assertEqual(len(requested), 2)
            self.assertIn("mirrors.ustc.edu.cn", requested[-1])

    def test_base_image_reports_every_failed_mirror(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / guestdisk.image_remote_name("x86_64")
            with patch.object(guestdisk, "download_verified", side_effect=ValueError("Cannot reach host")):
                with self.assertRaises(ValueError) as caught:
                    guestdisk.ensure_base_image(target, hashlib.sha256(b"payload").hexdigest())
        self.assertIn("Use a local image", str(caught.exception))


class PrepareTests(unittest.TestCase):
    def test_prepare_is_idempotent_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "androidbox-aarch64.qcow2"
            overlay.write_bytes(b"QFI\xfb")
            with patch.object(guestdisk, "remote_checksums", side_effect=AssertionError("network")):
                self.assertEqual(guestdisk.prepare("arm64", directory), overlay)

    def test_prepare_local_image_creates_a_pointing_overlay(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "local.img"
            local.write_bytes(b"\0" * 4096)
            digest = hashlib.sha256(local.read_bytes()).hexdigest()
            remote_name = guestdisk.image_remote_name("aarch64")
            checksums = {remote_name: digest}
            with patch.object(guestdisk, "remote_checksums", return_value=(checksums, "https://example/SHA256SUMS")):
                overlay = guestdisk.prepare("aarch64", directory, local_image=local)
            data = overlay.read_bytes()
            self.assertTrue(overlay.is_file())
            self.assertEqual(data[:4], b"QFI\xfb")
            offset, length = struct.unpack_from(">QI", data, 8)[0], struct.unpack_from(">I", data, 16)[0]
            self.assertEqual(data[offset:offset + length], remote_name.encode())
            self.assertTrue((Path(directory) / remote_name).is_file())

    def test_prepare_rejects_missing_manifest_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(guestdisk, "remote_checksums", return_value=({}, "https://example/SHA256SUMS")):
                with self.assertRaises(ValueError):
                    guestdisk.prepare("x86_64", directory)

    def test_prepare_rejects_local_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "local.img"
            local.write_bytes(b"wrong")
            with patch.object(guestdisk, "remote_checksums",
                              return_value=({guestdisk.image_remote_name("x86_64"): "0" * 64}, "https://example/SHA256SUMS")):
                with self.assertRaises(ValueError):
                    guestdisk.prepare("x86_64", directory, local_image=local)

    def test_parse_size_units_and_bounds(self):
        self.assertEqual(guestdisk.parse_size("32G"), 32 * 1024 ** 3)
        self.assertEqual(guestdisk.parse_size("512m"), 512 * 1024 ** 2)
        self.assertEqual(guestdisk.parse_size("1TiB"), 1024 ** 4)
        self.assertEqual(guestdisk.parse_size("1024"), 1024)
        self.assertEqual(guestdisk.parse_size("1000"), 1024)
        for bad in ("", "abc", "10Z", "0"):
            with self.subTest(size=bad):
                with self.assertRaises(ValueError):
                    guestdisk.parse_size(bad)


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to exercise the first-run guest disk flow")
class PrepareFlowTests(unittest.TestCase):
    def test_first_run_button_prepares_and_stores_the_disk(self):
        from PySide6.QtWidgets import QApplication
        from androidbox.desktop import MainWindow

        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory, \
                patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)), \
                patch("androidbox.desktop.QMessageBox.warning"):
            overlay = Path(directory) / "guests" / guestdisk.managed_disk_name("aarch64")

            def fake_prepare(arch, directory_argument, **kwargs):
                overlay.parent.mkdir(parents=True, exist_ok=True)
                overlay.write_bytes(b"QFI\xfb")
                return overlay

            window = MainWindow()
            window.show()
            self.assertTrue(window.prepare_button.isVisible())
            with patch("androidbox.desktop.guestdisk.prepare", side_effect=fake_prepare):
                window.prepare_guest_disk()
                window.future.result(timeout=10)
                window.poll()
            self.assertEqual(window.config.disk, str(overlay))
            self.assertEqual(window.config.disk_format, "qcow2")
            self.assertFalse(window.prepare_button.isVisible())
            # Read the stored settings as data: JSON escapes Windows path separators,
            # so matching the raw document text would only work on Unix platforms.
            saved = json.loads((Path(directory) / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["disk"], str(overlay))
            self.assertEqual(saved["disk_format"], "qcow2")
            window.close()
        self.assertIsNotNone(application)

    def test_local_image_button_prepares_the_chosen_architecture(self):
        from types import SimpleNamespace

        from PySide6.QtWidgets import QApplication, QDialog
        from androidbox.desktop import MainWindow

        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory, \
                patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)), \
                patch("androidbox.desktop.QMessageBox.warning"):
            overlay = Path(directory) / "guests" / guestdisk.managed_disk_name("x86_64")
            local = Path(directory) / "ubuntu-24.04-minimal-cloudimg-amd64.img"
            local.write_bytes(b"cloud image")

            class FakeDialog:
                def __init__(self, parent=None):
                    self.arch = SimpleNamespace(currentText=lambda: "x86_64")

                def exec(self):
                    return QDialog.Accepted

                def image(self):
                    return str(local)

            window = MainWindow()
            window.show()
            self.assertTrue(window.local_button.isVisible())
            def fake_prepare(arch, directory_argument, **kwargs):
                overlay.parent.mkdir(parents=True, exist_ok=True)
                overlay.write_bytes(b"QFI\xfb")
                return overlay

            with patch("androidbox.desktop.LocalImageDialog", FakeDialog), \
                    patch("androidbox.desktop.guestdisk.prepare", side_effect=fake_prepare) as prepare:
                window.use_local_image()
                window.future.result(timeout=10)
                window.poll()
            self.assertEqual(prepare.call_args.args[0], "x86_64")
            self.assertEqual(prepare.call_args.kwargs["local_image"], str(local))
            self.assertEqual(window.config.disk, str(overlay))
            self.assertEqual(window.config.arch, "x86_64")
            self.assertFalse(window.local_button.isVisible())
            window.close()
        self.assertIsNotNone(application)

    def test_local_image_button_ignores_a_cancelled_dialog(self):
        from PySide6.QtWidgets import QApplication, QDialog
        from androidbox.desktop import MainWindow

        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory, \
                patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)), \
                patch("androidbox.desktop.QMessageBox.warning"):
            class CancelledDialog:
                def __init__(self, parent=None):
                    self.arch = None

                def exec(self):
                    return QDialog.Rejected

                def image(self):
                    return ""

            window = MainWindow()
            window.show()
            with patch("androidbox.desktop.LocalImageDialog", CancelledDialog), \
                    patch("androidbox.desktop.guestdisk.prepare",
                          side_effect=AssertionError("must not prepare")):
                window.use_local_image()
            self.assertIsNone(window.future)
            self.assertTrue(window.local_button.isVisible())
            window.close()
        self.assertIsNotNone(application)
