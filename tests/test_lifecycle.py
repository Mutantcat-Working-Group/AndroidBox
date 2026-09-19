import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from androidbox.runtime import VirtualMachine, VMConfig, qmp_execute


class LifecycleTests(unittest.TestCase):
    def test_qmp_handshake_and_events(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        messages = []

        def server():
            with listener:
                connection, _ = listener.accept()
                with connection, connection.makefile("rwb") as stream:
                    stream.write(b'{"QMP": {}}\n')
                    stream.flush()
                    for _ in range(2):
                        message = json.loads(stream.readline())
                        messages.append(message)
                        stream.write(b'{"event": "RESET"}\n')
                        stream.write((json.dumps({"return": {}, "id": message["id"]}) + "\n").encode())
                        stream.flush()

        thread = threading.Thread(target=server)
        thread.start()
        try:
            self.assertEqual(qmp_execute(listener.getsockname()[1], "system_powerdown"), {})
        finally:
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual([message["execute"] for message in messages], ["qmp_capabilities", "system_powerdown"])

    def test_failed_spawn_closes_log(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "disk.qcow2"
            disk.touch()
            vm = VirtualMachine()
            with patch("androidbox.runtime.subprocess.Popen", side_effect=OSError("missing binary")):
                with self.assertRaises(OSError):
                    vm.start(VMConfig(disk=str(disk)), "qemu", "tcg", Path(directory) / "qemu.log")
            self.assertIsNone(vm.log)
            self.assertFalse(vm.running)

    def test_force_stop_escalates_and_reaps(self):
        vm = VirtualMachine()
        vm.process = Mock()
        vm.process.poll.return_value = None
        vm.process.wait.side_effect = [subprocess.TimeoutExpired("qemu", 5), 0]
        vm.terminate()
        vm.process.terminate.assert_called_once()
        vm.process.kill.assert_called_once()
        self.assertEqual(vm.process.wait.call_count, 2)

    def test_no_duplicate_start(self):
        vm = VirtualMachine()
        vm.process = Mock()
        vm.process.poll.return_value = None
        with self.assertRaisesRegex(RuntimeError, "already running"):
            vm.start(VMConfig(), "qemu", "tcg", Path("unused.log"))
