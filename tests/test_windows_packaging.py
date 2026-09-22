from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from androidbox.bundled import IMAGES_DISK
from androidbox import imagesstore
from scripts import package_desktop


VERSION = "1.0.20260928"
MAKENSIS = shutil.which("makensis")
REPO = Path(__file__).resolve().parents[1]


class WindowsPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = self.root / "dist/AndroidBox"
        (self.payload / "runtime/bin").mkdir(parents=True)
        self.images = self.payload / "runtime/images/x86_64"
        self.images.mkdir(parents=True)
        self.raw = self.images / IMAGES_DISK
        self.raw.write_bytes(b"guest image disk")
        self.output = self.root / "out"
        self.output.mkdir()

    def defines(self, run):
        # run() stringifies each part itself, so a Path may arrive unconverted.
        return [str(part) for call in run.call_args_list for part in call.args]

    def call_windows(self, images_raw=None):
        with patch.object(package_desktop, "ROOT", self.root), \
                patch.object(package_desktop, "run") as run, \
                patch("androidbox.imagesstore.append") as append:
            target = package_desktop.package_windows(VERSION, self.output, images_raw)
        return target, run, append

    def test_the_image_disk_stays_out_of_the_staged_payload(self):
        stage = self.root / "payload"
        package_desktop.stage_payload(self.payload, stage)
        self.assertTrue((stage / "runtime/bin").is_dir())
        self.assertTrue((stage / "runtime/images/x86_64").is_dir())
        self.assertFalse((stage / "runtime/images/x86_64" / IMAGES_DISK).exists())

    def test_a_stray_partial_disk_stays_out_of_the_staged_payload(self):
        partial = self.raw.with_name(f"{IMAGES_DISK}.part")
        partial.write_bytes(b"half written")
        stage = self.root / "payload"
        package_desktop.stage_payload(self.payload, stage)
        self.assertFalse((stage / "runtime/images/x86_64" / partial.name).exists())
        # Staging hard-links, so the source payload keeps its partial file.
        self.assertTrue(partial.exists())

    def test_the_installer_carries_the_image_package(self):
        target, run, append = self.call_windows(self.raw)
        self.assertEqual(target, self.output / f"AndroidBox-{VERSION}-Windows-x86_64-Setup.exe")
        self.assertIn("/DIMAGES_PKG=1", self.defines(run))
        payloads = [part for part in self.defines(run) if part.startswith("/DPAYLOAD=")]
        self.assertEqual(len(payloads), 1)
        self.assertEqual(Path(payloads[0][len("/DPAYLOAD="):]).name, "payload")
        self.assertEqual(append.call_args.args[0], target)
        self.assertEqual(append.call_args.args[1], self.raw)

    def test_the_installer_is_left_alone_without_an_image_disk(self):
        target, run, append = self.call_windows()
        self.assertTrue(target.name.endswith("Setup.exe"))
        self.assertNotIn("/DIMAGES_PKG=1", self.defines(run))
        self.assertFalse(append.called)

    def test_the_staged_payload_is_discarded_after_compiling(self):
        target, _, _ = self.call_windows(self.raw)
        staged = [path for path in self.root.glob("androidbox-payload-*")]
        self.assertEqual(staged, [])
        self.assertTrue(target.name.endswith("Setup.exe"))


    def test_the_staged_payload_is_discarded_after_compiling(self):
        target, _, _ = self.call_windows(self.raw)
        staged = [path for path in self.root.glob("androidbox-payload-*")]
        self.assertEqual(staged, [])
        self.assertTrue(target.name.endswith("Setup.exe"))


@unittest.skipUnless(MAKENSIS, "Install makensis to compile the Windows installer")
class NsisImagePackageTests(unittest.TestCase):
    """Compile the real script and prove the appended disk stays invisible.

    makensis reads `/`-prefixed switches on Windows and `-`-prefixed ones
    everywhere else, and the Windows build job is the only place the script is
    otherwise compiled.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        payload = self.root / "payload"
        (payload / "runtime/bin").mkdir(parents=True)
        (payload / "runtime/images/x86_64").mkdir(parents=True)
        (payload / "AndroidBox.exe").write_bytes(b"MZ fake payload")
        (payload / "runtime/bin/qemu-system-x86_64.exe").write_bytes(b"qemu")
        self.raw = self.root / IMAGES_DISK
        self.raw.write_bytes(bytes(range(256)) * 4096)
        self.target = self.root / "AndroidBox-Setup.exe"

    def switches(self):
        prefix = "/" if sys.platform == "win32" else "-"
        return [f"{prefix}D{name}" for name in
                (f"VERSION={VERSION}", "NUMERIC_VERSION=1.0.2026.928",
                 f"PAYLOAD={self.root / 'payload'}", f"OUTPUT={self.target}",
                 f"LICENSE_FILE={REPO / 'LICENSE'}",
                 f"ICON_FILE={REPO / 'packaging/icons/AndroidBox.ico'}",
                 "IMAGES_PKG=1")]

    def compile(self):
        completed = subprocess.run([MAKENSIS, ("/WX" if sys.platform == "win32" else "-WX"),
                                    *self.switches(), str(REPO / "packaging/windows.nsi")],
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return completed.stdout

    def test_the_installed_image_package_is_compiled_into_the_script(self):
        output = self.compile()
        self.assertIn("IMAGES_PKG", output)
        self.assertTrue(self.target.is_file())
        self.assertLess(self.target.stat().st_size, 1 << 20)

    def test_an_appended_disk_round_trips_from_the_finished_installer(self):
        self.compile()
        installer_bytes = self.target.stat().st_size
        imagesstore.append(self.target, self.raw)
        offset, length, raw_size = imagesstore.locate(self.target)
        # The disk starts exactly where the installer ends, so NSIS never sees it.
        self.assertEqual(offset, installer_bytes)
        self.assertEqual(raw_size, self.raw.stat().st_size)
        self.assertLess(length, raw_size)
        restored = self.root / "restored.raw"
        imagesstore.extract(self.target, restored)
        self.assertEqual(restored.read_bytes(), self.raw.read_bytes())


if __name__ == "__main__":
    unittest.main()
