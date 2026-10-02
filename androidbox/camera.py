"""Send the host webcam into the guest.

QEMU forwards the frames over the user-mode network to the guest-side camera
bridge, which writes them into a V4L2 loopback node and serves the same
picture to any guest browser over HTTP. Frames come from Qt's own camera
stack, so the same code drives a FaceTime HD camera on macOS, a UVC webcam on
Windows and a V4L2 device on Linux. The encoder only needs QtGui, which every
platform has; the camera itself comes from QtMultimedia, which is normally
present but not guaranteed.

QEMU owns the forwarded port the moment it starts, long before the guest
listens on it, and it answers a connect before anything on the far side is
listening. The host therefore leaves the webcam switched off until the guest
bridge greets it: a link that opens and closes again without ever answering is
a guest that is still booting, which is a wait, not a failure.
"""

import re
import sys
import tempfile
import threading
import time
from pathlib import Path


try:
    from PySide6.QtCore import (QBuffer, QCameraPermission, QCoreApplication, QIODevice,
                                QObject, Qt, QTimer, Signal, QUrl)
    from PySide6.QtGui import QImage
    from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
    from PySide6.QtMultimedia import (QCamera, QMediaCaptureSession, QMediaDevices,
                                      QMediaRecorder, QVideoSink)

    CAMERA_STACK = True
except ImportError:  # pragma: no cover - QtMultimedia is optional
    CAMERA_STACK = False


from .process import run


# A webcam sends more frames than a guest display can use, and every frame is
# encoded and pushed to the guest over TCP.
FRAME_INTERVAL = 1.0 / 15
MAX_FRAME_WIDTH = 640
JPEG_QUALITY = 70

# The guest bridge answers the host the instant it accepts a connection. A TCP
# connect alone only proves that QEMU is alive, so the host waits for this
# greeting before it switches the webcam on; a guest provisioned by an older
# release sends nothing and is streamed to anyway once the grace runs out.
CAMERA_GREETING = b"ANDROIDBOX-CAMERA-1\n"
CAMERA_GREETING_GRACE = 90.0
CAMERA_GREETING_FALLBACK = (
    "The guest camera bridge never greeted the host; streaming to it anyway"
)
MAX_CAMERA_RECONNECTS = 5
CAMERA_RECONNECT_DELAY_MS = 1500
CAMERA_STABLE_CONNECTION_SECONDS = 10.0
CAMERA_WAIT_REPORT_SECONDS = 20.0
# The bridge serves the same picture over HTTP on the Waydroid bridge address,
# which the guest browser can open even though the Android image has no camera
# HAL and so no Android camera app can enumerate a device.
CAMERA_PREVIEW_HOST = "192.168.240.1"
CAMERA_PREVIEW_PORT = 7101
CAMERA_PREVIEW_URL = f"http://{CAMERA_PREVIEW_HOST}:{CAMERA_PREVIEW_PORT}/"
GUEST_CAMERA_HAL_MISSING = (
    "The bundled Android image provides no camera HAL, so Android camera apps see no "
    "device. The webcam picture reaches the Ubuntu support layer instead, where the "
    "guest browser shows it at " + CAMERA_PREVIEW_URL
)
CAMERA_WAITING_FOR_GUEST = "Waiting for the guest camera bridge to come up"
CAMERA_PERMISSION_DENIED = (
    "Camera permission denied. Allow AndroidBox in System Settings > "
    "Privacy & Security > Camera, then restart AndroidBox."
)


class GuestLink:
    """Follow the guest camera bridge as it comes and goes.

    QEMU accepts every connection the host makes to a forwarded port, so a link
    that opens and closes again can mean nothing more than a guest that is still
    booting. Punishing that with a retry budget kills the camera before the
    guest is awake, so only a bridge that answered is held to the budget.
    """

    def __init__(self, max_reconnects=MAX_CAMERA_RECONNECTS,
                 stable_seconds=CAMERA_STABLE_CONNECTION_SECONDS):
        self.max_reconnects = max_reconnects
        self.stable_seconds = stable_seconds
        self.attempts = 0
        self.confirmed = False
        self.connected_at = 0.0
        self.open = False

    def reset(self):
        """Forget the history of a streamer that starts or stops watching."""
        self.attempts = 0
        self.confirmed = False
        self.connected_at = 0.0
        self.open = False

    def opened(self, now):
        """Note that the host end of the forwarded port took a new link."""
        self.connected_at = now
        self.confirmed = False
        self.open = True

    def greeted(self):
        """Record that the guest bridge answered over the stream."""
        self.confirmed = True

    def closed(self, now):
        """Return (message, keep_waiting) for a link the guest dropped."""
        if not self.open:
            # A close for a link that was never opened, or one already handled:
            # the network stack reports an error and a close for one drop.
            return None, True
        self.open = False
        if not self.confirmed:
            # Nobody on the far side ever spoke, so this was a port with no
            # listener yet. Waiting is free: the host webcam is still off.
            return None, True
        if now - self.connected_at >= self.stable_seconds:
            self.attempts = 0
        self.attempts += 1
        if self.attempts > self.max_reconnects:
            return ("Camera bridge stopped responding after "
                    f"{self.max_reconnects} reconnects; camera preview is unavailable"), False
        return ("The guest camera bridge closed; reconnecting "
                f"({self.attempts} of {self.max_reconnects})"), True


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


def parse_guest_camera_count(output):
    """Return how many camera devices the guest reports, or None when unknown."""
    match = re.search(r"Number of camera devices:\s*(\d+)", output or "")
    return int(match.group(1)) if match else None


if CAMERA_STACK:

    class CameraStreamer(QObject):
        """Stream the host webcam into the guest camera bridge."""

        status = Signal(str)
        frame_ready = Signal(bytes)

        def __init__(self, port, parent=None):
            super().__init__(parent)
            self.port = int(port)
            self.device = ""
            self.camera = None
            self.capture = None
            self.recorder = None
            self.sink = None
            self.sent = 0
            self._previous_frame = 0.0
            self._device = None
            self._greeting_buffer = b""
            self._reconnect_pending = False
            self.link = GuestLink()
            self.adb = None
            self.target = None
            self._probed_guest = False
            self.socket = QTcpSocket(self)
            self.socket.connected.connect(self._connected)
            self.socket.disconnected.connect(self._disconnected)
            self.socket.errorOccurred.connect(self._socket_error)
            self.socket.readyRead.connect(self._read_greeting)
            self.frame_ready.connect(self._write_frame)
            self._greeting_grace = QTimer(self)
            self._greeting_grace.setSingleShot(True)
            self._greeting_grace.timeout.connect(self._greeting_timed_out)
            self._wait_report = QTimer(self)
            self._wait_report.setInterval(int(CAMERA_WAIT_REPORT_SECONDS * 1000))
            self._wait_report.timeout.connect(self._report_waiting)

        def set_guest_probe(self, adb, target):
            """Teach the streamer how to ask the guest what it can see.

            The guest bridge proves only that something is listening on the far
            side; whether Android itself exposes a camera is a separate
            question the streamer reports instead of leaving the user guessing.
            """
            self.adb, self.target = adb, target

        @property
        def running(self):
            return self.camera is not None or self._device is not None

        def start(self):
            """Attach to the host webcam; False when this host has none."""
            if self.camera is not None or self._device is not None:
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
            self._watch_guest(device)
            return True

        def _watch_guest(self, device):
            """Watch the forwarded port until the guest bridge answers."""
            self._device = device
            self.link.reset()
            self._probed_guest = False
            self.status.emit(f"Waiting for the guest camera bridge: {self.device}")
            self._open_connection()
            self._wait_report.start()

        def _open_connection(self):
            self._reconnect_pending = False
            self._greeting_buffer = b""
            if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
                self.socket.abort()
            self.link.opened(time.monotonic())
            self.socket.connectToHost("127.0.0.1", self.port)

        def _connected(self):
            # QEMU accepts the link the moment the port is forwarded, well
            # before the guest bridge listens, so success waits for the bridge
            # to answer instead of for the socket to open.
            self._greeting_grace.start(int(CAMERA_GREETING_GRACE * 1000))

        def _read_greeting(self):
            if self.camera is None and self._device is None:
                return
            data = bytes(self.socket.read(64))
            if not data:
                return
            self._greeting_buffer += data
            if CAMERA_GREETING.startswith(self._greeting_buffer):
                if self._greeting_buffer == CAMERA_GREETING:
                    self._bridge_answered(f"Camera connected to the guest: {self.device}")
                return
            # The far side spoke, but not the greeting: a guest provisioned
            # before the handshake existed. Stream to it as before.
            self._bridge_answered(None)

        def _greeting_timed_out(self):
            if self.camera is None and self._device is None:
                return
            if self._greeting_buffer:
                self._bridge_answered(None)
                return
            self._bridge_answered(CAMERA_GREETING_FALLBACK)

        def _bridge_answered(self, message):
            """Bring the webcam up now that the guest bridge is in play."""
            self._greeting_grace.stop()
            self._wait_report.stop()
            self.link.greeted()
            if message:
                self.status.emit(message)
            self._begin_capture()
            self._probe_guest_camera()

        def _begin_capture(self, device=None):
            if self.camera is not None:
                return
            device = device or self._device
            if device is None:
                return
            self._device = None
            # Qt's FFmpeg media backend only pumps frames into a video sink
            # while the capture session has a recorder attached, and it keeps
            # doing that even for a recorder that never records. Without one
            # the camera starts and stays active while every platform reports
            # zero frames, which looks exactly like a permission problem.
            self.sink = QVideoSink(self)
            self.sink.videoFrameChanged.connect(self.send_frame)
            # QCamera carries no video sink of its own, so the frames flow
            # through a capture session that owns both the camera and the sink.
            self.camera = QCamera(device, self)
            self.capture = QMediaCaptureSession(self)
            self.capture.setCamera(self.camera)
            self.capture.setVideoSink(self.sink)
            self._attach_recorder()
            self.camera.errorOccurred.connect(self._camera_error)
            self._previous_frame = 0.0
            self.sent = 0
            self.camera.start()
            self.status.emit(f"Starting host camera: {self.device}")
            self.status.emit(f"Guest webcam preview: {CAMERA_PREVIEW_URL}")

        def _attach_recorder(self):
            """Keep a dormant recorder on the session so the sink sees frames."""
            self.recorder = QMediaRecorder(self)
            self.recorder.setQuality(QMediaRecorder.Quality.LowQuality)
            self.recorder.setOutputLocation(
                QUrl.fromLocalFile(str(Path(tempfile.gettempdir()) / "androidbox-camera.mp4")))
            self.capture.setRecorder(self.recorder)

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
            self._device = device
            self.status.emit("Waiting for macOS camera permission")
            application.requestPermission(permission, self, self._camera_permission_result)
            return None

        def _camera_permission_result(self, permission):
            if self._device is None:
                return
            application = QCoreApplication.instance()
            status = (application.checkPermission(permission) if application is not None
                      else Qt.PermissionStatus.Denied)
            if status == Qt.PermissionStatus.Granted:
                self._watch_guest(self._device)
            elif status == Qt.PermissionStatus.Denied:
                self._device = None
                self.status.emit(CAMERA_PERMISSION_DENIED)
            else:
                self._device = None
                self.status.emit("Camera permission was not granted; camera preview is unavailable")

        def stop(self):
            """Release the webcam and the connection to the guest."""
            self._release_camera()
            self._greeting_grace.stop()
            self._wait_report.stop()
            self.link.reset()
            self.status.emit("Camera stopped")

        def _release_camera(self):
            self._device = None
            if self.camera is not None:
                self.camera.stop()
                self.camera.deleteLater()
                self.camera = None
            if self.recorder is not None:
                self.recorder.deleteLater()
                self.recorder = None
            if self.capture is not None:
                self.capture.deleteLater()
                self.capture = None
            self.sink = None
            self.socket.abort()

        def send_frame(self, video_frame):
            """Encode one frame in the camera thread and hand it to the socket.

            QTcpSocket belongs to the thread that created it, so a frame only
            crosses to that thread once it is JPEG bytes.
            """
            if self.camera is None:
                return
            now = time.monotonic()
            if now - self._previous_frame < FRAME_INTERVAL:
                return
            self._previous_frame = now
            payload = encode_frame(video_frame.toImage())
            if payload:
                self.frame_ready.emit(payload)

        def _write_frame(self, payload):
            if self.camera is None or self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
                return
            self.socket.write(payload)
            if self.sent == 0:
                self.status.emit(f"Camera streaming into the guest: {self.device}")
            self.sent += 1

        def _probe_guest_camera(self):
            if self._probed_guest or not self.adb or not self.target:
                return
            self._probed_guest = True
            threading.Thread(target=self._run_guest_camera_probe, daemon=True).start()

        def _run_guest_camera_probe(self):
            if not self.adb or not self.target:
                return
            try:
                result = run([self.adb, "-s", self.target, "shell", "dumpsys",
                              "media.camera"], timeout=20)
            except Exception:
                return
            count = parse_guest_camera_count(result.stdout)
            if count == 0:
                self.status.emit(GUEST_CAMERA_HAL_MISSING)
            elif count:
                self.status.emit(f"The guest exposes {count} camera device(s) to Android")

        def _disconnected(self):
            if self.camera is None and self._device is None:
                return
            self._greeting_grace.stop()
            message, keep = self.link.closed(time.monotonic())
            if message:
                self.status.emit(message)
            if not keep:
                self._give_up()
                return
            self._schedule_reconnect()

        def _socket_error(self, error):
            if self.camera is None and self._device is None:
                return
            if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
                # The forwarded port is not up yet, or the bridge went away:
                # both look like an error on the way to the close.
                self._disconnected()

        def _schedule_reconnect(self):
            if self._reconnect_pending:
                return
            self._reconnect_pending = True
            QTimer.singleShot(CAMERA_RECONNECT_DELAY_MS, self._open_connection)

        def _report_waiting(self):
            if self.camera is not None or self._device is None:
                return
            self.status.emit(CAMERA_WAITING_FOR_GUEST)

        def _give_up(self):
            self._release_camera()
            self._wait_report.stop()
            self._greeting_grace.stop()
            self.link.reset()

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
