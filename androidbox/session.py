# AndroidBox — 由异猫工作群（mutantcat.org）发行
# GitHub: https://github.com/Mutantcat-Working-Group
"""Guest session state machine for the desktop client.

The window owns widgets, dialogs and the embedded display. This module owns
what the guest is doing: which operation is in flight, when QEMU exited, how a
failed start is retried, when the camera bridge is attached, and how a guest
disk is prepared and stored. Keeping that state out of the QMainWindow makes
it testable without a window and stops one file from knowing both QEMU and Qt.

Signals carry every decision to the view: ``log`` is raw runtime output for the
log pane, ``message`` is a user-facing line for the log and the status bar, and
the remaining signals describe lifecycle transitions the window must render.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import subprocess
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import guestdisk, runtime, seed
from .adb import executable as adb_executable
from .adb import install_apk as adb_install_apk
from .adb import transfer_files
from .camera import CameraStreamer
from .display import DisplayServer


# A host that suspends or drops QEMU gets a bounded number of automatic
# restarts before the user is left in control again.
MAX_GUEST_RESTARTS = 5

# The log file and the exit code are cheap to read, and 250 ms keeps the pane
# and the watchdog responsive without loading the GUI thread.
POLL_INTERVAL_MS = 250


class GuestSession(QObject):
    """Own one QEMU guest and every operation the desktop can start on it."""

    log = Signal(str)
    message = Signal(str)
    changed = Signal()
    started = Signal(str)
    stopped = Signal(int)
    prepared = Signal(str)
    failed = Signal(str, object, str)
    restarting = Signal(int, int)
    prepare_progress = Signal(int, int)
    transfer_progress = Signal(str)

    def __init__(self, parent=None, config=None, pool=None):
        super().__init__(parent)
        self.config = config or runtime.default_config(discover_disk=False)
        self.vm = runtime.VirtualMachine()
        self.pool = pool or ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.operation = None
        self.prepare_arch = None
        self.was_running = False
        self.shutdown_requested = False
        self.restarts = 0
        self.recovering = False
        self.pending_notes = []
        self.log_offset = 0
        self.log_path = runtime.state_directory() / "qemu.log"
        self.server = None
        self.camera = None
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self.poll)

    def start_polling(self):
        """Begin the watchdog; the window calls this once its widgets exist."""
        if not self.timer.isActive():
            self.timer.start()

    @property
    def busy(self):
        return self.future is not None

    @property
    def running(self):
        return self.vm.running

    def managed_disk(self):
        return guestdisk.managed_disk_path(runtime.normalize_arch(self.config.arch))

    def display_url(self):
        return self.server.url if self.server is not None else ""

    def ensure_seeds(self):
        """Rewrite the NoCloud seed for every disk this session may boot."""
        candidates = {}
        if self.config.disk:
            candidates[self.config.disk] = self.config.arch
        managed = self.managed_disk()
        if managed.is_file():
            candidates[str(managed)] = runtime.normalize_arch(self.config.arch)
        for disk, arch in candidates.items():
            try:
                seed.ensure_seed(seed.seed_path_for(disk), arch)
            except (OSError, ValueError) as error:
                self.log.emit(f"Could not write the first-boot seed for {disk}: {error}")

    def start(self):
        """Validate the settings and launch QEMU; False when that is refused."""
        if self.busy:
            return False
        if not self.recovering:
            self.restarts = 0
        self.recovering = False
        try:
            self.config.validate()
            try:
                guestdisk.repair_overlay_backing_format(Path(self.config.disk))
            except OSError as error:
                raise ValueError(f"Could not repair the guest disk header: {error}") from error
            server = DisplayServer()
        except (OSError, ValueError) as error:
            self.failed.emit("Start failed", error, "start")
            return False
        self.server = server
        self.log_offset = 0
        self.shutdown_requested = False
        self.message.emit("Starting QEMU")
        self.operation = "start"
        self.future = self.pool.submit(self._start_guest)
        self.changed.emit()
        return True

    def _start_guest(self):
        """Run QEMU and wait until its management socket answers."""
        config = replace(self.config)
        binary, accelerator = runtime.probe(config)
        driver = ""
        if config.audio != "off" or config.microphone != "off":
            # A host without a working sound backend must still boot the guest;
            # the worker only collects the note and never touches a widget.
            try:
                driver = runtime.audio_driver(binary)
            except (OSError, subprocess.SubprocessError) as error:
                self.pending_notes.append(f"Host sound is unavailable: {error}")
        self.vm.start(config, binary, accelerator, self.log_path, audio_driver=driver)
        try:
            for _ in range(60):
                if not self.vm.running:
                    raise RuntimeError(runtime.startup_failure_reason(self.log_path)
                                       or "QEMU exited during startup; see the runtime log")
                try:
                    self.vm.connect_display()
                    return accelerator
                except (OSError, ValueError, RuntimeError):
                    time.sleep(0.25)
            raise RuntimeError("QEMU management connection timed out")
        except Exception:
            self.vm.terminate()
            raise

    def stop(self, force=False):
        """Ask QEMU for a clean shutdown, or terminate it when forced."""
        self.restarts = 0
        operation = self.vm.terminate if force else self.vm.shutdown
        self.operation = "stop"
        self.future = self.pool.submit(operation)
        self.shutdown_requested = True
        self.changed.emit()

    def install_apk(self, adb, path):
        self.operation = "install"
        self.future = self.pool.submit(adb_install_apk, adb, self.adb_target(), path)
        self.message.emit("Waiting for Android authorization / installing APK")
        self.changed.emit()

    def upload(self, paths, adb):
        self.operation = "upload"
        self.future = self.pool.submit(transfer_files, adb, self.adb_target(), paths,
                                       progress=self.transfer_progress.emit)
        self.message.emit(f"Uploading {len(paths)} file(s) to the guest Download directory")
        self.changed.emit()

    def adb_target(self):
        return f"127.0.0.1:{self.vm.adb_port}"

    def prepare(self, arch, directory=None, local_image=None):
        """Download a cloud image and create the managed guest disk."""
        directory = Path(directory) if directory is not None else runtime.state_directory() / "guests"
        self.prepare_arch = arch
        self.operation = "prepare"

        def work():
            if local_image:
                return guestdisk.prepare(arch, directory, local_image=local_image)
            return guestdisk.prepare(arch, directory, progress=self._prepare_progress)

        self.future = self.pool.submit(work)
        self.changed.emit()

    def _prepare_progress(self, downloaded, total):
        percent = int(downloaded * 100 / total) if total else 0
        self.prepare_progress.emit(percent, downloaded)

    def poll(self):
        """Drain the runtime log, settle the worker, and watch the guest."""
        self._tail_log()
        if self.busy and self.future.done():
            self._settle()
        if self.was_running and not self.vm.running:
            self._guest_exited()
        self.changed.emit()

    def _tail_log(self):
        try:
            if not self.log_path.exists():
                return
            with self.log_path.open("rb") as stream:
                stream.seek(self.log_offset)
                content = stream.read(65536)
                self.log_offset = stream.tell()
        except OSError:
            return
        if content:
            self.log.emit(content.decode("utf-8", errors="replace").rstrip())

    def _settle(self):
        future, operation = self.future, self.operation
        self.future = None
        try:
            result = future.result()
        except Exception as error:
            if operation == "start":
                self.close_display()
            self.failed.emit(
                "Guest disk preparation failed" if operation == "prepare" else "Operation failed",
                error, operation)
            return
        if operation == "start":
            self.was_running = True
            self.started.emit(result)
            for note in self.pending_notes:
                self.message.emit(note)
            self.pending_notes.clear()
            if self.vm.audio_driver:
                self.message.emit(f"Guest sound: {self.vm.describe_audio()}")
            if self.config.camera != "off":
                self.start_camera()
        elif operation == "stop":
            self.message.emit("Shutdown requested" if self.vm.running else "Stopped")
        elif operation == "prepare":
            self._store_prepared(Path(result))
        else:
            self.message.emit(result or "Done")

    def _store_prepared(self, disk):
        try:
            config = replace(self.config, disk=str(disk), disk_format=runtime.disk_format(disk),
                             arch=self.prepare_arch or self.config.arch)
            runtime.save_config(config)
        except (OSError, ValueError) as error:
            self.failed.emit("Could not save the prepared guest disk", error, "prepare")
        else:
            self.config = config
            self.prepared.emit(str(disk))
            self.message.emit(f"Guest disk ready: {disk}")
            self.message.emit("The first boot installs the Android guest and can take several minutes")

    def _guest_exited(self):
        self.was_running = False
        self.vm.close_log()
        code = self.vm.process.returncode if self.vm.process is not None else 0
        self.close_display()
        self.stopped.emit(code or 0)
        # A clean exit is the guest powering itself off: restarting it here
        # would fight the user shutting Android down from inside the guest.
        if not self.shutdown_requested and code != 0:
            self.recover_guest(code)

    def recover_guest(self, code):
        """Start the guest again after an exit the user did not ask for."""
        if self.busy:
            return
        if self.restarts >= MAX_GUEST_RESTARTS:
            self.message.emit(f"QEMU keeps exiting ({code}); press Start to try again")
            return
        self.restarts += 1
        self.restarting.emit(self.restarts, MAX_GUEST_RESTARTS)
        self.message.emit(f"QEMU exited unexpectedly ({code}); restarting the guest "
                          f"({self.restarts} of {MAX_GUEST_RESTARTS})")
        self.recovering = True
        self.start()

    def start_camera(self):
        """Point the host webcam at the guest camera bridge."""
        if self.camera is not None or not self.vm.running:
            return
        self.camera = CameraStreamer(self.vm.camera_port, self)
        signal = getattr(self.camera, "status", None)
        if signal is not None:
            signal.connect(self.message.emit)
        # With ADB reachable the streamer can ask the guest which cameras
        # Android really sees, instead of claiming a success it cannot verify.
        probe = getattr(self.camera, "set_guest_probe", None)
        if probe is not None:
            probe(adb_executable(), self.adb_target())
        if not self.camera.start():
            self.camera = None

    def stop_camera(self):
        if self.camera is None:
            return
        streamer, self.camera = self.camera, None
        streamer.stop()

    def close_display(self):
        """Stop the camera and the local noVNC asset server."""
        self.stop_camera()
        if self.server is not None:
            self.server.close()
            self.server = None

    def close(self):
        """Release everything this session owns; safe to call twice."""
        self.timer.stop()
        self.stop_camera()
        self.vm.terminate()
        if self.server is not None:
            self.server.close()
            self.server = None
        self.pool.shutdown(wait=True)
