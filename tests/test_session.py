"""Exercise the guest session state machine without a window.

The desktop shell only renders these transitions; everything that decides what
QEMU is doing has to be testable on its own. These tests drive the session with
an inline executor and a fake VM so a start, an unexpected exit, a shutdown,
a disk preparation and an upload each complete without QEMU or a guest image.
"""

from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from androidbox import runtime
from androidbox.session import MAX_GUEST_RESTARTS, GuestSession


class InlinePool:
    """Run every submitted job at once, as if its worker had already finished."""

    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - mirror Future's contract
            future.set_exception(error)
        return future

    def shutdown(self, wait=False):
        pass


class AliveProcess:
    returncode = None

    def poll(self):
        return None


class DeadProcess:
    def __init__(self, code=1):
        self.returncode = code

    def poll(self):
        return self.returncode


class FakeServer:
    def __init__(self):
        self.url = "http://127.0.0.1:9999/token/display.html"
        self.closed = False

    def close(self):
        self.closed = True


class FakeVM:
    def __init__(self):
        self.process = None
        self.adb_port = 5555
        self.camera_port = 7100
        self.preview_port = 7200
        self.websocket_port = 5901
        self.password = "secret"
        self.audio_driver = ""
        self.audio_settings = None
        self.microphone_denied = False
        self.started = False
        self.terminated = False
        self.shutdown_called = False

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, config, binary, accelerator, log_path, audio_driver=None):
        self.started = True
        self.audio_driver = audio_driver or ""
        self.process = AliveProcess()

    def connect_display(self):
        pass

    def shutdown(self):
        self.shutdown_called = True

    def terminate(self):
        self.terminated = True
        self.process = None

    def close_log(self):
        pass

    def describe_audio(self):
        return "test audio"


class SessionFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.disk = self.root / "guest.raw"
        self.disk.write_bytes(b"guest disk")
        self.config = runtime.VMConfig(disk=str(self.disk), arch="x86_64", memory_mb=2048,
                                       cpus=2, audio="off", microphone="off", camera="off")
        patcher = patch("androidbox.session.runtime.state_directory", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.probe = patch("androidbox.session.runtime.probe", return_value=("qemu", "tcg"))
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.server = patch("androidbox.session.DisplayServer", FakeServer)
        self.server.start()
        self.addCleanup(self.server.stop)

    def session(self):
        session = GuestSession(config=runtime.VMConfig(**vars(self.config)), pool=InlinePool())
        session.vm = FakeVM()
        session.timer.stop()
        self.addCleanup(session.close)
        return session

    def start(self, session):
        self.assertTrue(session.start())
        session.poll()


class StartTests(SessionFixture):
    def test_a_started_guest_names_its_accelerator_and_serves_the_display(self):
        started = []
        session = self.session()
        session.started.connect(started.append)
        self.start(session)
        self.assertEqual(started, ["tcg"])
        self.assertTrue(session.was_running)
        self.assertTrue(session.vm.started)
        self.assertIsNotNone(session.server)
        self.assertIn("token", session.display_url())

    def test_a_refused_start_reports_the_operation_and_releases_the_display(self):
        failures = []
        session = self.session()
        session.failed.connect(lambda *args: failures.append(args))
        with patch("androidbox.session.runtime.probe",
                   side_effect=ValueError("QEMU not found")):
            self.start(session)
        self.assertFalse(session.was_running)
        self.assertIsNone(session.server)
        self.assertEqual(failures[0][0], "Operation failed")
        self.assertEqual(failures[0][2], "start")
        self.assertIn("QEMU not found", str(failures[0][1]))

    def test_an_invalid_start_is_refused_before_any_worker_runs(self):
        failures = []
        session = self.session()
        session.failed.connect(lambda *args: failures.append(args))
        session.config = runtime.VMConfig(disk=str(self.root / "missing.raw"), arch="x86_64")
        self.assertFalse(session.start())
        self.assertEqual(failures[0][0], "Start failed")
        self.assertEqual(failures[0][2], "start")


class ExitTests(SessionFixture):
    def test_an_unexpected_exit_emits_stopped_and_spends_one_restart(self):
        session = self.session()
        self.start(session)
        session.vm.process = DeadProcess(1)
        restarts = []
        session.stopped.connect(restarts.append)
        with patch.object(session, "start") as start:
            session.poll()
        self.assertEqual(restarts, [1])
        self.assertEqual(start.call_count, 1)
        self.assertEqual(session.restarts, 1)
        self.assertTrue(session.recovering)
        self.assertFalse(session.was_running)

    def test_a_clean_exit_does_not_restart_and_is_reported_as_stopped(self):
        session = self.session()
        self.start(session)
        session.vm.process = DeadProcess(0)
        stopped = []
        session.stopped.connect(stopped.append)
        with patch.object(session, "start") as start:
            session.poll()
        self.assertEqual(stopped, [0])
        self.assertFalse(start.called)

    def test_a_guest_the_user_shut_down_is_not_restarted(self):
        session = self.session()
        self.start(session)
        session.shutdown_requested = True
        session.vm.process = DeadProcess(1)
        with patch.object(session, "start") as start:
            session.poll()
        self.assertFalse(start.called)
        self.assertEqual(session.restarts, 0)

    def test_the_restart_budget_is_bounded(self):
        session = self.session()
        self.start(session)
        session.restarts = MAX_GUEST_RESTARTS
        session.vm.process = DeadProcess(1)
        messages = []
        session.message.connect(messages.append)
        with patch.object(session, "start") as start:
            session.poll()
        self.assertFalse(start.called)
        self.assertIn("press Start to try again", messages[-1])


class OperationTests(SessionFixture):
    def test_stop_asks_qemu_to_power_down_then_force_terminates(self):
        session = self.session()
        self.start(session)
        session.stop()
        session.poll()
        self.assertTrue(session.vm.shutdown_called)
        self.assertTrue(session.shutdown_requested)
        session.stop(force=True)
        self.assertTrue(session.vm.terminated)

    def test_prepare_stores_the_overlay_and_reports_it(self):
        session = self.session()
        overlay = self.root / "guests" / "androidbox-x86_64.qcow2"
        prepared = []

        def fake_prepare(arch, directory, progress=None):
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_bytes(b"QFI\xfb" + b"\0" * 64)
            return overlay

        session.prepared.connect(prepared.append)
        with patch("androidbox.session.guestdisk.prepare", side_effect=fake_prepare), \
                patch("androidbox.session.runtime.save_config") as save:
            session.prepare("x86_64", self.root / "guests")
            session.poll()
        self.assertEqual(prepared, [str(overlay)])
        self.assertEqual(session.config.disk, str(overlay))
        self.assertEqual(session.config.disk_format, "qcow2")
        self.assertEqual(session.config.arch, "x86_64")
        save.assert_called_once()

    def test_a_failed_prepare_keeps_the_old_settings(self):
        session = self.session()
        failures = []
        session.failed.connect(lambda *args: failures.append(args))
        with patch("androidbox.session.guestdisk.prepare",
                   side_effect=OSError("every mirror failed")):
            session.prepare("x86_64", self.root / "guests")
            session.poll()
        self.assertEqual(session.config.disk, str(self.disk))
        self.assertEqual(failures[0][0], "Guest disk preparation failed")
        self.assertEqual(failures[0][2], "prepare")

    def test_an_upload_targets_the_forwarded_adb_port(self):
        session = self.session()
        self.start(session)
        with patch("androidbox.session.transfer_files", return_value="Uploaded 1 file") as transfer:
            session.upload(["/tmp/app.apk"], "adb")
            session.poll()
        self.assertEqual(transfer.call_args.args[:3], ("adb", "127.0.0.1:5555", ["/tmp/app.apk"]))

    def test_install_targets_the_forwarded_adb_port(self):
        session = self.session()
        self.start(session)
        with patch("androidbox.session.adb_install_apk", return_value="Success") as install:
            session.install_apk("adb", "/tmp/app.apk")
            session.poll()
        self.assertEqual(install.call_args.args, ("adb", "127.0.0.1:5555", "/tmp/app.apk"))


class LogTests(SessionFixture):
    def test_only_new_bytes_reach_the_log(self):
        session = self.session()
        lines = []
        session.log.connect(lines.append)
        session.log_path.write_text("first\n", encoding="utf-8")
        session.poll()
        session.log_path.write_text("first\nsecond\n", encoding="utf-8")
        session.poll()
        self.assertEqual(lines, ["first", "second"])

    def test_a_missing_log_is_not_an_error(self):
        session = self.session()
        session.log_path = self.root / "absent.log"
        session.poll()


if __name__ == "__main__":
    unittest.main()
