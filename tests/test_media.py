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

    def test_a_host_without_a_webcam_reports_it(self):
        from PySide6.QtMultimedia import QMediaDevices
        streamer = camera.CameraStreamer(7101)
        reports = []
        streamer.status.connect(reports.append)
        empty = type("Device", (), {"isNull": staticmethod(lambda: True)})
        with patch.object(QMediaDevices, "defaultVideoInput", staticmethod(lambda: empty())):
            self.assertFalse(streamer.start())
        self.assertFalse(streamer.running)
        self.assertIn("no video input device", reports[0])

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

    def test_frames_flow_through_a_capture_session(self):
        # QCamera carries no video sink of its own, so the frames have to
        # travel through the capture session that owns both camera and sink.
        streamer = camera.CameraStreamer(7101)
        device = type("Device", (), {"isNull": staticmethod(lambda: False),
                                     "description": staticmethod(lambda: "Test Camera")})()
        with patch.object(camera.QMediaDevices, "defaultVideoInput", staticmethod(lambda: device)), \
                patch.object(camera, "QCamera", MagicMock()), \
                patch.object(camera, "QMediaCaptureSession", MagicMock()), \
                patch.object(camera, "QVideoSink", MagicMock()):
            self.assertTrue(streamer.start())
            self.assertTrue(streamer.running)
            session = camera.QMediaCaptureSession.return_value
            session.setCamera.assert_called_once_with(camera.QCamera.return_value)
            self.assertIs(session.setVideoSink.call_args.args[0], camera.QVideoSink.return_value)
            camera.QCamera.return_value.start.assert_called_once()
            streamer.stop()
            camera.QCamera.return_value.stop.assert_called_once()
        self.assertIsNone(streamer.capture)
        self.assertFalse(streamer.running)


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
            def __init__(self, port=None, parent=None):
                self.port = port

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
