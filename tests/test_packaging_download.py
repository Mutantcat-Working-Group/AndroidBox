import hashlib
import io
import os
from pathlib import Path
import subprocess
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

    def test_platform_tools_archive_is_arch_aware(self):
        # Google ships no AArch64 Linux Platform Tools archive.
        self.assertIsNone(fetch_platform_tools.archive_for("Linux", "aarch64"))
        self.assertIs(fetch_platform_tools.archive_for("Linux", "x86_64"),
                      fetch_platform_tools.ARCHIVES["Linux"])
        self.assertIs(fetch_platform_tools.archive_for("Darwin", "aarch64"),
                      fetch_platform_tools.ARCHIVES["Darwin"])
        self.assertEqual(fetch_platform_tools.host_arch("AMD64"), "x86_64")
        self.assertEqual(fetch_platform_tools.host_arch("arm64"), "aarch64")
        with self.assertRaisesRegex(ValueError, "Unsupported architecture"):
            fetch_platform_tools.host_arch("riscv64")

    def test_platform_tools_linux_arm64_stages_the_distribution_package(self):
        with tempfile.TemporaryDirectory() as directory:
            target = (Path(directory) / "platform-tools").resolve()
            with patch.object(fetch_platform_tools, "install_distribution", return_value=target) as staged:
                fetch_platform_tools.install(target, system="Linux", arch="aarch64")
            staged.assert_called_once_with(target)

    def test_distribution_adb_is_staged_with_its_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "usr/bin/adb"
            source.parent.mkdir(parents=True)
            source.write_text("binary")
            library = root / "lib/android-libbase.so"
            library.parent.mkdir(parents=True)
            library.write_text("library")
            documents = root / "usr/share/doc"
            (documents / "adb").mkdir(parents=True)
            (documents / "adb/copyright").write_text("distribution license")
            target = root / "build/platform-tools"
            with patch.object(fetch_platform_tools, "distribution_adb", return_value=source), \
                    patch.object(fetch_platform_tools, "shared_libraries", return_value=[library]), \
                    patch.object(fetch_platform_tools, "set_runpath") as runpath, \
                    patch.object(fetch_platform_tools, "require_runnable") as runnable:
                fetch_platform_tools.install_distribution(target, documents=documents)
            self.assertEqual((target / "adb").read_text(), "binary")
            self.assertEqual((target / "lib" / library.name).read_text(), "library")
            self.assertIn("distribution license", (target / "NOTICE.txt").read_text())
            self.assertTrue(runpath.called and runnable.called)
            self.assertFalse((root / "build/.platform-tools.extract").exists())

    def test_distribution_adb_refuses_an_unrunnable_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "adb"
            source.write_text("binary")
            target = root / "build/platform-tools"
            with patch.object(fetch_platform_tools, "distribution_adb", return_value=source), \
                    patch.object(fetch_platform_tools, "shared_libraries", return_value=[]), \
                    patch.object(fetch_platform_tools, "set_runpath"), \
                    patch.object(fetch_platform_tools.subprocess, "run",
                                 return_value=subprocess.CompletedProcess(["adb"], 1, "", "Exec format error")):
                with self.assertRaisesRegex(ValueError, "did not run"):
                    fetch_platform_tools.install_distribution(target, documents=root)
            self.assertFalse(target.exists())

    def test_distribution_adb_requires_an_installed_package(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(fetch_platform_tools, "distribution_adb", return_value=None):
                with self.assertRaisesRegex(ValueError, "no AArch64 Linux Platform Tools"):
                    fetch_platform_tools.install_distribution(Path(directory) / "platform-tools")

    def test_shared_libraries_skip_host_loader_pieces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("libc.so.6", "ld-linux-aarch64.so.1", "libusb-1.0.so.0"):
                (root / name).write_text(name)
            output = "\n".join(["\tlinux-vdso.so.1 (0x0000ffff)",
                                f"\tlibc.so.6 => {root / 'libc.so.6'} (0x0000ffff)",
                                f"\tld-linux-aarch64.so.1 => {root / 'ld-linux-aarch64.so.1'} (0x0000ffff)",
                                f"\tlibusb-1.0.so.0 => {root / 'libusb-1.0.so.0'} (0x0000ffff)",
                                "\tlibabsent.so.1 => not found"])
            with patch.object(fetch_platform_tools.subprocess, "run",
                              return_value=subprocess.CompletedProcess(["ldd"], 0, output, "")):
                libraries = fetch_platform_tools.shared_libraries(root / "adb")
            self.assertEqual([path.name for path in libraries], ["libusb-1.0.so.0"])

    def test_require_runnable_rejects_a_missing_version_string(self):
        with patch.object(fetch_platform_tools.subprocess, "run",
                          return_value=subprocess.CompletedProcess(["adb"], 0, "", "")):
            with self.assertRaisesRegex(ValueError, "did not run"):
                fetch_platform_tools.require_runnable(Path("adb"))

    def test_require_runnable_accepts_a_working_binary(self):
        version = subprocess.CompletedProcess(["adb"], 0, "Android Debug Bridge version 34.0.4", "")
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/hostedtoolcache/Python/3.12/lib"}), \
                patch.object(fetch_platform_tools.subprocess, "run", return_value=version) as spawn:
            self.assertIsNone(fetch_platform_tools.require_runnable(Path("adb")))
        # A staged ADB must not inherit the build host's library search path.
        self.assertNotIn("LD_LIBRARY_PATH", spawn.call_args.kwargs["env"])

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
