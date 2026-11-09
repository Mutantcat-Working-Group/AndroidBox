"""Exercise the in-client camera preview against a real local HTTP server.

The guest bridge is a plain snapshot endpoint, so the preview can be tested
without QEMU: a local server returns one JPEG, the dialog polls it, and the
label ends up holding the decoded frame. A closed port proves the waiting
state that an older or still-booting guest produces.
"""

import importlib.util
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from androidbox.preview import CameraPreview, WAITING_TEXT

REPO = Path(__file__).resolve().parent.parent


def jpeg_frame():
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        image.save(buffer, "JPG")
        return bytes(buffer.data())
    finally:
        buffer.close()


def unused_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def pump(application, predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    application.processEvents()
    return predicate()


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the camera preview")
class CameraPreviewTests(unittest.TestCase):
    def setUp(self):
        self.application = QApplication.instance() or QApplication([])
        self.frame = jpeg_frame()

    def serve(self):
        payload = self.frame

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if not self.path.startswith("/snapshot.jpg"):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 3)
        return server.server_address[1]

    def preview(self, port):
        preview = CameraPreview(port)
        self.addCleanup(preview.close)
        preview.show()
        return preview

    def test_a_snapshot_becomes_the_picture_in_the_window(self):
        preview = self.preview(self.serve())
        preview.refresh()
        self.assertTrue(pump(self.application,
                             lambda: preview.image.pixmap() is not None
                             and not preview.image.pixmap().isNull()))
        self.assertIn("Live from the guest camera bridge", preview.status.text())
        self.assertIn(str(preview.port), preview.status.text())

    def test_a_bridge_that_is_not_there_yet_keeps_the_window_waiting(self):
        preview = self.preview(unused_port())
        preview.refresh()
        self.assertTrue(pump(self.application,
                             lambda: WAITING_TEXT in preview.status.text()))
        self.assertIn("restart it", preview.status.text())
        self.assertTrue(preview.image.pixmap().isNull())

    def test_a_late_bridge_starts_the_picture_without_reopening_the_window(self):
        port = unused_port()
        preview = self.preview(port)
        preview.refresh()
        self.assertTrue(pump(self.application,
                             lambda: WAITING_TEXT in preview.status.text()))
        # Bind the same port after the first failures, like a guest that has
        # just finished booting and started its bridge.
        payload = self.frame

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 3)
        preview.refresh()
        self.assertTrue(pump(self.application,
                             lambda: preview.image.pixmap() is not None
                             and not preview.image.pixmap().isNull()))
        self.assertIn("Live", preview.status.text())


if __name__ == "__main__":
    unittest.main()
