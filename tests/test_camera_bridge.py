"""Exercise the guest camera bridge the way the host meets it.

The bridge is a stand-alone script that runs inside the Ubuntu support layer
with nothing but the guest standard library, so these tests load it straight
off disk and feed it real sockets, real frames and a real HTTP client. The
encoder process and the test-pattern capture are the only pieces that leave
the script, so the tests stub just those and keep every decision the bridge
makes for itself.
"""

import importlib.util
import http.client
import queue
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parent.parent
BRIDGE = REPO / "guest" / "camera-bridge.py"

spec = importlib.util.spec_from_file_location("camera_bridge_under_test", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def wait_for(predicate, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeProcess:
    """Stand in for the ffmpeg process the bridge writes frames into."""

    def __init__(self, alive=True, broken=False):
        self.written = bytearray()
        self.alive = alive
        self.broken = broken
        self.killed = False

    def poll(self):
        return None if self.alive else 1

    def kill(self):
        self.killed = True
        self.alive = False

    @property
    def stdin(self):
        return self

    def write(self, payload):
        if self.broken:
            raise BrokenPipeError("the encoder is gone")
        self.written.extend(payload)

    def flush(self):
        pass

    def text(self):
        return bytes(self.written)


class FrameQueueTests(unittest.TestCase):
    def test_a_full_queue_keeps_the_newest_frame(self):
        frames = bridge.FrameQueue(2)
        frames.offer(b"one")
        frames.offer(b"two")
        frames.offer(b"three")
        self.assertEqual(frames.queue.get_nowait(), b"two")
        self.assertEqual(frames.queue.get_nowait(), b"three")

    def test_frames_travel_in_order(self):
        frames = bridge.FrameQueue(8)
        for index in range(4):
            frames.offer(f"frame-{index}".encode())
        received = [frames.get(timeout=1.0) for _ in range(4)]
        self.assertEqual(received, [b"frame-0", b"frame-1", b"frame-2", b"frame-3"])

    def test_an_empty_queue_reports_nothing_within_the_timeout(self):
        self.assertIsNone(bridge.FrameQueue(4).get(0.05))


class LatestFrameTests(unittest.TestCase):
    def test_the_snapshot_holds_the_last_published_frame(self):
        latest = bridge.Latest()
        self.assertEqual(latest.snapshot(), b"")
        latest.publish(b"first")
        latest.publish(b"second")
        self.assertEqual(latest.snapshot(), b"second")

    def test_take_returns_none_when_nothing_arrives_in_time(self):
        self.assertIsNone(bridge.Latest().take(0.05))

    def test_take_returns_the_newest_frame_when_one_arrives(self):
        latest = bridge.Latest()
        threading.Timer(0.05, lambda: latest.publish(b"hello")).start()
        self.assertEqual(latest.take(1.0), b"hello")


class BridgeLinkTests(unittest.TestCase):
    def setUp(self):
        self.listener = bridge.open_listener(0)
        self.addCleanup(self.listener.close)
        self.port = self.listener.getsockname()[1]
        self.frames = bridge.FrameQueue(bridge.FRAME_QUEUE)
        self.latest = bridge.Latest()
        self.handler = None

    def connect(self):
        client = socket.create_connection(("127.0.0.1", self.port), timeout=5.0)
        client.settimeout(5.0)
        self.addCleanup(client.close)
        def accept_and_serve():
            connection, _ = self.listener.accept()
            with connection:
                bridge.serve_connection(connection, self.frames, self.latest)
        self.handler = threading.Thread(target=accept_and_serve, daemon=True)
        self.handler.start()
        return client

    def greet(self, client):
        return client.recv(len(bridge.CAMERA_GREETING))

    def test_the_bridge_greets_the_host_before_it_asks_for_anything(self):
        client = self.connect()
        self.assertEqual(self.greet(client), bridge.CAMERA_GREETING)
        self.assertEqual(bridge.CAMERA_GREETING, b"ANDROIDBOX-CAMERA-1\n")

    def test_the_frames_the_host_sends_reach_the_queue(self):
        client = self.connect()
        self.assertEqual(self.greet(client), bridge.CAMERA_GREETING)
        client.sendall(b"frame-one")
        self.assertTrue(wait_for(lambda: self.latest.snapshot() == b"frame-one"))
        client.sendall(b"frame-two")
        self.assertTrue(wait_for(lambda: self.latest.snapshot() == b"frame-two"))
        time.sleep(0.2)
        drained = []
        while True:
            try:
                drained.append(self.frames.queue.get_nowait())
            except queue.Empty:
                break
        self.assertEqual(b"".join(drained), b"frame-oneframe-two")

    def test_a_host_that_disconnects_ends_the_link_without_side_effects(self):
        client = self.connect()
        self.assertEqual(self.greet(client), bridge.CAMERA_GREETING)
        client.close()
        self.assertTrue(wait_for(lambda: not self.handler.is_alive(), timeout=3.0))
        self.assertEqual(self.latest.snapshot(), b"")

    def test_silence_past_the_tolerance_drops_the_host(self):
        with patch.object(bridge, "IDLE_TOLERANCE", 0.3):
            client = self.connect()
            self.assertEqual(self.greet(client), bridge.CAMERA_GREETING)
            time.sleep(0.9)
            self.assertEqual(client.recv(16), b"")
            self.assertTrue(wait_for(lambda: not self.handler.is_alive(), timeout=3.0))


class BridgeAcceptLoopTests(unittest.TestCase):
    def test_the_bridge_greets_the_next_host_after_one_drops(self):
        listener = bridge.open_listener(0)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        frames, latest = bridge.FrameQueue(8), bridge.Latest()
        stop = threading.Event()
        self.addCleanup(stop.set)
        thread = threading.Thread(target=bridge.serve_camera,
                                  args=(frames, latest),
                                  kwargs={"listener": listener, "stop": stop},
                                  daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5.0)
        first = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        first.settimeout(5.0)
        with first:
            self.assertEqual(first.recv(len(bridge.CAMERA_GREETING)), bridge.CAMERA_GREETING)
            first.sendall(b"from-one")
        second = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        second.settimeout(5.0)
        with second:
            self.assertEqual(second.recv(len(bridge.CAMERA_GREETING)), bridge.CAMERA_GREETING)
            second.sendall(b"from-two")
            self.assertTrue(wait_for(lambda: b"from-two" in latest.snapshot()))
        stop.set()
        self.assertTrue(wait_for(lambda: not thread.is_alive(), timeout=3.0))

    def test_a_port_the_guest_already_took_makes_open_listener_give_up(self):
        squatter = socket.socket()
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows lets a socket that set SO_REUSEADDR take a port another
            # socket already bound, so the squatter has to claim the port
            # exclusively for the conflict this test describes to exist there.
            squatter.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        squatter.bind(("0.0.0.0", 0))
        squatter.listen(1)
        port = squatter.getsockname()[1]
        try:
            self.assertIsNone(bridge.open_listener(port))
        finally:
            squatter.close()

    def test_serve_camera_reports_a_port_it_cannot_take(self):
        with patch.object(bridge, "open_listener", return_value=None):
            self.assertFalse(bridge.serve_camera(MagicMock(), MagicMock()))


class EncoderTests(unittest.TestCase):
    def setUp(self):
        self.frames = bridge.FrameQueue(8)
        self.latest = bridge.Latest()
        self.processes = []

        def fake_start(video):
            process = FakeProcess()
            self.processes.append(process)
            return process

        patcher = patch.object(bridge, "start_encoder", fake_start)
        patcher.start()
        self.addCleanup(patcher.stop)
        printer = patch.object(bridge, "print")
        printer.start()
        self.addCleanup(printer.stop)
        self.encoder = bridge.Encoder("/dev/video0", self.frames, self.latest)
        self.writer = threading.Thread(target=self.encoder.run, daemon=True)
        self.writer.start()
        self.addCleanup(self.encoder.close)
        self.assertTrue(wait_for(lambda: len(self.processes) >= 1))

    def written(self):
        return b"".join(process.text() for process in self.processes)

    def test_host_frames_are_written_to_the_encoder(self):
        self.frames.offer(b"frame-a")
        self.frames.offer(b"frame-b")
        self.assertTrue(wait_for(lambda: b"frame-a" in self.written()))
        self.assertTrue(wait_for(lambda: b"frame-b" in self.written()))

    def test_a_encoder_that_died_is_restarted_and_keeps_writing(self):
        self.frames.offer(b"first")
        self.assertTrue(wait_for(lambda: b"first" in self.written()))
        self.processes[0].alive = False
        self.frames.offer(b"second")
        self.assertTrue(wait_for(lambda: len(self.processes) >= 2))
        self.frames.offer(b"third")
        self.assertTrue(wait_for(lambda: b"third" in self.processes[-1].text()))
        # A process that already exited on its own is replaced, not killed.
        self.assertFalse(self.processes[0].killed)

    def test_a_encoder_whose_pipe_broke_is_restarted(self):
        self.processes[0].broken = True
        self.frames.offer(b"frame")
        self.assertTrue(wait_for(lambda: len(self.processes) >= 2))

    def test_close_stops_the_writer_and_kills_the_encoder(self):
        self.frames.offer(b"frame")
        self.assertTrue(wait_for(lambda: self.processes[0].text()))
        self.encoder.close()
        self.assertTrue(self.encoder.stop.is_set())
        self.assertIsNotNone(self.processes[0].poll())


class EncoderFallbackTests(unittest.TestCase):
    def setUp(self):
        self.frames = bridge.FrameQueue(8)
        self.latest = bridge.Latest()
        self.processes = []
        patcher = patch.object(bridge, "start_encoder", lambda video: self._start())
        patcher.start()
        self.addCleanup(patcher.stop)
        printer = patch.object(bridge, "print")
        printer.start()
        self.addCleanup(printer.stop)

    def _start(self):
        process = FakeProcess()
        self.processes.append(process)
        return process

    def test_an_idle_encoder_falls_back_to_the_test_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            pattern = Path(directory) / "camera-pattern.jpg"
            pattern.write_bytes(b"PATTERN")
            encoder = bridge.Encoder("/dev/video0", self.frames, self.latest)
            self.addCleanup(encoder.close)
            with patch.object(bridge, "STILL_PATTERN", pattern), \
                    patch.object(bridge, "IDLE_FALLBACK", 0.3), \
                    patch.object(bridge, "TEST_PATTERN_INTERVAL", 0.2):
                writer = threading.Thread(target=encoder.run, daemon=True)
                writer.start()
                self.assertTrue(wait_for(lambda: self.latest.snapshot() == b"PATTERN"))
                self.assertTrue(wait_for(lambda: b"PATTERN" in self.processes[0].text()))

    def test_host_frames_silence_the_test_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            pattern = Path(directory) / "camera-pattern.jpg"
            pattern.write_bytes(b"PATTERN")
            encoder = bridge.Encoder("/dev/video0", self.frames, self.latest)
            self.addCleanup(encoder.close)
            with patch.object(bridge, "STILL_PATTERN", pattern), \
                    patch.object(bridge, "IDLE_FALLBACK", 1.5), \
                    patch.object(bridge, "TEST_PATTERN_INTERVAL", 0.2):
                writer = threading.Thread(target=encoder.run, daemon=True)
                writer.start()
                self.frames.offer(b"live-frame")
                # A live host frame goes to the encoder; only an idle bridge
                # falls back to the test pattern.
                self.assertTrue(wait_for(lambda: b"live-frame" in self.processes[0].text()))


class TestPatternTests(unittest.TestCase):
    def test_a_pattern_the_guest_already_has_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            pattern = Path(directory) / "camera-pattern.jpg"
            pattern.write_bytes(b"kept")
            with patch.object(bridge, "STILL_PATTERN", pattern), \
                    patch.object(bridge.subprocess, "run") as runner:
                bridge.capture_test_pattern()
                runner.assert_not_called()

    def test_a_guest_without_a_pattern_renders_one(self):
        with tempfile.TemporaryDirectory() as directory:
            pattern = Path(directory) / "missing" / "camera-pattern.jpg"
            with patch.object(bridge, "STILL_PATTERN", pattern), \
                    patch.object(bridge.subprocess, "run") as runner:
                bridge.capture_test_pattern()
                runner.assert_called_once()
                self.assertIn("ffmpeg", runner.call_args[0][0])


class PreviewServerTests(unittest.TestCase):
    def connect(self):
        server = bridge.start_preview(self.latest, bind=("127.0.0.1", 0))
        # Cleanups run last in first out, so the accept loop is stopped before
        # the listener is closed. Windows refuses a select on a socket whose
        # thread has already closed it, which surfaces as a stray traceback.
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        self.addCleanup(connection.close)
        return connection

    def setUp(self):
        self.latest = bridge.Latest()

    def test_the_page_offers_the_stream_and_a_still_fallback(self):
        connection = self.connect()
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn("text/html", response.getheader("Content-Type"))
        self.assertIn(b'<img id="view" src="stream"', bridge.PREVIEW_PAGE)
        self.assertIn(b"snapshot.jpg", body)

    def test_the_snapshot_serves_the_latest_frame(self):
        self.latest.publish(b"JPEGDATA")
        connection = self.connect()
        connection.request("GET", "/snapshot.jpg")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "image/jpeg")
        self.assertEqual(response.read(), b"JPEGDATA")

    def test_a_guest_without_a_frame_yet_gets_a_service_error(self):
        connection = self.connect()
        connection.request("GET", "/snapshot.jpg")
        response = connection.getresponse()
        self.assertEqual(response.status, 503)

    def test_the_stream_frames_each_picture_for_a_browser(self):
        self.latest.publish(b"JPEGDATA")
        connection = self.connect()
        connection.request("GET", "/stream")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn("multipart/x-mixed-replace", response.getheader("Content-Type"))
        self.assertIn(bridge.PREVIEW_BOUNDARY.decode(),
                      response.getheader("Content-Type"))
        self.assertEqual(response.read(20), b"--" + bridge.PREVIEW_BOUNDARY + b"\r\n")
        self.assertEqual(response.read(57),
                         b"Content-Type: image/jpeg\r\nContent-Length: 8\r\n\r\n"
                         b"JPEGDATA\r\n")

    def test_an_unknown_route_is_not_found(self):
        connection = self.connect()
        connection.request("GET", "/nope")
        response = connection.getresponse()
        self.assertEqual(response.status, 404)
        response.read()


class MainFlowTests(unittest.TestCase):
    def test_a_guest_without_the_loopback_node_is_reported(self):
        with patch.object(bridge, "Path",
                          lambda *args, **kwargs: SimpleNamespace(exists=lambda: False)), \
                patch.object(sys, "argv", ["camera-bridge.py"]):
            self.assertEqual(bridge.main(), 1)

    def test_a_guest_with_the_loopback_node_streams(self):
        encoder = SimpleNamespace(run=lambda: None, close=lambda: None)

        class StoppingServe:
            def __call__(self, frames, latest):
                return True

        with patch.object(bridge, "Path",
                          lambda *args, **kwargs: SimpleNamespace(exists=lambda: True)), \
                patch.object(bridge, "capture_test_pattern"), \
                patch.object(bridge, "STILL_PATTERN",
                             SimpleNamespace(is_file=lambda: True,
                                             read_bytes=lambda: b"pattern")), \
                patch.object(bridge, "start_preview", MagicMock()), \
                patch.object(bridge, "Encoder", lambda *a, **k: encoder), \
                patch.object(bridge, "serve_camera", StoppingServe()), \
                patch.object(sys, "argv", ["camera-bridge.py"]):
            self.assertEqual(bridge.main(), 0)


class HandshakeAgreementTests(unittest.TestCase):
    def test_the_host_and_the_guest_agree_on_the_handshake(self):
        from androidbox import camera
        from androidbox.runtime import CAMERA_GUEST_PORT

        self.assertEqual(camera.CAMERA_GREETING, bridge.CAMERA_GREETING)
        self.assertEqual(CAMERA_GUEST_PORT, bridge.CAMERA_PORT)
        self.assertEqual(camera.CAMERA_PREVIEW_PORT, bridge.PREVIEW_PORT)
        self.assertTrue(bridge.IDLE_TOLERANCE > bridge.IDLE_FALLBACK)
