"""Send the host webcam to the camera app running inside the guest.

QEMU forwards the camera frames over the user-mode network to the guest-side
camera bridge, which writes them into a V4L2 loopback node that Android reads
as its camera. Frames come from Qt's own camera stack, so the same code drives
a FaceTime HD camera on macOS, a UVC webcam on Windows and a V4L2 device on
Linux. The encoder only needs QtGui, which every platform has; the camera
itself comes from QtMultimedia, which is normally present but not guaranteed.
"""

import time


try:
    from PySide6.QtCore import QBuffer, QIODevice, QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QImage
    from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
    from PySide6.QtMultimedia import QCamera, QMediaDevices, QVideoSink

    CAMERA_STACK = True
except ImportError:  # pragma: no cover - QtMultimedia is optional
    CAMERA_STACK = False


# A webcam sends more frames than an Android display can use, and every frame
# is encoded and pushed to the guest over TCP.
FRAME_INTERVAL = 1.0 / 15
MAX_FRAME_WIDTH = 640
JPEG_QUALITY = 70


def encode_frame(image, quality=JPEG_QUALITY, max_width=MAX_FRAME_WIDTH):
    """Return one camera frame as JPEG bytes, downsized when it is too wide."""
    if image is None or image.isNull():
        return b""
    if max_width and image.width() > max_width:
        image = image.scaledToWidth(max_width, Qt.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not image.save(buffer, "JPG", quality):
            return b""
        return bytes(buffer.data())
    finally:
        buffer.close()


def host_camera_names():
    """Return the descriptions of the host video input devices."""
    if not CAMERA_STACK:
        return []
    return [device.description() for device in QMediaDevices.videoInputs()]


if CAMERA_STACK:

    class CameraStreamer(QObject):
        """Stream the host webcam into the guest camera bridge."""

        status = Signal(str)

        def __init__(self, port, parent=None):
            super().__init__(parent)
            self.port = int(port)
            self.device = ""
            self.camera = None
            self.sink = None
            self.sent = 0
            self._previous_frame = 0.0
            self.socket = QTcpSocket(self)
            self.socket.connected.connect(self._connected)
            self.socket.disconnected.connect(self._disconnected)

        @property
        def running(self):
            return self.camera is not None

        def start(self):
            """Attach to the host webcam; False when this host has none."""
            if self.camera is not None:
                return True
            device = QMediaDevices.defaultVideoInput()
            if device.isNull():
                self.status.emit("Camera is off: this host reports no video input device")
                return False
            self.device = device.description()
            self.sink = QVideoSink(self)
            self.sink.videoFrameChanged.connect(self.send_frame)
            self.camera = QCamera(device, self)
            self.camera.errorOccurred.connect(self._camera_error)
            self.camera.setVideoSink(self.sink)
            self.socket.connectToHost(QAbstractSocket.LocalHost, self.port)
            self.camera.start()
            self.status.emit(f"Camera streaming into the guest: {self.device}")
            return True

        def stop(self):
            """Release the webcam and the connection to the guest."""
            if self.camera is not None:
                self.camera.stop()
                self.camera.deleteLater()
                self.camera = None
            self.sink = None
            self.socket.abort()
            self.status.emit("Camera stopped")

        def send_frame(self, video_frame):
            """Encode one frame and push it to the guest, at a modest rate."""
            if self.camera is None or self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
                return
            now = time.monotonic()
            if now - self._previous_frame < FRAME_INTERVAL:
                return
            self._previous_frame = now
            payload = encode_frame(video_frame.toImage())
            if payload:
                self.socket.write(payload)
                self.sent += 1

        def _connected(self):
            self.status.emit(f"Camera connected to the guest: {self.device}")

        def _disconnected(self):
            if self.camera is None:
                return
            self.status.emit("The guest camera bridge closed; reconnecting")
            QTimer.singleShot(1500, self._connect)

        def _connect(self):
            if self.camera is not None:
                self.socket.connectToHost(QAbstractSocket.LocalHost, self.port)

        def _camera_error(self, error, message):
            if self.camera is not None:
                self.status.emit(f"Camera error: {message}")

else:

    class CameraStreamer:
        """Placeholder used where QtMultimedia is unavailable."""

        status = None

        def __init__(self, port=None, parent=None):
            self.port = port
            self.camera = None
            self.device = ""
            self.sent = 0

        @property
        def running(self):
            return False

        def start(self):
            return False

        def stop(self):
            pass
