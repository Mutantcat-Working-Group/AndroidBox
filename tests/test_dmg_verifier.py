from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_frozen


class StagedMount:
    """Serve verify_dmg's temporary mount point from a directory we control."""

    def __init__(self, path):
        self.path = path
        self.root = Path(path) / "volume"

    def __enter__(self):
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "AndroidBox.app/Contents/MacOS").mkdir(parents=True, exist_ok=True)
            (self.root / "Applications").symlink_to("/Applications")
        return self.path

    def remove_shortcut(self):
        (self.root / "Applications").unlink()

    def __exit__(self, *_):
        return False
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "AndroidBox.app/Contents/MacOS").mkdir(parents=True, exist_ok=True)
        (self.root / "Applications").symlink_to("/Applications")
        return self.root

    def __exit__(self, *_):
        return False


class DmgVerifierTests(unittest.TestCase):
    def mount(self, image):
        return StagedMount(image.parent)

    def adhoc(self, args, **kwargs):
        if args[:2] == ["codesign", "-dv"]:
            return subprocess.CompletedProcess(args, 0, "Signature=adhoc", "")
        return subprocess.CompletedProcess(args, 0)

    def test_verifies_mounted_application_and_detaches_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "AndroidBox.dmg"
            image.touch()
            mount = self.mount(image)
            with mount, \
                    patch.object(verify_frozen.tempfile, "TemporaryDirectory",
                                 return_value=mount), \
                    patch("scripts.verify_frozen.subprocess.run", side_effect=self.adhoc) as run, \
                    patch.object(verify_frozen, "verify", side_effect=ValueError("test failure")) as verify, \
                    self.assertRaisesRegex(ValueError, "test failure"):
                verify_frozen.verify_dmg(image, require_runtime=True)
                verify.assert_called_once()
                self.assertTrue(verify.call_args.kwargs["require_runtime"])
                executable = verify.call_args.args[0]
                self.assertEqual(executable.parts[-4:],
                                  ("AndroidBox.app", "Contents", "MacOS", "AndroidBox"))
                self.assertEqual(run.call_args.args[0][:2], ["hdiutil", "detach"])
                self.assertEqual(run.call_args.args[0][2], str(executable.parents[3]))

    def test_the_disk_image_and_its_application_must_both_be_adhoc_signed(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "AndroidBox.dmg"
            image.touch()
            mount = self.mount(image)
            with mount, \
                    patch.object(verify_frozen.tempfile, "TemporaryDirectory",
                                 return_value=mount), \
                    patch("scripts.verify_frozen.subprocess.run", side_effect=self.adhoc) as run, \
                    patch.object(verify_frozen, "verify"):
                verify_frozen.verify_dmg(image)
                inspected = [call.args[0] for call in run.call_args_list
                                if call.args[0][:2] == ["codesign", "-dv"]]
                self.assertEqual(len(inspected), 2)

    def test_a_signed_disk_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "AndroidBox.dmg"
            image.touch()
            with patch("scripts.verify_frozen.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 0, "Authority=Developer ID", "")), \
                    patch.object(verify_frozen, "verify"):
                with self.assertRaisesRegex(ValueError, "ad-hoc"):
                    verify_frozen.verify_dmg(image)

    def test_a_signed_application_inside_the_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "AndroidBox.dmg"
            image.touch()
            mount = self.mount(image)

            def codesign(args, **kwargs):
                target = Path(args[-1])
                if args[:2] == ["codesign", "-dv"] and target.name.endswith(".dmg"):
                    return subprocess.CompletedProcess(args, 0, "Signature=adhoc", "")
                return subprocess.CompletedProcess(args, 0, "Authority=Developer ID", "")

            with mount, \
                    patch.object(verify_frozen.tempfile, "TemporaryDirectory",
                                 return_value=mount), \
                    patch("scripts.verify_frozen.subprocess.run", side_effect=codesign), \
                    patch.object(verify_frozen, "verify"):
                with self.assertRaisesRegex(ValueError, "ad-hoc"):
                    verify_frozen.verify_dmg(image)

    def test_a_disk_image_without_the_applications_shortcut_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "AndroidBox.dmg"
            image.touch()
            mount = self.mount(image)
            with mount, \
                    patch.object(verify_frozen.tempfile, "TemporaryDirectory",
                                 return_value=mount), \
                    patch("scripts.verify_frozen.subprocess.run", side_effect=self.adhoc), \
                    patch.object(verify_frozen, "verify"):
                (mount.root / "Applications").unlink()
                with self.assertRaisesRegex(ValueError, "Applications"):
                    verify_frozen.verify_dmg(image)


if __name__ == "__main__":
    unittest.main()
