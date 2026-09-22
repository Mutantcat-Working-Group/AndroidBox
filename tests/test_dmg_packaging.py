import sys
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import package_desktop


class DmgPackagingTests(unittest.TestCase):
    def mount_output(self, *volumes):
        return "\n".join(f"/dev/disk4s1 on {volume} (hfs, local, journaled)" for volume in volumes)

    def completed(self, returncode=0, stdout=""):
        return subprocess.CompletedProcess(["command"], returncode, stdout, "")

    def test_mounted_volumes_ignores_other_disk_images(self):
        output = self.mount_output("/Volumes/AndroidBox", "/Volumes/Other", "/System/Volumes/VM")
        with patch.object(package_desktop.subprocess, "run", return_value=self.completed(stdout=output)):
            self.assertEqual(package_desktop.mounted_volumes(), ["/Volumes/AndroidBox"])

    def test_mounted_volumes_handles_an_empty_mount_table(self):
        with patch.object(package_desktop.subprocess, "run", return_value=self.completed()):
            self.assertEqual(package_desktop.mounted_volumes(), [])

    def test_release_volume_detaches_a_leftover_volume(self):
        output = self.mount_output("/Volumes/AndroidBox", "/Volumes/Untitled")
        with patch.object(package_desktop.subprocess, "run") as spawn:
            spawn.return_value = self.completed(stdout=output)
            package_desktop.release_volume()
            detach = [call.args[0] for call in spawn.call_args_list if call.args[0][0] == "hdiutil"]
        self.assertEqual(detach, [["hdiutil", "detach", "/Volumes/AndroidBox"]])

    def test_create_dmg_succeeds_without_retrying(self):
        with patch.object(package_desktop.subprocess, "run") as spawn, \
                patch.object(package_desktop, "time") as clock:
            spawn.return_value = self.completed()
            package_desktop.create_dmg(Path("/stage"), Path("/target.dmg"))
        self.assertEqual([call.args[0][0] for call in spawn.call_args_list], ["mount", "hdiutil"])
        self.assertIn("AndroidBox", spawn.call_args_list[1].args[0])
        self.assertFalse(clock.sleep.called)

    def test_create_dmg_retries_once_after_a_busy_failure(self):
        attempts = [self.completed(), self.completed(returncode=1),
                    self.completed(), self.completed()]
        with patch.object(package_desktop.subprocess, "run", side_effect=attempts) as spawn, \
                patch.object(package_desktop, "time") as clock:
            package_desktop.create_dmg(Path("/stage"), Path("/target.dmg"))
        commands = [call.args[0][0] for call in spawn.call_args_list]
        self.assertEqual(commands, ["mount", "hdiutil", "mount", "hdiutil"])
        clock.sleep.assert_called_once_with(5)

    def test_create_dmg_reports_a_failure_that_persists(self):
        attempts = [self.completed(), self.completed(returncode=1),
                    self.completed(), self.completed(returncode=1)]
        with patch.object(package_desktop.subprocess, "run", side_effect=attempts) as spawn, \
                patch.object(package_desktop, "time"):
            package_desktop.create_dmg(Path("/stage"), Path("/target.dmg"))
        # The retry goes through the checked runner, so a failure that persists
        # aborts the build with the command output visible.
        self.assertEqual(spawn.call_args.kwargs["check"], True)
        self.assertEqual(spawn.call_args.args[0][0], "hdiutil")

    def test_package_mac_stages_the_app_and_a_shortcut_for_the_image_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "dist/AndroidBox.app"
            (app / "Contents").mkdir(parents=True)
            output = root / "dist/installers"
            output.mkdir()
            image = output / "AndroidBox-1.0.20260921-macOS-x86_64.dmg"
            observed = {}

            def capture(source, target, name=package_desktop.VOLUME_NAME):
                # The staging folder is removed as soon as package_mac returns, so
                # the image root has to be inspected while it still exists.
                observed["shortcut"] = (source / "Applications").is_symlink()
                observed["app"] = (source / "AndroidBox.app").name
                return image

            with patch.object(package_desktop, "ROOT", root), \
                    patch.object(package_desktop, "sign_app"), \
                    patch.object(package_desktop, "run") as run, \
                    patch.object(package_desktop, "create_dmg", side_effect=capture) as create:
                result = package_desktop.package_mac("1.0.20260921", "x86_64", output)
            self.assertEqual(result, image)
            # The staged folder becomes the image root, holding the app and the
            # Applications shortcut beside it.
            self.assertTrue(observed["shortcut"])
            self.assertEqual(observed["app"], "AndroidBox.app")
            stage = create.call_args.args[0]
            ditto = [call.args for call in run.call_args_list if call.args[0] == "ditto"]
            self.assertEqual(ditto, [("ditto", app, stage / "AndroidBox.app")])
            self.assertEqual(create.call_args.args[1], image)

    def test_verify_dmg_image_succeeds_without_retrying(self):
        with patch.object(package_desktop, "run") as spawn, \
                patch.object(package_desktop, "release_volume") as release, \
                patch.object(package_desktop, "time") as clock:
            package_desktop.verify_dmg_image(Path("/target.dmg"))
        self.assertEqual([call.args[0] for call in spawn.call_args_list], ["hdiutil"])
        self.assertFalse(release.called)
        self.assertFalse(clock.sleep.called)

    def test_verify_dmg_image_retries_once_when_the_helper_is_busy(self):
        refusal = subprocess.CalledProcessError(1, "hdiutil")
        with patch.object(package_desktop, "run", side_effect=[refusal, None]) as spawn, \
                patch.object(package_desktop, "release_volume") as release, \
                patch.object(package_desktop, "time") as clock:
            package_desktop.verify_dmg_image(Path("/target.dmg"))
        self.assertEqual([call.args[0] for call in spawn.call_args_list], ["hdiutil", "hdiutil"])
        self.assertEqual(release.call_count, 1)
        clock.sleep.assert_called_once_with(5)

    def test_verify_dmg_image_reports_a_failure_that_persists(self):
        refusal = subprocess.CalledProcessError(1, "hdiutil")
        with patch.object(package_desktop, "run", side_effect=[refusal, refusal]) as spawn, \
                patch.object(package_desktop, "release_volume"), \
                patch.object(package_desktop, "time"):
            with self.assertRaises(subprocess.CalledProcessError):
                package_desktop.verify_dmg_image(Path("/target.dmg"))
        self.assertEqual(spawn.call_count, 2)

    def test_package_mac_verifies_the_image_through_the_retrying_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "dist/AndroidBox.app"
            (app / "Contents").mkdir(parents=True)
            output = root / "dist/installers"
            output.mkdir()
            image = output / "AndroidBox-1.0.20260921-macOS-arm64.dmg"
            with patch.object(package_desktop, "ROOT", root), \
                    patch.object(package_desktop, "sign_app"), \
                    patch.object(package_desktop, "run"), \
                    patch.object(package_desktop, "create_dmg", return_value=image), \
                    patch.object(package_desktop, "verify_dmg_image") as verify:
                package_desktop.package_mac("1.0.20260921", "arm64", output)
            verify.assert_called_once_with(image)


if __name__ == "__main__":
    unittest.main()
