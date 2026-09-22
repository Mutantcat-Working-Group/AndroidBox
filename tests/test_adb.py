import subprocess
import unittest
from unittest.mock import patch

from androidbox.adb import install_apk, push_file, transfer_files


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


class TransferTests(unittest.TestCase):
    @patch("androidbox.adb.run")
    def test_push_file_lands_in_the_download_directory(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "1 file pushed", "")
        push_file("adb", "127.0.0.1:5555", "/tmp/holiday photo.jpg")
        self.assertEqual(run.call_args.args[0],
                         ["adb", "-s", "127.0.0.1:5555", "push", "/tmp/holiday photo.jpg",
                          "/sdcard/Download/holiday photo.jpg"])

    @patch("androidbox.adb.run")
    def test_transfer_pushes_every_file_then_installs_apks(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "1 file pushed", ""),
            subprocess.CompletedProcess([], 0, "1 file pushed", ""),
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "Success\n", ""),
        ]
        summary = transfer_files("adb", "127.0.0.1:5555", ["/tmp/photo.jpg", "/tmp/app.apk"])
        self.assertEqual(summary, "Uploaded 2 file(s) to /sdcard/Download; "
                                  "installed 1 package(s): app.apk")
        self.assertEqual(run.call_args_list[-1].args[0],
                         ["adb", "-s", "127.0.0.1:5555", "install", "-r", "/tmp/app.apk"])

    @patch("androidbox.adb.run")
    def test_transfer_installs_an_uppercase_apk_suffix(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "1 file pushed", ""),
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "Success\n", ""),
        ]
        transfer_files("adb", "127.0.0.1:5555", ["/tmp/GAME.APK"])
        self.assertEqual(run.call_args_list[-1].args[0],
                         ["adb", "-s", "127.0.0.1:5555", "install", "-r", "/tmp/GAME.APK"])

    @patch("androidbox.adb.run")
    def test_transfer_reports_progress_per_file(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "1 file pushed", ""),
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "Success\n", ""),
        ]
        messages = []
        transfer_files("adb", "127.0.0.1:5555", ["/tmp/app.apk"], progress=messages.append)
        self.assertEqual(messages, ["Uploading app.apk...", "Installing app.apk..."])

    @patch("androidbox.adb.run")
    def test_transfer_keeps_going_after_a_failure(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 1, "", "Read-only file system"),
            subprocess.CompletedProcess([], 0, "1 file pushed", ""),
        ]
        with self.assertRaisesRegex(RuntimeError, "Read-only file system"):
            transfer_files("adb", "127.0.0.1:5555", ["/tmp/bad.bin", "/tmp/ok.bin"])
        self.assertEqual(len(run.call_args_list), 4)
        self.assertIn("push", run.call_args_list[-1].args[0])
