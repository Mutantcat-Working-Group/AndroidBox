import importlib.util
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from androidbox import camera
from androidbox.runtime import (AUDIO_CAPTURE_DENIED, CAMERA_GUEST_PORT, VMConfig,
                                VirtualMachine, audio_arguments, audio_driver, build_command,
                                start_attempts)

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from androidbox.desktop import MainWindow, SettingsDialog


def fake_audio_drivers(*names):
    return subprocess.CompletedProcess(
        [], 0, stdout="Available audio drivers:\n" + "\n".join(names) + "\n")


class AudioSelectionTests(unittest.TestCase):
    def test_driver_order_follows_the_host(self):
        for system, offered, expected in [
                ("Darwin", ["none", "coreaudio", "wav"], "coreaudio"),
                ("Windows", ["none", "sdl", "dsound", "pa"], "dsound"),
                ("Windows", ["none", "sdl"], "sdl"),
                ("Linux", ["none", "alsa", "pipewire", "pa"], "pa"),
                ("Linux", ["none", "alsa"], "alsa"),
                ("Linux", ["none"], "")]:
            with self.subTest(system=system, offered=offered):
                with patch("androidbox.runtime.run", return_value=fake_audio_drivers(*offered)), \
                        patch("androidbox.runtime.platform.system", return_value=system):
                    self.assertEqual(audio_driver("qemu"), expected)

    def test_a_host_that_cannot_be_asked_raises(self):
        # The desktop treats this as "no sound" and still boots the guest.
        with patch("androidbox.runtime.run",
                   side_effect=subprocess.CalledProcessError(1, "qemu")):
            with self.assertRaises(subprocess.SubprocessError):
                audio_driver("qemu")

    def test_arguments_match_the_devices_the_user_asked_for(self):
        arguments = audio_arguments(VMConfig(audio="auto", microphone="auto"), "coreaudio")
        self.assertEqual(arguments[:2], ["-audiodev", "coreaudio,id=androidbox-audio"])
        self.assertIn("intel-hda", arguments)
        self.assertIn("hda-output,audiodev=androidbox-audio", arguments)
        self.assertIn("hda-micro,audiodev=androidbox-audio", arguments)

    def test_arguments_drop_each_device_it_cannot_have(self):
        self.assertNotIn("hda-micro,audiodev=androidbox-audio",
                         audio_arguments(VMConfig(microphone="off"), "coreaudio"))
        self.assertNotIn("hda-output,audiodev=androidbox-audio",
                         audio_arguments(VMConfig(audio="off"), "coreaudio"))
        self.assertEqual(audio_arguments(VMConfig(), ""), [])
        self.assertEqual(audio_arguments(VMConfig(audio="off", microphone="off"), "coreaudio"), [])

    def test_attempts_retreat_from_the_devices_that_refused_to_start(self):
        config = VMConfig()
        attempts = list(start_attempts(config, "coreaudio"))
        self.assertEqual([settings.audio for settings, _ in attempts], ["auto", "auto", "off"])
        self.assertEqual([settings.microphone for settings, _ in attempts], ["auto", "off", "off"])
        self.assertEqual([driver for _, driver in attempts], ["coreaudio", "coreaudio", None])
        self.assertEqual(list(start_attempts(config, "")), [(config, "")])


class MediaCommandTests(unittest.TestCase):
    def command(self, audio="auto", microphone="auto", driver="coreaudio"):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            config = VMConfig(disk=str(disk), audio=audio, microphone=microphone)
            return build_command(config, "qemu", "tcg", 5900, 6000, 6001, adb_port=5555,
                                 camera_port=7101, audio_driver=driver)

    def test_camera_and_adb_ride_the_same_user_network(self):
        command = self.command()
        netdev = command[command.index("-netdev") + 1]
        self.assertIn(",hostfwd=tcp:127.0.0.1:5555-:5555", netdev)
        self.assertIn(f",hostfwd=tcp:127.0.0.1:7101-:{CAMERA_GUEST_PORT}", netdev)
        self.assertIn("intel-hda", command)

    def test_no_audio_devices_when_sound_is_off(self):
        command = self.command(audio="off", microphone="off", driver=None)
        self.assertNotIn("intel-hda", command)
        self.assertNotIn("-audiodev", command)

    def test_media_settings_are_validated(self):
        for field, message in [("audio", "Invalid audio mode"),
                               ("microphone", "Invalid microphone mode"),
                               ("camera", "Invalid camera mode")]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, message):
                    VMConfig(**{field: "maximum"}).validate(check_files=False)

    def test_media_settings_survive_a_config_round_trip(self):
        from androidbox.runtime import load_config, save_config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = VMConfig(disk="/disk.qcow2", audio="off", microphone="auto", camera="off")
            save_config(config, path)
            self.assertEqual(load_config(path), config)

    def test_media_defaults_to_on(self):
        config = VMConfig()
        self.assertEqual((config.audio, config.microphone, config.camera), ("auto", "auto", "auto"))


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the desktop shell")
class CameraStreamTests(unittest.TestCase):
    def setUp(self):
        self.application = QApplication.instance() or QApplication([])

    def frame(self, width=320, height=240):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(0xFF336699)
        return image

    def test_a_frame_becomes_jpeg_bytes(self):
        payload = camera.encode_frame(self.frame())
        self.assertEqual(payload[:2], b"\xff\xd8")
        self.assertGreater(len(payload), 100)

    def test_wide_frames_are_scaled_before_they_leave(self):
        wide = camera.encode_frame(self.frame(1280, 720))
        small = camera.encode_frame(self.frame(640, 480))
        self.assertEqual(wide[:2], b"\xff\xd8")
        self.assertLessEqual(len(wide) - len(small), 1)  # same width, same quality

    def test_a_null_frame_encodes_to_nothing(self):
        self.assertEqual(camera.encode_frame(None), b"")
        self.assertEqual(camera.encode_frame(QImage()), b"")

    def test_host_camera_names_are_a_list_of_strings(self):
        names = camera.host_camera_names()
        self.assertIsInstance(names, list)
        self.assertTrue(all(isinstance(name, str) for name in names))

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_a_host_without_a_webcam_reports_it(self):
        streamer = camera.CameraStreamer(7101)
        reports = []
        streamer.status.connect(reports.append)
        empty = type("Device", (), {"isNull": staticmethod(lambda: True)})
        with patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: empty())):
            self.assertFalse(streamer.start())
        self.assertFalse(streamer.running)
        self.assertIn("no video input device", reports[0])

    def test_guest_camera_count_comes_from_dumpsys(self):
        self.assertEqual(camera.parse_guest_camera_count("Number of camera devices: 0"), 0)
        self.assertEqual(camera.parse_guest_camera_count("Number of camera devices: 2"), 2)
        self.assertIsNone(camera.parse_guest_camera_count("nothing here"))
        self.assertIsNone(camera.parse_guest_camera_count(""))

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_a_guest_without_a_camera_hal_says_so(self):
        streamer = camera.CameraStreamer(7101)
        streamer.set_guest_probe("/bundle/adb", "127.0.0.1:5555")
        reports = []
        streamer.status.connect(reports.append)
        blind = subprocess.CompletedProcess([], 0, "Number of camera devices: 0", "")
        with patch("androidbox.camera.run", return_value=blind):
            streamer._run_guest_camera_probe()
        self.assertIn("no camera HAL", reports[0])
        answering = subprocess.CompletedProcess([], 0, "Number of camera devices: 1", "")
        with patch("androidbox.camera.run", return_value=answering):
            streamer._run_guest_camera_probe()
        self.assertIn("1 camera device", reports[1])

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_a_probe_that_cannot_run_stays_quiet(self):
        streamer = camera.CameraStreamer(7101)
        reports = []
        streamer.status.connect(reports.append)
        streamer._run_guest_camera_probe()  # no probe configured
        self.assertEqual(reports, [])

    def test_without_multimedia_the_streamer_never_touches_a_camera(self):
        # A frozen build can ship without QtMultimedia; the placeholder keeps
        # every caller working instead of failing the import.
        with patch.dict(sys.modules, {"PySide6.QtMultimedia": None}):
            placeholder = importlib.reload(camera)
            try:
                streamer = placeholder.CameraStreamer()
                self.assertFalse(streamer.start())
                self.assertFalse(streamer.running)
                streamer.stop()
            finally:
                importlib.reload(camera)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_frames_flow_through_a_capture_session_once_the_bridge_answers(self):
        # The webcam stays switched off until the guest bridge greets the
        # host, and QCamera carries no video sink of its own, so the frames
        # have to travel through the capture session that owns both camera
        # and sink. A dormant recorder rides along because the FFmpeg media
        # backend only pumps frames into the sink while one is attached.
        streamer = camera.CameraStreamer(7101)
        device = type("Device", (), {"isNull": staticmethod(lambda: False),
                                     "description": staticmethod(lambda: "Test Camera")})()
        mock_camera = MagicMock()
        mock_recorder = MagicMock()
        with patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: device)), \
                patch.object(camera, "QCamera", mock_camera), \
                patch.object(camera, "QMediaCaptureSession", MagicMock()), \
                patch.object(camera, "QMediaRecorder", mock_recorder), \
                patch.object(camera, "QVideoSink", MagicMock()):
            streamer._watch_guest(device)
            self.assertTrue(streamer.running)
            self.assertIsNone(streamer.camera)  # the webcam waits for the bridge
            streamer._bridge_answered(f"Camera connected to the guest: {streamer.device}")
            session = camera.QMediaCaptureSession.return_value
            session.setCamera.assert_called_once_with(mock_camera.return_value)
            self.assertIs(session.setVideoSink.call_args.args[0], camera.QVideoSink.return_value)
            session.setRecorder.assert_called_once_with(mock_recorder.return_value)
            mock_camera.return_value.start.assert_called_once()
            streamer._write_frame(b"\xff\xd8\xff\xd9")
            streamer.stop()
            mock_camera.return_value.stop.assert_called_once()
            mock_recorder.return_value.deleteLater.assert_called_once()
        self.assertIsNone(streamer.capture)
        self.assertIsNone(streamer.recorder)
        self.assertFalse(streamer.running)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_camera_error_releases_capture_and_reports_macos_permission(self):
        streamer = camera.CameraStreamer(7101)
        camera_object = streamer.camera = MagicMock()
        capture = streamer.capture = MagicMock()
        streamer.sink = MagicMock()
        reports = []
        streamer.status.connect(reports.append)
        with patch("sys.platform", "darwin"):
            streamer._camera_error(camera.QCamera.Error.CameraError, "Access to camera not granted")
        self.assertFalse(streamer.running)
        self.assertIsNone(streamer.capture)
        self.assertIsNone(streamer.sink)
        camera_object.deleteLater.assert_called_once()
        capture.deleteLater.assert_called_once()
        self.assertIn("System Settings", reports[-1])
        self.assertIn("Privacy & Security > Camera", reports[-1])

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_camera_reconnect_budget_is_bounded(self):
        # QEMU answers a forwarded port before the guest bridge listens, so a
        # guest that is still booting counts as a wait, not as a failure: the
        # host webcam stays off and no budget is spent until a bridge answers.
        streamer = camera.CameraStreamer(0)
        streamer.device = "Test Camera"
        reports = []
        streamer.status.connect(reports.append)
        streamer._device = MagicMock()
        # A mock socket keeps the reconnect bookkeeping free of the timing a
        # real connect to an unreachable port would add.
        streamer.socket = MagicMock()
        reconnects = []
        with patch.object(camera.QTimer, "singleShot",
                          side_effect=lambda delay, callback: reconnects.append(callback)):
            for _ in range(30):
                streamer._disconnected()
                reconnects.pop()()
            self.assertEqual(len(reconnects), 0)
            self.assertEqual(reports, [])
            self.assertTrue(streamer.running)  # still waiting, webcam untouched
            # once a bridge has answered, its drops finally spend the budget
            streamer.link.opened(camera.time.monotonic())
            streamer.link.greeted()
            for _ in range(camera.MAX_CAMERA_RECONNECTS):
                streamer._disconnected()
                self.assertTrue(reconnects)
                reconnects.pop()()  # the host dials the bridge again...
                streamer.link.greeted()  # ...and the bridge answers again
            self.assertEqual(len(reports), camera.MAX_CAMERA_RECONNECTS)
            self.assertIn("reconnecting (1 of 5)", reports[0])
            streamer._disconnected()
        self.assertFalse(streamer.running)
        self.assertIn("stopped responding", reports[-1])

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_the_webcam_waits_for_the_guest_bridge(self):
        streamer = camera.CameraStreamer(0)
        reports = []
        streamer.status.connect(reports.append)
        device = type("Device", (), {"isNull": staticmethod(lambda: False),
                                     "description": staticmethod(lambda: "Test Camera")})()
        with patch("sys.platform", "linux"), \
                patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: device)), \
                patch.object(camera, "QCamera", MagicMock()), \
                patch.object(camera, "QMediaCaptureSession", MagicMock()), \
                patch.object(camera, "QMediaRecorder", MagicMock()), \
                patch.object(camera, "QVideoSink", MagicMock()):
            self.assertTrue(streamer.start())
            self.assertTrue(streamer.running)
            self.assertIsNone(streamer.camera)  # nothing on the guest side yet
            self.assertIn("Waiting for the guest camera bridge", reports[0])
            streamer._bridge_answered("Camera connected to the guest: Test Camera")
            self.assertIsNotNone(streamer.camera)  # now the webcam comes up
            streamer.stop()
        self.assertIsNone(streamer.camera)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_a_partial_greeting_keeps_the_webcam_waiting(self):
        streamer = camera.CameraStreamer(0)
        streamer._device = MagicMock()
        streamer.device = "Test Camera"
        reported = []
        streamer._bridge_answered = lambda message: reported.append(message)
        streamer.socket = MagicMock()
        streamer.socket.read.return_value = camera.CAMERA_GREETING[:12]
        streamer._read_greeting()
        self.assertEqual(reported, [])
        self.assertEqual(streamer._greeting_buffer, camera.CAMERA_GREETING[:12])
        streamer.socket.read.return_value = camera.CAMERA_GREETING[12:]
        streamer._read_greeting()
        self.assertEqual(reported, ["Camera connected to the guest: Test Camera"])

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_an_old_guest_that_never_greets_is_streamed_to_anyway(self):
        streamer = camera.CameraStreamer(0)
        streamer._device = MagicMock()
        streamer.device = "Test Camera"
        reported = []
        streamer._bridge_answered = lambda message: reported.append(message)
        streamer.socket = MagicMock()
        streamer.socket.read.return_value = b"something else entirely"
        streamer._read_greeting()
        self.assertEqual(reported, [None])
        # A bridge that never speaks at all is streamed to when the grace runs out.
        silent = camera.CameraStreamer(0)
        silent._device = MagicMock()
        silent.device = "Test Camera"
        silent._bridge_answered = lambda message: reported.append(message)
        silent._greeting_timed_out()
        self.assertIn(camera.CAMERA_GREETING_FALLBACK, reported)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_the_preview_url_and_hal_note_name_where_the_picture_lands(self):
        self.assertEqual(camera.CAMERA_PREVIEW_URL, "http://192.168.240.1:7101/")
        self.assertIn(camera.CAMERA_PREVIEW_URL, camera.GUEST_CAMERA_HAL_MISSING)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_the_macos_permission_flow_starts_the_webcam_when_granted(self):
        streamer = camera.CameraStreamer(7101)
        device = type("Device", (), {"isNull": staticmethod(lambda: False),
                                     "description": staticmethod(lambda: "Test Camera")})()
        application = MagicMock()
        application.checkPermission.side_effect = [
            camera.Qt.PermissionStatus.Undetermined,
            camera.Qt.PermissionStatus.Granted,
        ]
        application.requestPermission.side_effect = (
            lambda permission, context, callback: callback(permission))
        with patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: device)), \
                patch.object(camera.QCoreApplication, "instance", return_value=application), \
                patch.object(camera, "QCamera", MagicMock()), \
                patch.object(camera, "QMediaCaptureSession", MagicMock()), \
                patch.object(camera, "QVideoSink", MagicMock()), \
                patch("sys.platform", "darwin"):
            self.assertTrue(streamer.start())
            self.assertTrue(streamer.running)
            application.requestPermission.assert_called_once()
            self.assertIsNone(streamer.camera)  # the guest has not answered yet
            streamer._bridge_answered("Camera connected to the guest: Test Camera")
            self.assertIsNotNone(streamer.camera)
        camera.QCamera.return_value.start.assert_called_once()

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_a_stopped_streamer_ignores_a_late_close(self):
        streamer = camera.CameraStreamer(7101)
        streamer._device = MagicMock()
        streamer.stop()
        streamer._disconnected()
        streamer._socket_error(camera.QAbstractSocket.RemoteHostClosedError)
        self.assertFalse(streamer.running)
        self.assertEqual(streamer.link.open, False)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_frames_cross_to_the_socket_thread_as_bytes(self):
        streamer = camera.CameraStreamer(7101)
        streamer._device = MagicMock()
        streamer.device = "Test Camera"
        delivered = []
        streamer.frame_ready.connect(delivered.append)
        image = QImage(320, 240, QImage.Format.Format_RGB32)
        image.fill(0xFF336699)
        frame = type("Frame", (), {"toImage": staticmethod(lambda: image)})()
        streamer.camera = MagicMock()
        streamer.send_frame(frame)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0][:2], b"\xff\xd8")
        streamer.send_frame(frame)  # the rate limiter drops the second one
        self.assertEqual(len(delivered), 1)

    def test_a_guest_that_never_answers_spends_no_budget(self):
        link = camera.GuestLink()
        now = camera.time.monotonic()
        for _ in range(camera.MAX_CAMERA_RECONNECTS * 4):
            link.opened(now)
            message, keep = link.closed(now)
            self.assertIsNone(message)
            self.assertTrue(keep)
        self.assertEqual(link.attempts, 0)

    def test_a_double_close_is_one_drop(self):
        link = camera.GuestLink()
        now = camera.time.monotonic()
        link.opened(now)
        link.greeted()
        message, keep = link.closed(now)
        self.assertIn("reconnecting (1 of 5)", message)
        message, keep = link.closed(now)  # the socket stack reports two drops
        self.assertIsNone(message)
        self.assertTrue(keep)
        self.assertEqual(link.attempts, 1)

    def test_a_link_that_was_never_opened_has_nothing_to_report(self):
        link = camera.GuestLink()
        message, keep = link.closed(camera.time.monotonic())
        self.assertIsNone(message)
        self.assertTrue(keep)
        self.assertEqual(link.attempts, 0)

    def test_the_bridge_waits_for_the_host_silence_it_tolerates(self):
        self.assertEqual(camera.CAMERA_GREETING, b"ANDROIDBOX-CAMERA-1\n")
        self.assertGreaterEqual(camera.CAMERA_GREETING_GRACE, 60.0)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_camera_reconnect_budget_resets_after_a_stable_connection(self):
        streamer = camera.CameraStreamer(0)
        streamer._device = MagicMock()
        link = streamer.link
        link.opened(camera.time.monotonic() - camera.CAMERA_STABLE_CONNECTION_SECONDS - 1)
        link.greeted()
        with patch.object(camera.QTimer, "singleShot"):
            streamer._disconnected()
        self.assertEqual(link.attempts, 1)

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_macos_permission_denied_reports_without_starting_camera(self):
        streamer = camera.CameraStreamer(7101)
        reports = []
        streamer.status.connect(reports.append)
        device = type("Device", (), {"isNull": staticmethod(lambda: False),
                                     "description": staticmethod(lambda: "Test Camera")})()
        application = MagicMock()
        application.checkPermission.return_value = camera.Qt.PermissionStatus.Denied
        mock_camera = MagicMock()
        with patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: device)), \
                patch.object(camera.QCoreApplication, "instance", return_value=application), \
                patch.object(camera, "QCamera", mock_camera), \
                patch("sys.platform", "darwin"):
            self.assertFalse(streamer.start())
        self.assertFalse(streamer.running)
        self.assertIn("System Settings", reports[-1])
        mock_camera.assert_not_called()

    @unittest.skipUnless(camera.CAMERA_STACK, "QtMultimedia unavailable")
    def test_the_macos_permission_flow_starts_the_webcam_when_granted(self):
        streamer = camera.CameraStreamer(0)
        device = type("Device", (), {"isNull": staticmethod(lambda: False),
                                     "description": staticmethod(lambda: "Test Camera")})()
        application = MagicMock()
        application.checkPermission.side_effect = [
            camera.Qt.PermissionStatus.Undetermined,
            camera.Qt.PermissionStatus.Granted,
        ]
        application.requestPermission.side_effect = (
            lambda permission, context, callback: callback(permission))
        with patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: device)), \
                patch.object(camera.QCoreApplication, "instance", return_value=application), \
                patch("sys.platform", "darwin"):
            self.assertTrue(streamer.start())
        self.assertTrue(streamer.running)
        application.requestPermission.assert_called_once()
        # A granted permission only starts watching the guest: the physical
        # webcam comes up once the bridge answers, never for a guest that is
        # still booting.
        self.assertIsNone(streamer.camera)


class GuestAudioReportTests(unittest.TestCase):
    def test_the_log_reveals_a_microphone_the_host_refused(self):
        vm = VirtualMachine()
        self.assertFalse(vm.log_mentions(AUDIO_CAPTURE_DENIED))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qemu.log"
            with path.open("wb") as stream:
                stream.write(b"qemu-system-x86_64: -device hda-micro,audiodev=androidbox-audio"
                             b": audio: Can not open `adc' (no host audio driver)\n")
                vm.log = stream
                self.assertTrue(vm.log_mentions(AUDIO_CAPTURE_DENIED))
                self.assertFalse(vm.log_mentions("a different problem"))

    def test_guest_sound_names_the_devices_it_kept(self):
        vm = VirtualMachine()
        vm.audio_driver = "coreaudio"
        vm.audio_settings = VMConfig(audio="auto", microphone="auto")
        self.assertEqual(vm.describe_audio(), "coreaudio: speakers and microphone")
        vm.microphone_denied = True
        report = vm.describe_audio()
        self.assertIn("speakers", report)
        self.assertIn("withholds its microphone", report)
        vm.audio_driver = ""
        self.assertEqual(vm.describe_audio(), "guest audio off")


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the desktop shell")
class DesktopMediaTests(unittest.TestCase):
    def setUp(self):
        self.application = QApplication.instance() or QApplication([])

    def window(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.guestdisk.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)):
            window = MainWindow()
            window.show()
            return window

    def test_settings_offer_the_media_choices(self):
        window = self.window()
        dialog = SettingsDialog(window.config)
        for name in ("audio", "microphone", "camera"):
            control = getattr(dialog, name)
            self.assertEqual([control.itemText(index) for index in range(control.count())],
                             ["auto", "off"])
            self.assertEqual(control.currentText(), getattr(window.config, name))
        dialog.camera.setCurrentText("off")
        self.assertEqual(dialog.config().camera, "off")
        window.close()

    def test_camera_follows_the_guest_lifecycle(self):
        window = self.window()
        started = []
        stopped = []

        class FakeStreamer:
            def __init__(self, *args, **kwargs):
                self.port = args[0] if args else kwargs.get("port")
                self.probe = None

            def set_guest_probe(self, adb, target):
                self.probe = (adb, target)

            def start(self):
                started.append(self.port)
                return True

            def stop(self):
                stopped.append(self.port)

        window.vm.process = type("Process", (), {"poll": staticmethod(lambda: None)})()
        window.vm.camera_port = 7101
        with patch("androidbox.desktop.CameraStreamer", FakeStreamer):
            window.start_camera()
            self.assertEqual(started, [7101])
            window.start_camera()  # a second call must not stream twice
            self.assertEqual(started, [7101])
            window.stop_camera()
            window.stop_camera()  # stopping twice releases the webcam once
        self.assertEqual(stopped, [7101])
        window.vm.process = None
        with patch("androidbox.desktop.CameraStreamer", FakeStreamer):
            window.start_camera()
        self.assertEqual(started, [7101])  # a stopped guest starts no stream
        window.close()
