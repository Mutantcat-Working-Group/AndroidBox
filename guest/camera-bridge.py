"""Feed the guest loopback camera from the frames the host streams over TCP.

Runs inside the Ubuntu support layer only. One ffmpeg process turns MJPEG
frames into a V4L2 stream and writes them to the loopback camera device, while
this script decides what goes into that pipe: the frames the host sends over
port 7100 while a webcam is attached, or a still test pattern while it sends
nothing. The bridge also serves the same picture over HTTP on port 7101, so a
guest browser can show the webcam even though the Android image ships no camera
HAL and no camera app can enumerate a device. Only the guest standard library
is used, because the guest receives this file from the seed.

The host cannot tell a guest that is still booting from a guest whose bridge is
down, because QEMU answers a forwarded port long before anything in the guest
listens on it. The bridge therefore answers with a greeting the moment it
accepts a connection, which lets the host tell the two apart and keep its
webcam off until there is somebody to stream to.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time

CAMERA_PORT = 7100
PREVIEW_PORT = 7101
CAMERA_GREETING = b"ANDROIDBOX-CAMERA-1\n"
PREVIEW_BOUNDARY = b"androidbox-frame"
# How long a host connection may stay quiet before the bridge drops it, and how
# long the encoder goes without host frames before the test pattern returns.
IDLE_TOLERANCE = 60.0
IDLE_FALLBACK = 5.0
TEST_PATTERN_INTERVAL = 2.0
# Frames the encoder may sit behind the network; a faster host drops the oldest
# frame instead of stalling the link that feeds the loopback camera.
FRAME_QUEUE = 8
STILL_PATTERN = Path("/var/lib/androidbox/camera-pattern.jpg")
PREVIEW_PAGE = b"""<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AndroidBox camera</title>
<style>
html, body { margin: 0; height: 100%; background: #0b1220; }
img { display: block; width: 100%; height: 100%; object-fit: contain; }
</style>
<img id="view" src="stream"
     onerror="this.onerror=null;this.src='snapshot.jpg?'+Date.now()">
"""


class Latest:
    """The newest frame, shared with the HTTP preview."""

    def __init__(self):
        self.lock = threading.Lock()
        self.arrived = threading.Event()
        self.data = b""

    def publish(self, data):
        with self.lock:
            self.data = data
        self.arrived.set()

    def snapshot(self):
        with self.lock:
            return self.data

    def take(self, timeout):
        """Return the newest frame, or None when none arrived in time."""
        if self.arrived.wait(timeout):
            self.arrived.clear()
            return self.snapshot()
        return None


class FrameQueue:
    """A bounded frame queue that drops the oldest frame, not the newest."""

    def __init__(self, size):
        self.queue = queue.Queue(maxsize=size)

    def get(self, timeout):
        """Take the oldest frame, or None when the queue stayed empty."""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def offer(self, item):
        try:
            self.queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            pass


def capture_test_pattern():
    """Render one still frame for hosts without a webcam, once per boot."""
    if STILL_PATTERN.is_file():
        return
    STILL_PATTERN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=1",
                    "-frames:v", "1", str(STILL_PATTERN)], check=False)


def start_encoder(video):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "image2pipe", "-vcodec", "mjpeg", "-i", "pipe:0",
               "-vf", "format=yuv420p", "-f", "v4l2", video]
    return subprocess.Popen(command, stdin=subprocess.PIPE)


class Encoder:
    """Own the ffmpeg process that writes the loopback camera device.

    A device with no reader stalls after a couple of frames, and a video node
    that disappears takes the encoder with it. Both would take the host link
    down with them if the bridge fed ffmpeg directly from the network thread,
    so frames travel through a bounded queue that the writer drains at its own
    pace, restarting the encoder whenever it stops.
    """

    def __init__(self, video, frames, latest):
        self.video = video
        self.frames = frames
        self.latest = latest
        self.process = None
        self.stop = threading.Event()

    def run(self):
        self.restart()
        last_host_frame = 0.0
        last_pattern = 0.0
        while not self.stop.is_set():
            try:
                payload = self.frames.get(timeout=0.2)
            except queue.Empty:
                payload = None
            if payload is not None:
                last_host_frame = time.monotonic()
                last_pattern = 0.0
                if self.write(payload):
                    continue
                self.restart()
                continue
            if time.monotonic() - last_host_frame < IDLE_FALLBACK:
                continue
            now = time.monotonic()
            if now - last_pattern < TEST_PATTERN_INTERVAL:
                continue
            last_pattern = now
            pattern = self.pattern()
            if pattern and not self.write(pattern):
                self.restart()
            elif pattern:
                self.latest.publish(pattern)

    def write(self, payload):
        """Hand one frame to the encoder; False when the encoder is gone."""
        if self.process is None or self.process.poll() is not None:
            return False
        try:
            self.process.stdin.write(payload)
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            return False
        return True

    def restart(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process = None
        print("camera bridge: restarting the frame encoder", file=sys.stderr, flush=True)
        self.process = start_encoder(self.video)

    def pattern(self):
        try:
            return STILL_PATTERN.read_bytes()
        except OSError:
            return None

    def close(self):
        self.stop.set()
        if self.process is not None and self.process.poll() is None:
            self.process.kill()


class PreviewHandler(BaseHTTPRequestHandler):
    """Serve the webcam picture to a guest browser as MJPEG."""

    server_version = "AndroidBoxCamera"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/snapshot.jpg":
            self.serve_snapshot()
        elif route in ("/stream", "/"):
            self.serve_stream()
        else:
            self.send_error(404)

    def serve_snapshot(self):
        frame = self.server.store.snapshot()
        if not frame:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(frame)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_stream(self):
        if self.path.split("?")[0] == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PREVIEW_PAGE)))
            self.end_headers()
            try:
                self.wfile.write(PREVIEW_PAGE)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary="
                         + PREVIEW_BOUNDARY.decode())
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        while True:
            frame = self.server.store.take(1.0)
            if frame is None:
                continue
            try:
                self.wfile.write(b"--" + PREVIEW_BOUNDARY + b"\r\n"
                                 b"Content-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(frame)).encode() + b"\r\n\r\n"
                                 + frame + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return


def start_preview(latest, bind=("0.0.0.0", PREVIEW_PORT)):
    server = ThreadingHTTPServer(bind, PreviewHandler)
    server.store = latest
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def open_listener(port):
    """Bind the camera port, returning None when the guest already took it."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("0.0.0.0", port))
        listener.listen(2)
    except OSError as error:
        print(f"camera bridge: cannot listen on {port}: {error}", file=sys.stderr)
        listener.close()
        return None
    return listener


def serve_connection(connection, frames, latest):
    """Greet one host and publish every frame it sends until it goes quiet."""
    try:
        connection.sendall(CAMERA_GREETING)
    except OSError:
        return
    connection.settimeout(0.5)
    last_host_frame = time.monotonic()
    while True:
        try:
            payload = connection.recv(262144)
        except socket.timeout:
            if time.monotonic() - last_host_frame > IDLE_TOLERANCE:
                break
            continue
        except OSError:
            break
        if not payload:
            break
        frames.offer(payload)
        latest.publish(payload)
        last_host_frame = time.monotonic()


def serve_camera(frames, latest, listener=None, stop=None):
    """Accept host connections, greet them, and publish their frames."""
    if listener is None:
        listener = open_listener(CAMERA_PORT)
        if listener is None:
            return False
    listener.settimeout(0.5)
    try:
        while stop is None or not stop.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                continue
            with connection:
                serve_connection(connection, frames, latest)
    finally:
        listener.close()
    return True


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"
    if not Path(video).exists():
        print(f"camera bridge: {video} is not available", file=sys.stderr)
        return 1
    capture_test_pattern()
    frames = FrameQueue(FRAME_QUEUE)
    latest = Latest()
    if STILL_PATTERN.is_file():
        latest.publish(STILL_PATTERN.read_bytes())
    start_preview(latest)
    writer = Encoder(video, frames, latest)
    threading.Thread(target=writer.run, daemon=True).start()
    try:
        serve_camera(frames, latest)
    finally:
        writer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
