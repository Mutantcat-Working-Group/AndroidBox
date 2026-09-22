"""Keep the host awake for as long as the desktop window owns a running guest.

A host that suspends or drops its display takes the QEMU process and the
noVNC connection with it, so the window asks the operating system to stay
awake - including when the lid closes or the session goes idle - and gives
the request back when it closes.
"""

import ctypes
import shutil
import subprocess
import sys

from .process import popen


CAFFEINATE = ("caffeinate", "-d", "-i", "-s")
INHIBIT = ("systemd-inhibit", "--what=handle-lid-switch:sleep:idle",
           "--mode=block", "--why=AndroidBox guest is running", "sleep", "infinity")
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def _windows_stay_awake(enable=True):
    flags = ES_CONTINUOUS if not enable else ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    if not ctypes.windll.kernel32.SetThreadExecutionState(flags):
        raise ctypes.WinError(ctypes.get_last_error())


def _spawn(command):
    if not shutil.which(command[0]):
        return None
    return popen(list(command), stdin=subprocess.DEVNULL,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PowerSession:
    """Hold one wake lock, released when the desktop window closes."""

    def __init__(self):
        self.process = None
        self.held = False

    def acquire(self):
        """Ask the host to stay awake; return a name for what is holding it."""
        if self.held:
            return self.describe()
        try:
            if sys.platform == "win32":
                _windows_stay_awake()
                self.held = True
            elif sys.platform == "darwin":
                self.process = _spawn(CAFFEINATE)
                self.held = self.process is not None
            elif sys.platform.startswith("linux"):
                self.process = _spawn(INHIBIT)
                self.held = self.process is not None
        except (OSError, ValueError):
            self.held = False
        return self.describe()

    def release(self):
        """Give the wake lock back; safe to call more than once."""
        if not self.held:
            return
        self.held = False
        try:
            if sys.platform == "win32":
                _windows_stay_awake(False)
        except (OSError, ValueError):
            pass
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def describe(self):
        if not self.held:
            return ""
        if sys.platform == "win32":
            return "the Windows execution state"
        if sys.platform == "darwin":
            return "caffeinate"
        return "systemd-inhibit"
