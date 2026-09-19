import subprocess
import unittest
from unittest.mock import patch

from androidbox.adb import install_apk


class AdbTests(unittest.TestCase):
    @patch("androidbox.adb.time.sleep")
    @patch("androidbox.adb.run")
    def test_waits_for_authorization_before_install(self, run, sleep):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "failed to authenticate", ""),
            subprocess.CompletedProcess([], 1, "", "device unauthorized"),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "Success\n", ""),
        ]
        self.assertEqual(install_apk("adb", "127.0.0.1:5555", "/test.apk"), "Success")
        self.assertEqual(run.call_args_list[-1].args[0],
                         ["adb", "-s", "127.0.0.1:5555", "install", "-r", "/test.apk"])
        sleep.assert_called_once()

    @patch("androidbox.adb.time.monotonic", side_effect=[0, 0, 121])
    @patch("androidbox.adb.time.sleep")
    @patch("androidbox.adb.run")
    def test_timeout_does_not_install(self, run, sleep, clock):
        run.return_value = subprocess.CompletedProcess([], 1, "", "device unauthorized")
        with self.assertRaisesRegex(RuntimeError, "Authorize"):
            install_apk("adb", "127.0.0.1:5555", "/test.apk")
        self.assertFalse(any("install" in call.args[0] for call in run.call_args_list))

    @patch("androidbox.adb.run")
    def test_install_failure_retains_device_error(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 1, "", "INSTALL_FAILED_INVALID_APK"),
        ]
        with self.assertRaisesRegex(RuntimeError, "INSTALL_FAILED_INVALID_APK"):
            install_apk("adb", "127.0.0.1:5555", "/test.apk")
