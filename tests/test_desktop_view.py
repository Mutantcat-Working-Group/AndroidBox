"""Check that the window renders the transitions the session reports.

The session tests prove what the state machine decides; these tests prove the
window turns those signals into the screen, labels and actions a user sees.
They drive the slots directly, so no QEMU process or guest image is involved.
"""

import importlib.util
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from androidbox.desktop import MainWindow


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the desktop shell")
class DesktopViewTests(unittest.TestCase):
    def setUp(self):
        self.application = QApplication.instance() or QApplication([])
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        with patch("androidbox.desktop.state_directory", return_value=root), \
                patch("androidbox.runtime.state_directory", return_value=root):
            self.window = MainWindow()
        self.window.show()
        self.addCleanup(self.window.close)

    def fake_server(self):
        class Server:
            url = "http://127.0.0.1:5000/token/display.html"
            closed = False

            def close(self):
                self.closed = True

        return Server()

    def test_started_switches_to_the_guest_screen_with_a_quality_hint(self):
        self.window.session.server = self.fake_server()
        self.window.vm.websocket_port = 5901
        self.window.vm.password = "secret12"
        self.window.on_started("hvf")
        self.assertEqual(self.window.stack.currentIndex(), 1)
        url = self.window.view.url().toString()
        self.assertIn("http://127.0.0.1:5000/token/display.html", url)
        self.assertIn("#port=5901", url)
        self.assertIn("password=secret12", url)
        self.assertIn("quality=6", url)
        self.assertIn("QEMU running", self.window.log.toPlainText())

    def test_a_stopped_guest_returns_to_the_empty_state_with_the_exit_code(self):
        self.window.on_started("tcg")
        self.window.on_stopped(3)
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertEqual(self.window.empty_status.text(), "QEMU exited (3)")

    def test_a_clean_stop_is_reported_as_stopped(self):
        self.window.on_started("tcg")
        self.window.on_stopped(0)
        self.assertEqual(self.window.empty_status.text(), "Stopped")

    def test_a_recovery_announces_itself_before_the_restart(self):
        self.window.on_restarting(2, 5)
        self.assertEqual(self.window.empty_status.text(), "Recovering the guest...")

    def test_a_failed_start_returns_to_the_empty_state(self):
        self.window.on_started("tcg")
        with patch.object(self.window, "report_error") as report:
            self.window.on_failed("Start failed", ValueError("missing firmware"), "start")
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertEqual(self.window.empty_status.text(), "Start failed")
        self.assertIn("missing firmware", self.window.log.toPlainText())
        report.assert_called_once()

    def test_the_preview_closes_when_the_guest_stops(self):
        class Preview:
            closed = False

            def close(self):
                self.closed = True

        preview = Preview()
        self.window.preview = preview
        self.window.on_stopped(0)
        self.assertTrue(preview.closed)
        self.assertIsNone(self.window.preview)


if __name__ == "__main__":
    unittest.main()
