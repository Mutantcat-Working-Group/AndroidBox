"""Send the host webcam to the camera app running inside the guest.

QEMU forwards the camera frames over the user-mode network to the guest-side
camera bridge, which writes them into a V4L2 loopback node that Android reads
as its camera. Frames come from Qt's own camera stack, so the same code drives
a FaceTime HD camera on macOS, a UVC webcam on Windows and a V4L2 device on
Linux. The encoder only needs QtGui, which every platform has; the camera
itself comes from QtMultimedia, which is normally present but not guaranteed.
"""

import time
import sys


try:
    from PySide6.QtCore import (QBuffer, QCameraPermission, QCoreApplication, QIODevice,
                                QObject, Qt, QTimer, Signal)
    from PySide6.QtGui import QImage
    from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
    from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink

    CAMERA_STACK = True
except ImportError:  # pragma: no cover - QtMultimedia is optional
    CAMERA_STACK = False


# A webcam sends more frames than an Android display can use, and every frame
# is encoded and pushed to the guest over TCP.
FRAME_INTERVAL = 1.0 / 15
MAX_FRAME_WIDTH = 640
JPEG_QUALITY = 70
MAX_CAMERA_RECONNECTS = 5
CAMERA_RECONNECT_DELAY_MS = 1500
CAMERA_STABLE_CONNECTION_SECONDS = 10.0
CAMERA_PERMISSION_DENIED = (
    "Camera permission denied. Allow AndroidBox in System Settings > "
    "Privacy & Security > Camera, then restart AndroidBox."
)


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
            self.capture = None
            self.sink = None
            self.sent = 0
            self._previous_frame = 0.0
            self._reconnect_attempts = 0
            self._connected_at = 0.0
            self._pending_device = None
            self.socket = QTcpSocket(self)
            self.socket.connected.connect(self._connected)
            self.socket.disconnected.connect(self._disconnected)

        @property
        def running(self):
            return self.camera is not None or self._pending_device is not None

        def start(self):
            """Attach to the host webcam; False when this host has none."""
            if self.camera is not None or self._pending_device is not None:
                return True
            device = QMediaDevices.defaultVideoInput()
            if device.isNull():
                self.status.emit("Camera is off: this host reports no video input device")
                return False
            self.device = device.description()
            permission = self._request_camera_permission(device)
            if permission is False:
                return False
            if permission is None:
                return True
            self._start_capture(device)
            return True

        def _start_capture(self, device):
            if self.camera is not None:
                return
            self.sink = QVideoSink(self)
            self.sink.videoFrameChanged.connect(self.send_frame)
            # QCamera has no video sink of its own, so the frames flow through
            # a capture session that owns both the camera and the sink.
            self.camera = QCamera(device, self)
            self.capture = QMediaCaptureSession(self)
            self.capture.setCamera(self.camera)
            self.capture.setVideoSink(self.sink)
            self.camera.errorOccurred.connect(self._camera_error)
            self._reconnect_attempts = 0
            self._connected_at = 0.0
            self.socket.connectToHost("127.0.0.1", self.port)
            self.camera.start()
            self.status.emit(f"Starting host camera: {self.device}")

        def _request_camera_permission(self, device):
            """Return True when capture may start, False when denied, None while asking."""
            if sys.platform != "darwin":
                return True
            application = QCoreApplication.instance()
            if application is None:
                return True
            permission = QCameraPermission()
            status = application.checkPermission(permission)
            if status == Qt.PermissionStatus.Granted:
                return True
            if status == Qt.PermissionStatus.Denied:
                self.status.emit(CAMERA_PERMISSION_DENIED)
                return False
            self._pending_device = device
            self.status.emit("Waiting for macOS camera permission")
            application.requestPermission(permission, self, self._camera_permission_result)
            return None

        def _camera_permission_result(self, permission):
            device, self._pending_device = self._pending_device, None
            if device is None:
                return
            application = QCoreApplication.instance()
            status = (application.checkPermission(permission) if application is not None
                      else Qt.PermissionStatus.Denied)
            if status == Qt.PermissionStatus.Granted:
                self._start_capture(device)
            elif status == Qt.PermissionStatus.Denied:
                self.status.emit(CAMERA_PERMISSION_DENIED)
            else:
                self.status.emit("Camera permission was not granted; camera preview is unavailable")

        def stop(self):
            """Release the webcam and the connection to the guest."""
            self._release_camera()
            self._reconnect_attempts = 0
            self._connected_at = 0.0
            self.status.emit("Camera stopped")

        def _release_camera(self):
            self._pending_device = None
            if self.camera is not None:
                self.camera.stop()
                self.camera.deleteLater()
                self.camera = None
            if self.capture is not None:
                self.capture.deleteLater()
                self.capture = None
            self.sink = None
            self.socket.abort()

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
                if self.sent == 0:
                    self.status.emit(f"Camera streaming into the guest: {self.device}")
                self.sent += 1

        def _connected(self):
            self._connected_at = time.monotonic()
            self.status.emit(f"Camera connected to the guest: {self.device}")

        def _disconnected(self):
            if self.camera is None:
                return
            if (self._connected_at
                    and time.monotonic() - self._connected_at >= CAMERA_STABLE_CONNECTION_SECONDS):
                self._reconnect_attempts = 0
            self._reconnect_attempts += 1
            if self._reconnect_attempts > MAX_CAMERA_RECONNECTS:
                self.status.emit(
                    "Camera bridge stopped responding after "
                    f"{MAX_CAMERA_RECONNECTS} reconnects; camera preview is unavailable"
                )
                self._release_camera()
                return
            self.status.emit(
                "The guest camera bridge closed; reconnecting "
                f"({self._reconnect_attempts} of {MAX_CAMERA_RECONNECTS})"
            )
            QTimer.singleShot(CAMERA_RECONNECT_DELAY_MS, self._connect)

        def _connect(self):
            if self.camera is not None and self._pending_device is None:
                self.socket.connectToHost("127.0.0.1", self.port)

        def _camera_error(self, error, message):
            if self.camera is None:
                return
            text = str(message).strip() or "Unknown camera error"
            self._release_camera()
            if sys.platform == "darwin" and "not granted" in text.lower():
                self.status.emit(CAMERA_PERMISSION_DENIED)
            else:
                self.status.emit(f"Camera error: {text}")

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
