"""Qt desktop shell for the QEMU display and the optional Linux-native backend."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import QLockFile, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QIcon, QPalette
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle, QToolBar,
    QVBoxLayout, QWidget,
)

from . import APP_ID, APP_NAME, guestdisk, seed
from .adb import install_apk, transfer_files, executable as adb_executable
from .display import DisplayServer
from .icons import icon
from .power import PowerSession
from .process import external_environment
from .runtime import (
    VMConfig, VirtualMachine, default_config, disk_format, executable, load_config,
    display_quality_level, normalize_arch, probe, save_config, state_directory,
)


# The host can lose the guest process when it suspends; give the desktop a
# bounded budget of automatic restarts before leaving the user in control.
MAX_GUEST_RESTARTS = 5


# One icon size for every toolbar button keeps the row visually even.
TOOLBAR_ICON_SIZE = 20


def build_toolbar(owner, toolbar, ink, brand, left_buttons, right_buttons):
    """Fill the toolbar and return its actions keyed by name.

    The brand leads, the runtime controls follow left-aligned, a stretch pushes
    the window controls against the right edge, and nothing separates the two
    groups: one icon-only row, three buttons per side, no divider in between.
    """
    actions = {}
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    toolbar.setIconSize(QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
    toolbar.addWidget(brand)

    def add(button):
        key, glyph, label, checkable = button
        action = QAction(icon(glyph, ink), label, owner)
        action.setToolTip(label)
        action.setCheckable(checkable)
        toolbar.addAction(action)
        actions[key] = action

    for button in left_buttons:
        add(button)
    stretch = QWidget(toolbar)
    stretch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    toolbar.addWidget(stretch)
    for button in right_buttons:
        add(button)
    return actions


def shield_drag_and_drop(widget):
    """Stop every widget inside the guest screen from eating drag events.

    The browser engine accepts drags for its own web content; leaving those
    widgets non-droppable lets the main window receive file drops that are
    dragged over the running screen.
    """
    widget.setAcceptDrops(False)
    for child in widget.findChildren(QWidget):
        child.setAcceptDrops(False)


class DisplayView(QWebEngineView):
    """The guest screen, which never handles drag and drop itself."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Chromium turns drops on by default to grab files for web content.
        self.setAcceptDrops(False)

    def dragEnterEvent(self, event):
        event.ignore()

    def dragMoveEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AndroidBox Settings")
        self.setMinimumWidth(540)
        form = QFormLayout(self)
        self.disk = self.path_row(form, "Linux guest disk", config.disk)
        self.binary = self.path_row(form, "QEMU executable", config.qemu)
        self.firmware = self.path_row(form, "UEFI firmware", config.firmware)
        self.arch = QComboBox()
        self.arch.addItems(["x86_64", "aarch64"])
        self.arch.setCurrentText(config.arch)
        form.addRow("Guest architecture", self.arch)
        self.format = QComboBox()
        self.format.addItems(["qcow2", "raw"])
        self.format.setCurrentText(config.disk_format)
        form.addRow("Disk format", self.format)
        self.accel = QComboBox()
        self.accel.addItems(["auto", "tcg", "kvm", "hvf", "whpx"])
        self.accel.setCurrentText(config.accelerator)
        form.addRow("Acceleration", self.accel)
        self.cpu_mode = QComboBox()
        self.cpu_mode.setToolTip("Host passes the CPU model through to the guest; max offers the "
                                 "widest feature set; qemu64 is the portable x86_64 baseline.")
        self.update_cpu_models(config.cpu_mode)
        form.addRow("CPU model", self.cpu_mode)
        self.cache = QComboBox()
        self.cache.addItems(["writeback", "none", "unsafe"])
        self.cache.setCurrentText(config.disk_cache)
        self.cache.setToolTip("Writeback is the balanced default, none bypasses the host page cache, "
                              "unsafe ignores guest flush requests and risks data on host crashes.")
        form.addRow("Disk cache", self.cache)
        self.tcg = QComboBox()
        self.tcg.addItems(["auto", "multi", "single"])
        self.tcg.setCurrentText(config.tcg_threads)
        self.tcg.setToolTip("Multi-threaded TCG spreads guest CPU emulation over host threads; "
                            "single keeps it on one thread and can help some hosts.")
        form.addRow("TCG threads", self.tcg)
        self.quality = QComboBox()
        self.quality.addItems(["responsive", "balanced", "sharp"])
        self.quality.setCurrentText(config.display_quality)
        self.quality.setToolTip(
            "Display quality. Responsive sends lightly compressed frames so mouse and "
            "touch input feel immediate; sharp costs more encoding work on both ends.")
        form.addRow("Display quality", self.quality)
        self.memory = QSpinBox()
        self.memory.setRange(1024, 262144)
        self.memory.setSingleStep(1024)
        self.memory.setSuffix(" MiB")
        self.memory.setValue(config.memory_mb)
        form.addRow("Memory", self.memory)
        self.cpus = QSpinBox()
        self.cpus.setRange(1, 128)
        self.cpus.setValue(config.cpus)
        form.addRow("CPU cores", self.cpus)
        self.arch.currentTextChanged.connect(self.update_detected_paths)
        self.binary.textChanged.connect(self.update_detected_paths)
        self.arch.currentTextChanged.connect(lambda: self.update_cpu_models())
        self.update_detected_paths()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def update_detected_paths(self):
        config = VMConfig(arch=self.arch.currentText(), qemu=self.binary.text().strip())
        try:
            binary = executable(config)
        except ValueError:
            binary = "Not found"
        self.binary.setPlaceholderText(f"Automatic: {binary}")
        self.binary.setToolTip(f"Automatic: {binary}")
        firmware = config.resolved_firmware()
        self.firmware.setPlaceholderText(f"Automatic: {firmware or ('Not found' if config.arch == 'aarch64' else 'Not required')}")
        self.firmware.setToolTip(self.firmware.placeholderText())

    def update_cpu_models(self, preferred=None):
        values = ["auto", "host", "max", "qemu64"] if self.arch.currentText() == "x86_64" else ["auto", "host", "max"]
        selected = preferred or self.cpu_mode.currentText()
        self.cpu_mode.clear()
        self.cpu_mode.addItems(values)
        if selected in values:
            self.cpu_mode.setCurrentText(selected)

    def path_row(self, form, name, value):
        field = QLineEdit(value)
        button = QPushButton()
        button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        button.setToolTip(f"Select {name.lower()}")
        button.setFixedWidth(36)
        def browse():
            path, _ = QFileDialog.getOpenFileName(self, name, field.text())
            if path:
                field.setText(path)
                if name == "Linux guest disk":
                    try:
                        self.format.setCurrentText(disk_format(path))
                    except OSError as error:
                        QMessageBox.warning(self, APP_NAME, str(error))
        button.clicked.connect(browse)
        row = QHBoxLayout()
        row.addWidget(field)
        row.addWidget(button)
        form.addRow(name, row)
        return field

    def config(self):
        return VMConfig(disk=self.disk.text().strip(), qemu=self.binary.text().strip(),
                        firmware=self.firmware.text().strip(), arch=self.arch.currentText(),
                        memory_mb=self.memory.value(), cpus=self.cpus.value(),
                        accelerator=self.accel.currentText(), disk_format=self.format.currentText(),
                        cpu_mode=self.cpu_mode.currentText(), disk_cache=self.cache.currentText(),
                        tcg_threads=self.tcg.currentText(),
                        display_quality=self.quality.currentText())


class LocalImageDialog(QDialog):
    """Pick an already downloaded cloud image and the architecture it was built for."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Use a local cloud image")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.path = QLineEdit()
        self.path.setPlaceholderText("ubuntu-24.04-minimal-cloudimg-{amd64,arm64}.img")
        browse = QPushButton()
        browse.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse.setToolTip("Select the cloud image")
        browse.setFixedWidth(36)
        browse.clicked.connect(self.select_image)
        row = QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        form.addRow("Cloud image", row)
        self.arch = QComboBox()
        self.arch.addItems(["x86_64", "aarch64"])
        self.arch.setCurrentText(normalize_arch(platform.machine()))
        self.arch.setToolTip("Architecture of the image; it decides which QEMU binary boots it")
        form.addRow("Guest architecture", self.arch)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def select_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select the Ubuntu cloud image",
                                              str(state_directory() / "guests"),
                                              "Cloud images (*.img);;All files (*)")
        if path:
            self.path.setText(path)

    def image(self):
        return self.path.text().strip()


class MainWindow(QMainWindow):
    prepare_progress = Signal(int, int)
    transfer_progress = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setMinimumSize(640, 480)
        self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/AppIcon.png")))
        self.vm = VirtualMachine()
        self.server = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.operation = None
        self.prepare_arch = None
        self.was_running = False
        self.native_process = None
        self.log_offset = 0
        self.log_path = state_directory() / "qemu.log"
        self.shutdown_requested = False
        self.restarts = 0
        self.recovering = False
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        try:
            self.config = load_config()
        except (ValueError, OSError) as error:
            self.config = default_config(discover_disk=False)
            self.log.appendPlainText(str(error))
        candidates = {}
        if self.config.disk:
            candidates[self.config.disk] = self.config.arch
        managed = self.managed_disk()
        if managed.is_file():
            candidates[str(managed)] = normalize_arch(self.config.arch)
        for disk, arch in candidates.items():
            try:
                seed.ensure_seed(seed.seed_path_for(disk), arch)
            except (OSError, ValueError) as error:
                self.log.appendPlainText(f"Could not write the first-boot seed for {disk}: {error}")
        toolbar = QToolBar("Runtime")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        brand = QLabel("  AndroidBox  ")
        brand.setStyleSheet("font-size: 18px; font-weight: 600;")
        ink = toolbar.palette().color(QPalette.ColorRole.WindowText).name()
        left_buttons = [
            ("start", "play", "Start", False),
            ("stop", "stop", "Shut down", False),
            ("install", "install", "Install APK", False),
        ]
        if sys.platform.startswith("linux"):
            left_buttons.append(("native", "computer", "Linux native", False))
        right_buttons = [
            ("settings", "gear", "Settings", False),
            ("logs", "exclamation", "Logs", True),
            ("fullscreen", "fullscreen", "Full screen", False),
        ]
        actions = build_toolbar(self, toolbar, ink, brand, left_buttons, right_buttons)
        self.start_action = actions["start"]
        self.stop_action = actions["stop"]
        self.install_action = actions["install"]
        self.settings_action = actions["settings"]
        self.logs_action = actions["logs"]
        self.fullscreen_action = actions["fullscreen"]
        self.native_action = actions.get("native")
        self.start_action.triggered.connect(self.start_vm)
        self.stop_action.triggered.connect(self.stop_vm)
        self.install_action.triggered.connect(self.install_apk)
        self.settings_action.triggered.connect(self.settings)
        self.logs_action.triggered.connect(lambda: self.log.setVisible(self.logs_action.isChecked()))
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        if self.native_action is not None:
            self.native_action.triggered.connect(self.native)
        self.stack = QStackedWidget()
        empty = QWidget()
        empty.setStyleSheet("background: #16191b; color: #d5dcdf;")
        layout = QVBoxLayout(empty)
        layout.addStretch()
        image = QLabel()
        image.setPixmap(self.windowIcon().pixmap(80, 80))
        image.setAlignment(Qt.AlignCenter)
        layout.addWidget(image)
        self.empty_title = QLabel("AndroidBox")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(self.empty_title)
        self.empty_status = QLabel("Stopped")
        self.empty_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_status)
        self.prepare_button = QPushButton("Prepare example guest disk")
        self.prepare_button.setToolTip(
            "Download the verified Ubuntu 24.04 minimal cloud image for this computer's "
            "architecture and create a ready-to-boot AndroidBox guest disk")
        self.prepare_button.clicked.connect(self.prepare_guest_disk)
        self.local_button = QPushButton("Use a local image")
        self.local_button.setToolTip(
            "Create the guest disk from an Ubuntu 24.04 minimal cloud image you already "
            "downloaded; its SHA256 is still verified against the official manifest")
        self.local_button.clicked.connect(self.use_local_image)
        prepare_row = QHBoxLayout()
        prepare_row.addStretch()
        prepare_row.addWidget(self.prepare_button)
        prepare_row.addWidget(self.local_button)
        prepare_row.addStretch()
        layout.addLayout(prepare_row)
        layout.addStretch()
        self.stack.addWidget(empty)
        self.view = DisplayView()
        shield_drag_and_drop(self.view)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.stack.addWidget(self.view)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.log)
        splitter.setSizes([600, 140])
        self.setCentralWidget(splitter)
        self.log.hide()
        shield_drag_and_drop(self.log)
        self.prepare_progress.connect(self.on_prepare_progress)
        self.transfer_progress.connect(self.on_transfer_progress)
        self.update_empty_state()
        self.statusBar().showMessage("Stopped")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        self.power = PowerSession()
        held = self.power.acquire()
        if held:
            self.log.appendPlainText(
                f"The host is kept awake with {held}; a closed lid or a sleeping "
                "display will not interrupt the running guest")
        self.update_actions()

    def report(self, message):
        self.log.appendPlainText(message)
        self.statusBar().showMessage(message)

    def report_error(self, summary, error):
        """Show a failure with its full text behind a details button.

        Preparation failures carry one line per mirror, which does not survive
        being squeezed into a single message box label.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(summary)
        box.setDetailedText(str(error))
        box.exec()

    def showEvent(self, event):
        super().showEvent(event)
        # The guest screen builds its browser child widgets lazily; re-apply
        # the shield so the freshly created ones cannot eat drops either.
        shield_drag_and_drop(self.view)

    def dragEnterEvent(self, event):
        self.offer_drop(event)

    def dragMoveEvent(self, event):
        self.offer_drop(event)

    def offer_drop(self, event):
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()] if mime is not None else []
        files = [path for path in paths if Path(path).is_file()]
        if not files:
            event.ignore()
            return
        event.acceptProposedAction()
        self.upload_files(files)

    def upload_files(self, paths):
        """Copy dragged files into the guest and install any APK among them."""
        if not self.vm.running:
            QMessageBox.warning(self, APP_NAME, "Start the guest before uploading files to it.")
            return
        if self.future is not None:
            QMessageBox.warning(self, APP_NAME, "Wait for the current operation to finish before uploading.")
            return
        adb = adb_executable()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB not found. Install Android SDK Platform Tools and add adb to PATH.")
            return
        target = f"127.0.0.1:{self.vm.adb_port}"
        self.operation = "upload"
        self.future = self.pool.submit(transfer_files, adb, target, paths,
                                       progress=self.transfer_progress.emit)
        self.report(f"Uploading {len(paths)} file(s) to the guest Download directory")
        self.update_actions()

    def on_transfer_progress(self, message):
        self.report(message)

    def update_actions(self):
        busy = self.future is not None
        running = self.vm.running
        native_running = self.native_process is not None and self.native_process.poll() is None
        self.start_action.setEnabled(not busy and not running and not native_running)
        self.settings_action.setEnabled(not busy and not running)
        self.stop_action.setEnabled(not busy and running)
        self.install_action.setEnabled(not busy and running and not self.shutdown_requested)
        if self.native_action is not None:
            self.native_action.setEnabled(not busy and not running and not native_running)
        self.update_empty_state()

    def managed_disk(self):
        return guestdisk.managed_disk_path(normalize_arch(self.config.arch))

    def update_empty_state(self):
        ready = bool(self.config.disk) or self.managed_disk().is_file()
        self.prepare_button.setVisible(not ready and self.future is None)
        self.local_button.setVisible(not ready and self.future is None)
        # Only adjust the two idle labels; Starting..., Start failed and the
        # preparation progress texts are event-driven and must survive polling.
        if self.future is None and not self.vm.running and self.empty_status.text() in ("Stopped", "No guest disk yet"):
            self.empty_status.setText("Stopped" if ready else "No guest disk yet")

    def prepare_guest_disk(self):
        arch = normalize_arch(platform.machine())
        directory = state_directory() / "guests"
        self.empty_status.setText("Preparing guest disk...")
        self.report(f"Preparing an example guest disk for {arch} in {directory}")

        def progress(downloaded, total):
            percent = int(downloaded * 100 / total) if total else 0
            self.prepare_progress.emit(percent, downloaded)

        def work():
            return guestdisk.prepare(arch, directory, progress=progress)

        self.prepare_arch = arch
        self.operation = "prepare"
        self.future = self.pool.submit(work)
        self.update_actions()

    def use_local_image(self):
        dialog = LocalImageDialog(self)
        if dialog.exec() != QDialog.Accepted or not dialog.image():
            return
        arch = normalize_arch(dialog.arch.currentText())
        directory = state_directory() / "guests"
        self.empty_status.setText("Preparing guest disk...")
        self.report(f"Preparing a {arch} guest disk from {dialog.image()}")

        def work():
            return guestdisk.prepare(arch, directory, local_image=dialog.image())

        self.prepare_arch = arch
        self.operation = "prepare"
        self.future = self.pool.submit(work)
        self.update_actions()

    def on_prepare_progress(self, percent, downloaded):
        self.empty_status.setText(f"Preparing guest disk - {percent}%")
        self.statusBar().showMessage(f"Downloading example image - {percent}% ({downloaded // 1024 // 1024} MiB)")

    def settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                config = dialog.config()
                save_config(config)
                self.config = config
                self.report("Settings saved")
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, APP_NAME, str(error))

    def start_vm(self):
        if not self.recovering:
            self.restarts = 0
        self.recovering = False
        if not self.config.disk:
            path, _ = QFileDialog.getOpenFileName(self, "Select bootable Linux/Android guest disk",
                                                str(state_directory() / "guests"),
                                                "Guest disks (*.qcow2 *.raw *.img);;All files (*)")
            if not path:
                return
            try:
                config = replace(self.config, disk=path, disk_format=disk_format(path))
                save_config(config)
                self.config = config
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, APP_NAME, str(error))
                return
        try:
            self.config.validate()
            try:
                guestdisk.repair_overlay_backing_format(Path(self.config.disk))
            except OSError as error:
                raise ValueError(f"Could not repair the guest disk header: {error}") from error
            self.server = DisplayServer()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return
        self.log_offset = 0
        self.shutdown_requested = False
        self.empty_status.setText("Starting...")
        self.report("Starting QEMU")
        config = replace(self.config)
        def start():
            binary, accelerator = probe(config)
            self.vm.start(config, binary, accelerator, self.log_path)
            try:
                for _ in range(60):
                    if not self.vm.running:
                        raise RuntimeError("QEMU exited during startup; see the runtime log")
                    try:
                        self.vm.connect_display()
                        return accelerator
                    except (OSError, ValueError, RuntimeError):
                        time.sleep(0.25)
                raise RuntimeError("QEMU management connection timed out")
            except Exception:
                self.vm.terminate()
                raise
        self.operation = "start"
        self.future = self.pool.submit(start)
        self.update_actions()

    def stop_vm(self):
        self.restarts = 0
        if self.shutdown_requested:
            answer = QMessageBox.question(self, "Force stop", "Force stop the virtual machine? Unsaved guest data may be lost.")
            if answer != QMessageBox.Yes:
                return
            operation = self.vm.terminate
        else:
            operation = self.vm.shutdown
        self.operation = "stop"
        self.future = self.pool.submit(operation)
        self.shutdown_requested = True
        self.stop_action.setToolTip("Force stop")
        self.update_actions()

    def install_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, "Install APK", "", "Android packages (*.apk)")
        if not path:
            return
        adb = adb_executable()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB not found. Install Android SDK Platform Tools and add adb to PATH.")
            return
        target = f"127.0.0.1:{self.vm.adb_port}"
        self.operation = "install"
        self.future = self.pool.submit(install_apk, adb, target, path)
        self.report("Waiting for Android authorization / installing APK")
        self.update_actions()

    def native(self):
        binary = shutil.which("androidbox")
        if not binary:
            QMessageBox.warning(self, APP_NAME, "Install the Linux-native runtime with make install first.")
            return
        if not os.environ.get("WAYLAND_DISPLAY"):
            QMessageBox.warning(self, APP_NAME, "The Linux-native backend requires a Wayland session.")
            return
        try:
            self.native_process = subprocess.Popen([binary, "show-full-ui"], env=external_environment())
            self.report("Linux-native session launched in its own window")
            self.update_actions()
        except OSError as error:
            QMessageBox.warning(self, APP_NAME, str(error))

    def poll(self):
        if self.log_path.exists():
            with self.log_path.open("rb") as stream:
                stream.seek(self.log_offset)
                content = stream.read(65536)
                self.log_offset = stream.tell()
            if content:
                self.log.appendPlainText(content.decode("utf-8", errors="replace").rstrip())
        if self.future is not None and self.future.done():
            future, operation = self.future, self.operation
            self.future = None
            try:
                result = future.result()
                if operation == "start":
                    self.was_running = True
                    quality = display_quality_level(self.config.display_quality)
                    self.view.setUrl(QUrl(
                        f"{self.server.url}#port={self.vm.websocket_port}"
                        f"&password={self.vm.password}&quality={quality}"))
                    shield_drag_and_drop(self.view)
                    self.stack.setCurrentIndex(1)
                    self.report(f"QEMU running | {self.config.arch} | {result.upper()}")
                elif operation == "stop":
                    self.report("Shutdown requested" if self.vm.running else "Stopped")
                elif operation == "prepare":
                    disk = Path(result)
                    try:
                        config = replace(self.config, disk=str(disk), disk_format=disk_format(disk),
                                         arch=self.prepare_arch or self.config.arch)
                        save_config(config)
                    except (OSError, ValueError) as error:
                        self.empty_status.setText("Preparation failed")
                        self.report_error("Could not save the prepared guest disk", error)
                    else:
                        self.config = config
                        self.empty_status.setText("Guest disk ready")
                        self.report(f"Guest disk ready: {disk}")
                        self.report("The first boot installs the Android guest and can take several minutes")
                else:
                    self.report(result or "Done")
            except Exception as error:
                self.report(str(error))
                if operation == "start":
                    self.empty_status.setText("Start failed")
                    self.close_display()
                elif operation == "prepare":
                    self.empty_status.setText("Preparation failed")
                self.report_error("Guest disk preparation failed" if operation == "prepare"
                                  else "Operation failed", error)
        if self.was_running and not self.vm.running:
            self.was_running = False
            self.vm.close_log()
            code = self.vm.process.returncode
            self.close_display()
            self.empty_status.setText("Stopped" if code == 0 else f"QEMU exited ({code})")
            self.report(self.empty_status.text())
            self.stop_action.setToolTip("Shut down")
            # A clean exit is the guest powering itself off: restarting it here
            # would fight the user shutting Android down from inside the guest.
            if not self.shutdown_requested and code != 0:
                self.recover_guest(code)
        self.update_actions()

    def close_display(self):
        self.view.setUrl(QUrl("about:blank"))
        self.stack.setCurrentIndex(0)
        if self.server:
            self.server.close()
            self.server = None

    def recover_guest(self, code):
        """Start the guest again after an exit the user did not ask for.

        A host that suspends takes the QEMU process with it. The guest disk
        and the saved settings are unchanged, so retry a bounded number of
        times before handing control back to the user.
        """
        if self.future is not None:
            return
        if self.restarts >= MAX_GUEST_RESTARTS:
            self.report(f"QEMU keeps exiting ({code}); press Start to try again")
            return
        self.restarts += 1
        self.empty_status.setText("Recovering the guest...")
        self.report(f"QEMU exited unexpectedly ({code}); restarting the guest "
                    f"({self.restarts} of {MAX_GUEST_RESTARTS})")
        self.recovering = True
        self.start_vm()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def closeEvent(self, event):
        if self.future is not None:
            QMessageBox.information(self, APP_NAME, "Wait for the current operation to finish before closing.")
            event.ignore()
            return
        if self.vm.running:
            answer = QMessageBox.question(self, APP_NAME, "Force stop AndroidBox and close? Shut down first to preserve guest data.")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.timer.stop()
        self.vm.terminate()
        self.close_display()
        self.power.release()
        self.pool.shutdown(wait=True)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Mutantcat")
    app.setOrganizationDomain("mutantcat.org")
    app.setDesktopFileName(APP_ID)
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.warning(None, APP_NAME, "AndroidBox is already open for this user.")
        return 1
    window = MainWindow()
    window.show()
    return app.exec()
