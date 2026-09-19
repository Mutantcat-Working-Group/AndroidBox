import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from androidbox import process
from androidbox.process import external_environment


class ProcessTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows DLL inheritance requires a Windows host")
    def test_native_windows_child_does_not_inherit_bundle_directory(self):
        original = process._get_dll_directory()
        with tempfile.TemporaryDirectory(prefix="androidbox-dll-") as directory:
            try:
                process._set_dll_directory(directory)
                with patch("sys.frozen", True, create=True):
                    result = process.run([sys.executable, "-c", "import ctypes; "
                                          "b=ctypes.create_unicode_buffer(32768); "
                                          "ctypes.windll.kernel32.GetDllDirectoryW(len(b), b); print(b.value)"],
                                         timeout=10, check=True)
                self.assertEqual(result.stdout.strip(), "")
                self.assertEqual(process._get_dll_directory(), directory)
            finally:
                process._set_dll_directory(original)

    def test_external_windows_path_excludes_private_libraries_only(self):
        with patch("sys.frozen", True, create=True), patch("sys.platform", "win32"), \
                patch("sys._MEIPASS", "C:/App/_internal", create=True), \
                patch.object(process, "contains_binary", return_value=False), \
                patch.dict(os.environ, {"PATH": 'C:/Windows;C:/App/_internal;"C:\\App\\_internal\\PySide6";C:/App/_internal-other'}, clear=True):
            environment = external_environment("C:/QEMU/qemu.exe")
        self.assertEqual(environment["PATH"], "C:/Windows;C:/App/_internal-other")

    def test_external_windows_spawn_restores_dll_directory_immediately(self):
        events = []
        with patch("sys.frozen", True, create=True), patch("sys.platform", "win32"), \
                patch.object(process, "contains_binary", return_value=False), \
                patch.object(process, "_get_dll_directory", return_value="C:/bundle"), \
                patch.object(process, "_set_dll_directory", side_effect=lambda value: events.append(value)), \
                patch("subprocess.Popen", side_effect=lambda *args, **kwargs: events.append("spawn") or Mock()) as spawn:
            process.popen(["external.exe"])
        self.assertEqual(events, [None, "spawn", "C:/bundle"])
        self.assertEqual(spawn.call_args.kwargs["creationflags"] & 0x08000000, 0x08000000)

    def test_windows_spawn_failure_restores_directory(self):
        with patch("sys.frozen", True, create=True), patch("sys.platform", "win32"), \
                patch.object(process, "contains_binary", return_value=False), \
                patch.object(process, "_get_dll_directory", return_value="C:/bundle"), \
                patch.object(process, "_set_dll_directory") as setter, \
                patch("subprocess.Popen", side_effect=OSError("spawn failed")), \
                self.assertRaisesRegex(OSError, "spawn failed"):
            process.popen(["external.exe"])
        self.assertEqual([call.args[0] for call in setter.call_args_list], [None, "C:/bundle"])

    def test_bundled_windows_binary_keeps_dll_directory(self):
        with patch("sys.frozen", True, create=True), patch("sys.platform", "win32"), \
                patch.object(process, "contains_binary", return_value=True), \
                patch.object(process, "_set_dll_directory") as setter, \
                patch("subprocess.Popen"):
            process.popen(["bundled.exe"])
        setter.assert_not_called()

    def test_run_collects_output_and_propagates_exit_status(self):
        result = process.run([sys.executable, "-c", "print('ok')"], timeout=10, check=True)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(result.returncode, 0)
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            process.run([sys.executable, "-c", "import sys; print('bad'); sys.exit(3)"], timeout=10, check=True)
        self.assertEqual(raised.exception.returncode, 3)
        self.assertIn("bad", raised.exception.stdout)

    def test_run_timeout_kills_and_reaps(self):
        child = Mock()
        child.__enter__ = Mock(return_value=child)
        child.__exit__ = Mock(return_value=False)
        child.communicate.side_effect = [subprocess.TimeoutExpired("test", 1), ("partial", "error")]
        with patch.object(process, "popen", return_value=child), self.assertRaises(subprocess.TimeoutExpired):
            process.run(["test"], timeout=1)
        child.kill.assert_called_once()
        self.assertEqual(child.communicate.call_count, 2)

    def test_bundled_linux_binary_keeps_private_library_path(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.frozen", True, create=True), patch("sys.platform", "linux"), \
                patch("sys._MEIPASS", directory, create=True), \
                patch.dict(os.environ, {"LD_LIBRARY_PATH": directory, "LD_LIBRARY_PATH_ORIG": "/system/lib"}, clear=True):
            binary = Path(directory) / "runtime/bin/qemu-system-x86_64"
            self.assertEqual(external_environment(str(binary))["LD_LIBRARY_PATH"], directory)

    def test_external_binary_never_keeps_private_library_path(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.frozen", True, create=True), patch("sys.platform", "linux"), \
                patch("sys._MEIPASS", directory, create=True), \
                patch.dict(os.environ, {"LD_LIBRARY_PATH": directory}, clear=True):
            binary = Path(directory) / "runtime-other/bin/qemu"
            self.assertNotIn("LD_LIBRARY_PATH", external_environment(str(binary)))

    def test_frozen_linux_restores_original_library_path(self):
        with patch("sys.frozen", True, create=True), patch("sys.platform", "linux"), \
                patch.dict(os.environ, {"LD_LIBRARY_PATH": "/app/_internal", "LD_LIBRARY_PATH_ORIG": "/system/lib"}, clear=True):
            environment = external_environment()
            self.assertEqual(environment["LD_LIBRARY_PATH"], "/system/lib")
            self.assertNotIn("LD_LIBRARY_PATH_ORIG", environment)
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/app/_internal")

    def test_frozen_linux_removes_injected_library_path(self):
        with patch("sys.frozen", True, create=True), patch("sys.platform", "linux"), \
                patch.dict(os.environ, {"LD_LIBRARY_PATH": "/app/_internal", "PATH": "/usr/bin"}, clear=True):
            self.assertEqual(external_environment(), {"PATH": "/usr/bin"})

    def test_unfrozen_environment_is_preserved(self):
        with patch("sys.frozen", False, create=True), \
                patch.dict(os.environ, {"LD_LIBRARY_PATH": "/custom/lib"}, clear=True):
            self.assertEqual(external_environment(), dict(os.environ))
