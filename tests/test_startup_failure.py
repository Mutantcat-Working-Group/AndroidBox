import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from androidbox.runtime import VMConfig, VirtualMachine, startup_failure_reason


class StartupFailureTests(unittest.TestCase):
    def test_a_disk_another_qemu_holds_gets_an_actionable_message(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "qemu.log"
            log.write_text('qemu-system-aarch64: -blockdev {"driver":"qcow2"}: '
                           'Failed to get "write" lock\n'
                           'Is another process using the image [guest.qcow2]?\n',
                           encoding="utf-8")
            reason = startup_failure_reason(log)
            self.assertIn("Another program is using the guest disk", reason)

    def test_other_startup_failures_stay_unclassified(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "qemu.log"
            log.write_text("qemu-system-x86_64: could not load kernel\n", encoding="utf-8")
            self.assertIsNone(startup_failure_reason(log))

    def test_a_missing_log_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(startup_failure_reason(Path(directory) / "absent.log"))

    def test_a_locked_disk_is_reported_instead_of_the_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "qemu.log"
            disk = Path(directory) / "guest.qcow2"
            disk.write_bytes(b"guest disk")
            failing_process = SimpleNamespace(
                poll=lambda: 1,
                returncode=1,
                terminate=lambda: None,
                wait=lambda timeout=None: None,
                kill=lambda: None,
            )

            def fake_popen(command, **kwargs):
                stream = kwargs.get("stdout")
                if stream is not None:
                    stream.write(b'qemu-system-aarch64: -blockdev {"driver":"qcow2"}: '
                                 b'Failed to get "write" lock\n'
                                 b'Is another process using the image [guest.qcow2]?\n')
                    stream.flush()
                return failing_process

            with patch("androidbox.runtime.popen", side_effect=fake_popen):
                vm = VirtualMachine()
                with self.assertRaises(RuntimeError) as raised:
                    vm.start(VMConfig(disk=str(disk)), "qemu-system-aarch64", "hvf", log)
                self.assertIn("Another program is using the guest disk", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
