import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from concurrent.futures import Future
from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to exercise the guest watchdog")
class GuestRecoveryTests(unittest.TestCase):
    def build_window(self, directory):
        from PySide6.QtWidgets import QApplication
        from androidbox.desktop import MainWindow

        application = QApplication.instance() or QApplication([])
        with patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)), \
                patch("androidbox.desktop.DisplayServer"), \
                patch("androidbox.power._spawn", return_value=None):
            window = MainWindow()
        self.addCleanup(window.close)
        disk = Path(directory) / "guest.raw"
        disk.write_bytes(b"guest disk")
        window.config = replace(window.config, disk=str(disk), disk_format="raw")
        return application, window

    def exited(self, window, code=1):
        """Leave the window looking as if QEMU had just left with a status."""
        window.vm.process = SimpleNamespace(poll=lambda: code, returncode=code)

    def test_a_guest_that_exits_on_its_own_is_started_again(self):
        from androidbox import desktop

        with tempfile.TemporaryDirectory() as directory:
            application, window = self.build_window(directory)
            window.was_running = True
            window.shutdown_requested = False
            self.exited(window)
            with patch.object(window, "start_vm") as start:
                window.poll()
                self.assertEqual(start.call_count, 1)
                self.assertEqual(window.restarts, 1)
                self.assertTrue(window.recovering)
                self.assertIn("restarting the guest", window.log.toPlainText())
                # A host that keeps dropping the guest gets a bounded budget.
                for _ in range(desktop.MAX_GUEST_RESTARTS - 1):
                    window.was_running = True
                    window.poll()
                self.assertEqual(start.call_count, desktop.MAX_GUEST_RESTARTS)
                self.assertEqual(window.restarts, desktop.MAX_GUEST_RESTARTS)
                # The budget spent, control returns to the user.
                window.was_running = True
                window.poll()
                self.assertEqual(start.call_count, desktop.MAX_GUEST_RESTARTS)
            self.assertIn("press Start to try again", window.log.toPlainText())
            self.assertEqual(window.empty_status.text(), "QEMU exited (1)")
            self.assertIsNotNone(application)

    def test_a_guest_the_user_shut_down_is_left_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            application, window = self.build_window(directory)
            window.was_running = True
            window.shutdown_requested = True
            self.exited(window)
            with patch.object(window, "start_vm") as start:
                window.poll()
                self.assertFalse(start.called)
            self.assertEqual(window.restarts, 0)
            self.assertEqual(window.empty_status.text(), "QEMU exited (1)")
            self.assertIsNotNone(application)

    def test_a_clean_shutdown_is_not_a_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            application, window = self.build_window(directory)
            window.was_running = True
            window.shutdown_requested = False
            self.exited(window, code=0)
            with patch.object(window, "start_vm") as start:
                window.poll()
                self.assertFalse(start.called)
            self.assertEqual(window.empty_status.text(), "Stopped")
            self.assertIsNotNone(application)

    def test_a_recovery_keeps_the_budget_a_fresh_start_clears_it(self):
        with tempfile.TemporaryDirectory() as directory:
            application, window = self.build_window(directory)
            with patch.object(window.pool, "submit", return_value=None):
                window.restarts = 3
                window.recovering = True
                window.start_vm()
                self.assertEqual(window.restarts, 3)
                # A start the user asked for begins a new budget.
                window.restarts = 4
                window.start_vm()
                self.assertEqual(window.restarts, 0)
                self.assertFalse(window.recovering)
            self.assertIsNotNone(application)

    def test_an_operation_in_flight_is_not_interrupted_by_a_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            application, window = self.build_window(directory)
            window.future = Future()
            window.operation = "start"
            with patch.object(window, "start_vm") as start:
                window.recover_guest(1)
                self.assertFalse(start.called)
            window.future = None
            self.assertIsNotNone(application)


if __name__ == "__main__":
    unittest.main()
