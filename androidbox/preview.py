"""Show the guest camera bridge picture inside the desktop client.

The guest bridge serves the same JPEG it writes to the V4L2 loopback device
over HTTP on 7101. QEMU forwards that port to the host, so the client can show
the picture without opening a browser inside the guest - the stock image ships
no browser at all. A small worker fetches the snapshot endpoint and the window
only decodes the newest frame, which keeps a closed dialog from leaving a
network reply pointed at a deleted widget.
"""

import threading
import urllib.request

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from . import APP_NAME


# The worker asks a live bridge often and backs off while the guest is still
# booting; the window drains whatever arrived a few times a second.
LIVE_INTERVAL_SECONDS = 0.15
WAITING_INTERVAL_SECONDS = 0.75
VIEW_POLL_MS = 60
REQUEST_TIMEOUT_SECONDS = 2.0
WAITING_TEXT = "Waiting for the guest camera bridge..."
OLD_GUEST_HINT = (
    "If the guest has not rebooted since the last update, restart it so the "
    "current camera bridge installs."
)


class SnapshotSource:
    """Fetch the guest snapshot endpoint on a worker thread.

    The thread owns its HTTP request, so closing the window only has to stop
    the loop; no Qt network reply outlives the widget that started it.
    """

    def __init__(self, port, live_interval=LIVE_INTERVAL_SECONDS,
                 waiting_interval=WAITING_INTERVAL_SECONDS):
        self.url = f"http://127.0.0.1:{int(port)}/snapshot.jpg"
        self.live_interval = live_interval
        self.waiting_interval = waiting_interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._version = 0
        self._seen = 0
        self._frame = None
        self._error = ""

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=REQUEST_TIMEOUT_SECONDS + 0.5)

    def take(self):
        """Return (frame, error) once per new attempt, or None when unchanged."""
        with self._lock:
            if self._version == self._seen:
                return None
            self._seen = self._version
            return self._frame, self._error

    def _run(self):
        while not self._stop.is_set():
            frame, error = None, ""
            try:
                with urllib.request.urlopen(self.url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    frame = response.read()
                if not frame:
                    error = "The guest returned no camera frame yet"
            except Exception as failure:  # noqa: BLE001 - the loop must survive a broken guest
                error = getattr(failure, "reason", None) or str(failure) or "The guest is not reachable"
            with self._lock:
                self._frame = frame
                self._error = str(error)
                self._version += 1
            self._stop.wait(self.live_interval if frame else self.waiting_interval)


class CameraPreview(QDialog):
    """A window showing the picture the guest camera bridge just received."""

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Camera preview")
        self.setMinimumSize(480, 380)
        self.resize(680, 540)
        self.port = int(port)
        self.source = SnapshotSource(self.port)
        self._last_pixmap = None
        self.image = QLabel(WAITING_TEXT)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(320, 240)
        self.image.setStyleSheet("background: #0b1220; color: #d5dcdf;")
        self.status = QLabel(f"http://127.0.0.1:{self.port}/")
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.image, 1)
        layout.addWidget(self.status)
        self._timer = QTimer(self)
        self._timer.setInterval(VIEW_POLL_MS)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.source.start()
        self._timer.start()

    def closeEvent(self, event):
        self._timer.stop()
        self.source.stop()
        super().closeEvent(event)

    def refresh(self):
        """Apply the newest fetch to the window, when one has arrived."""
        update = self.source.take()
        if update is None:
            return
        frame, error = update
        if error or not frame:
            self._waiting_for(error or "The guest returned no camera frame yet")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame, "JPG"):
            self._waiting_for("The guest sent a frame this client cannot decode")
            return
        self._last_pixmap = pixmap
        self.status.setText(f"Live from the guest camera bridge (port {self.port})")
        self._apply(pixmap)

    def _waiting_for(self, reason):
        self.status.setText(f"{WAITING_TEXT} {reason}\n{OLD_GUEST_HINT}")
        if self._last_pixmap is None:
            self.image.clear()
            self.image.setText(WAITING_TEXT)

    def _apply(self, pixmap):
        self.image.setText("")
        self.image.setPixmap(pixmap.scaled(
            self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_pixmap is not None:
            self._apply(self._last_pixmap)
