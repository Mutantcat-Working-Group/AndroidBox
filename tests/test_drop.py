import importlib.util
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from concurrent.futures import Future
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication, QWidget

    from androidbox.desktop import DisplayView, MainWindow, shield_drag_and_drop


def drag_enter(mime):
    return QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)


def drop(mime):
    return QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, QEvent.Type.Drop)


def files_mime(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


class FakeProcess:
    """A process that only ever reports itself as alive."""

    def poll(self):
        return None


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the desktop shell")
class DropTests(unittest.TestCase):
    def setUp(self):
        self.application = QApplication.instance() or QApplication([])

    def make_window(self, directory):
        with patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.guestdisk.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)):
            window = MainWindow()
            window.show()
            return window

    def close_window(self, window):
        window.vm.process = None
        window.close()

    def test_dropped_files_are_uploaded_and_apks_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "sample.apk"
            apk.write_bytes(b"apk")
            window = self.make_window(directory)
            window.vm.process = FakeProcess()
            window.vm.adb_port = 5555
            # The mime data must outlive the event that borrows it.
            mime = files_mime([apk])
            with patch("androidbox.desktop.adb_executable", return_value="adb"), \
                    patch("androidbox.desktop.transfer_files",
                          return_value="Uploaded 1 file(s) to /sdcard/Download") as transfer, \
                    patch.object(window, "report") as report:
                window.dropEvent(drop(mime))
                self.assertEqual(window.operation, "upload")
                window.future.result(timeout=10)
            # No event loop runs here, so the poll timer cannot clear the
            # finished future and closeEvent would block on its modal box.
            window.future = None
            self.assertEqual(transfer.call_args.args[0], "adb")
            self.assertEqual(transfer.call_args.args[1], "127.0.0.1:5555")
            self.assertEqual(transfer.call_args.args[2], [str(apk)])
            self.assertIn("Uploading", report.call_args_list[0].args[0])
            self.close_window(window)

    def test_dropped_directories_are_not_uploaded(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "folder"
            folder.mkdir()
            window = self.make_window(directory)
            window.vm.process = FakeProcess()
            mime = files_mime([folder])
            window.dropEvent(drop(mime))
            self.assertIsNone(window.future)
            self.close_window(window)

    def test_drop_is_refused_while_the_guest_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "sample.apk"
            apk.write_bytes(b"apk")
            window = self.make_window(directory)
            mime = files_mime([apk])
            with patch("androidbox.desktop.QMessageBox.warning") as warning:
                window.dropEvent(drop(mime))
            self.assertTrue(warning.called)
            self.assertIsNone(window.future)
            self.close_window(window)

    def test_drop_waits_for_the_running_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "sample.apk"
            apk.write_bytes(b"apk")
            window = self.make_window(directory)
            window.vm.process = FakeProcess()
            window.future = Future()
            window.operation = "stop"
            mime = files_mime([apk])
            with patch("androidbox.desktop.QMessageBox.warning") as warning:
                window.dropEvent(drop(mime))
            self.assertTrue(warning.called)
            self.assertIsInstance(window.future, Future)
            window.future = None
            self.close_window(window)

    def test_drag_enter_accepts_files_but_not_plain_text(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "sample.apk"
            apk.write_bytes(b"apk")
            window = self.make_window(directory)
            mime = files_mime([apk])
            enter = drag_enter(mime)
            window.dragEnterEvent(enter)
            self.assertTrue(enter.isAccepted())
            text = QMimeData()
            text.setText("hello")
            plain = drag_enter(text)
            window.dragEnterEvent(plain)
            self.assertFalse(plain.isAccepted())
            self.close_window(window)

    def test_window_accepts_drops_but_screen_and_log_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(directory)
            self.assertTrue(window.acceptDrops())
            self.assertFalse(window.view.acceptDrops())
            self.assertFalse(window.log.acceptDrops())
            self.close_window(window)

    def test_display_view_never_accepts_drops(self):
        view = DisplayView()
        self.assertFalse(view.acceptDrops())
        mime = files_mime([])
        dropped = drop(mime)
        view.dropEvent(dropped)
        self.assertFalse(dropped.isAccepted())
        entered = drag_enter(mime)
        view.dragEnterEvent(entered)
        self.assertFalse(entered.isAccepted())

    def test_shield_drag_and_drop_disables_accepting_widgets(self):
        parent = QWidget()
        child = QWidget(parent)
        child.setAcceptDrops(True)
        shield_drag_and_drop(parent)
        self.assertFalse(parent.acceptDrops())
        self.assertFalse(child.acceptDrops())
