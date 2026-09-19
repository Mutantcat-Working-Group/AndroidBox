"""Environment for system executables launched from the packaged desktop."""

import os
import ntpath
import ctypes
import subprocess
import sys
import threading
from .bundled import contains_binary


_spawn_lock = threading.Lock()


def _get_dll_directory():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetDllDirectoryW
    function.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    function.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    ctypes.set_last_error(0)
    length = function(len(buffer), buffer)
    if not length and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    if length >= len(buffer):
        raise OSError("DLL directory exceeds supported length")
    return buffer.value or None


def _set_dll_directory(directory):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.SetDllDirectoryW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_int
    if not function(directory):
        raise ctypes.WinError(ctypes.get_last_error())


def popen(command, **kwargs):
    kwargs.setdefault("env", external_environment(command[0]))
    if sys.platform != "win32":
        return subprocess.Popen(command, **kwargs)
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
    # SetDllDirectory is process-wide. Serialize our spawns and restore before waiting.
    with _spawn_lock:
        if not getattr(sys, "frozen", False) or contains_binary(command[0]):
            return subprocess.Popen(command, **kwargs)
        original = _get_dll_directory()
        _set_dll_directory(None)
        try:
            return subprocess.Popen(command, **kwargs)
        finally:
            _set_dll_directory(original)


def run(command, *, timeout, check=False):
    with popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace") as child:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            child.kill()
            error.output, error.stderr = child.communicate()
            raise
        except BaseException:
            child.kill()
            child.wait()
            raise
        result = subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result


def external_environment(executable=None):
    environment = os.environ.copy()
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux") and not contains_binary(executable):
        # PyInstaller's private libraries must not override QEMU/ADB system libraries.
        original = environment.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original
    if getattr(sys, "frozen", False) and sys.platform == "win32" and not contains_binary(executable):
        root = getattr(sys, "_MEIPASS", None)
        if root and "PATH" in environment:
            root = ntpath.normcase(ntpath.abspath(root))

            def private_path(entry):
                path = ntpath.normcase(ntpath.abspath(entry.strip('"')))
                try:
                    return ntpath.commonpath([root, path]) == root
                except ValueError:
                    return False

            environment["PATH"] = ";".join(entry for entry in environment["PATH"].split(";") if not private_path(entry))
    return environment
