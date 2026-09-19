import subprocess
import unittest
from unittest.mock import patch

from androidbox import bundled


class RuntimeVerifierTests(unittest.TestCase):
    def test_missing_bundle_does_not_fall_back_to_system(self):
        with patch.object(bundled, "binary", return_value=None), \
                patch("androidbox.process.run") as run, \
                self.assertRaisesRegex(ValueError, "Missing bundled"):
            bundled.verify_runtime()
        run.assert_not_called()

    def test_checks_native_qemu_data_and_adb(self):
        with patch.object(bundled, "binary", side_effect=lambda name: f"/bundle/{name}"), \
                patch.object(bundled, "qemu_data", return_value="/bundle/share/qemu"), \
                patch.object(bundled, "arm_firmware", return_value="/bundle/firmware"), \
                patch("platform.machine", return_value="arm64"), \
                patch("androidbox.process.run", return_value=subprocess.CompletedProcess([], 0, "version info\n", "")) as run:
            result = bundled.verify_runtime()
        self.assertEqual(result["qemu"]["path"], "/bundle/qemu-system-aarch64")
        self.assertEqual(result["adb"]["version"], "version info")
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["/bundle/qemu-system-aarch64", "--version"], ["/bundle/adb", "version"]])
        for call in run.call_args_list:
            self.assertTrue(call.kwargs["check"])
            self.assertEqual(call.kwargs["timeout"], 10)

    def test_arm_firmware_required(self):
        with patch.object(bundled, "binary", return_value="/bundle/qemu"), \
                patch.object(bundled, "qemu_data", return_value="/bundle/share/qemu"), \
                patch.object(bundled, "arm_firmware", return_value=""), \
                patch("platform.machine", return_value="arm64"), \
                self.assertRaisesRegex(ValueError, "firmware"):
            bundled.verify_runtime()

    def test_failed_binary_not_accepted(self):
        with patch.object(bundled, "binary", return_value="/bundle/qemu"), \
                patch.object(bundled, "qemu_data", return_value="/bundle/share/qemu"), \
                patch("platform.machine", return_value="x86_64"), \
                patch("androidbox.process.run", side_effect=subprocess.CalledProcessError(1, "qemu")), \
                self.assertRaises(subprocess.CalledProcessError):
            bundled.verify_runtime()
