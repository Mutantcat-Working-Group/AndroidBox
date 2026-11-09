# AndroidBox — 由异猫工作群（mutantcat.org）发行
# GitHub: https://github.com/Mutantcat-Working-Group
"""Qt desktop shell for the QEMU display and the optional Linux-native backend."""

from dataclasses import replace
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from PySide6.QtCore import QLockFile, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QIcon, QPalette
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle, QToolBar,
    QVBoxLayout, QWidget,
)

from . import APP_ID, APP_NAME, PUBLISHER_LABEL, PUBLISHER_URL
from .adb import executable as adb_executable
from .icons import icon
from .power import PowerSession
from .preview import CameraPreview
from .process import external_environment
from .runtime import (
    VMConfig, default_config, disk_format, executable, load_config,
    display_quality_level, normalize_arch, save_config, state_directory,
)
from .session import GuestSession



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
        self.audio = self.mode_row(form, "Audio output", config.audio,
            "Attach a sound card to the guest so Android sounds and app media play "
            "through this computer's speakers. Off leaves the guest silent.")
        self.microphone = self.mode_row(form, "Microphone", config.microphone,
            "Attach a microphone to the guest so voice notes, calls and recording "
            "apps can hear this computer's input.")
        self.camera = self.mode_row(form, "Camera", config.camera,
            "Stream this computer's webcam into the guest so the Android camera app "
            "sees a live picture. Without a webcam the guest gets a test pattern.")
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
        self.publisher = self.publisher_row(form)
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

    def publisher_row(self, form):
        publisher = QLabel(PUBLISHER_LABEL)
        publisher.setTextInteractionFlags(Qt.TextSelectableByMouse)
        link = QLabel(f'<a href="{PUBLISHER_URL}">{PUBLISHER_URL}</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(publisher)
        layout.addWidget(link)
        layout.addStretch()
        form.addRow("Publisher", row)
        return publisher

    def update_cpu_models(self, preferred=None):
        values = ["auto", "host", "max", "qemu64"] if self.arch.currentText() == "x86_64" else ["auto", "host", "max"]
        selected = preferred or self.cpu_mode.currentText()
        self.cpu_mode.clear()
        self.cpu_mode.addItems(values)
        if selected in values:
            self.cpu_mode.setCurrentText(selected)

    def mode_row(self, form, name, value, tooltip):
        box = QComboBox()
        box.addItems(["auto", "off"])
        box.setCurrentText(value)
        box.setToolTip(tooltip)
        form.addRow(name, box)
        return box

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
                        display_quality=self.quality.currentText(),
                        audio=self.audio.currentText(),
                        microphone=self.microphone.currentText(),
                        camera=self.camera.currentText())


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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setMinimumSize(640, 480)
        self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/AppIcon.png")))
        self.native_process = None
        self.preview = None
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        try:
            config = load_config()
        except (ValueError, OSError) as error:
            config = default_config(discover_disk=False)
            self.log.appendPlainText(str(error))
        self.session = GuestSession(self, config=config)
        self.session.log.connect(self.log.appendPlainText)
        self.session.message.connect(self.report)
        self.session.ensure_seeds()
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
            ("preview", "camera", "Camera preview", False),
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
        self.preview_action = actions["preview"]
        self.settings_action = actions["settings"]
        self.logs_action = actions["logs"]
        self.fullscreen_action = actions["fullscreen"]
        self.native_action = actions.get("native")
        self.start_action.triggered.connect(self.start_vm)
        self.stop_action.triggered.connect(self.stop_vm)
        self.install_action.triggered.connect(self.install_apk)
        self.preview_action.triggered.connect(self.show_preview)
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
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image)
        self.empty_title = QLabel("AndroidBox")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(self.empty_title)
        self.empty_status = QLabel("Stopped")
        self.empty_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.stack.addWidget(self.view)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.log)
        splitter.setSizes([600, 140])
        self.setCentralWidget(splitter)
        self.log.hide()
        shield_drag_and_drop(self.log)
        # The session owns the state machine; the window only renders it.
        self.session.changed.connect(self.update_actions)
        self.session.started.connect(self.on_started)
        self.session.stopped.connect(self.on_stopped)
        self.session.prepared.connect(self.on_prepared)
        self.session.failed.connect(self.on_failed)
        self.session.restarting.connect(self.on_restarting)
        self.session.prepare_progress.connect(self.on_prepare_progress)
        self.session.transfer_progress.connect(self.on_transfer_progress)
        self.session.start_polling()
        self.update_empty_state()
        self.statusBar().showMessage("Stopped")
        self.power = PowerSession()
        held = self.power.acquire()
        if held:
            self.log.appendPlainText(
                f"The host is kept awake with {held}; a closed lid or a sleeping "
                "display will not interrupt the running guest")
        self.update_actions()

    @property
    def config(self):
        return self.session.config

    @config.setter
    def config(self, value):
        self.session.config = value

    @property
    def vm(self):
        return self.session.vm

    def report(self, message):
        self.log.appendPlainText(message)
        self.statusBar().showMessage(message)

    def report_error(self, summary, error):
        """Show a failure with its full text behind a details button.

        Preparation failures carry one line per mirror, which does not survive
        being squeezed into a single message box label.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
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
        if not self.session.vm.running:
            QMessageBox.warning(self, APP_NAME, "Start the guest before uploading files to it.")
            return
        if self.session.busy:
            QMessageBox.warning(self, APP_NAME, "Wait for the current operation to finish before uploading.")
            return
        adb = adb_executable()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB not found. Install Android SDK Platform Tools and add adb to PATH.")
            return
        self.session.upload(paths, adb)

    def on_transfer_progress(self, message):
        self.report(message)

    def update_actions(self):
        busy = self.session.busy
        running = self.session.vm.running
        native_running = self.native_process is not None and self.native_process.poll() is None
        self.start_action.setEnabled(not busy and not running and not native_running)
        self.settings_action.setEnabled(not busy and not running)
        self.stop_action.setEnabled(not busy and running)
        self.stop_action.setToolTip("Force stop" if self.session.shutdown_requested else "Shut down")
        self.install_action.setEnabled(not busy and running and not self.session.shutdown_requested)
        self.preview_action.setEnabled(running and not self.session.shutdown_requested)
        if self.native_action is not None:
            self.native_action.setEnabled(not busy and not running and not native_running)
        self.update_empty_state()

    def managed_disk(self):
        return self.session.managed_disk()

    def update_empty_state(self):
        ready = bool(self.config.disk) or self.managed_disk().is_file()
        self.prepare_button.setVisible(not ready and not self.session.busy)
        self.local_button.setVisible(not ready and not self.session.busy)
        # Only adjust the two idle labels; Starting..., Start failed and the
        # preparation progress texts are event-driven and must survive polling.
        if not self.session.busy and not self.session.vm.running and \
                self.empty_status.text() in ("Stopped", "No guest disk yet"):
            self.empty_status.setText("Stopped" if ready else "No guest disk yet")

    def prepare_guest_disk(self):
        arch = normalize_arch(platform.machine())
        directory = state_directory() / "guests"
        self.empty_status.setText("Preparing guest disk...")
        self.report(f"Preparing an example guest disk for {arch} in {directory}")
        self.session.prepare(arch, directory)

    def use_local_image(self):
        dialog = LocalImageDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.image():
            return
        arch = normalize_arch(dialog.arch.currentText())
        directory = state_directory() / "guests"
        self.empty_status.setText("Preparing guest disk...")
        self.report(f"Preparing a {arch} guest disk from {dialog.image()}")
        self.session.prepare(arch, directory, local_image=dialog.image())

    def on_prepare_progress(self, percent, downloaded):
        self.empty_status.setText(f"Preparing guest disk - {percent}%")
        self.statusBar().showMessage(f"Downloading example image - {percent}% ({downloaded // 1024 // 1024} MiB)")

    def settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                config = dialog.config()
                save_config(config)
                self.session.config = config
                self.report("Settings saved")
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, APP_NAME, str(error))

    def start_vm(self):
        if not self.config.disk:
            path, _ = QFileDialog.getOpenFileName(self, "Select bootable Linux/Android guest disk",
                                                str(state_directory() / "guests"),
                                                "Guest disks (*.qcow2 *.raw *.img);;All files (*)")
            if not path:
                return
            try:
                config = replace(self.config, disk=path, disk_format=disk_format(path))
                save_config(config)
                self.session.config = config
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, APP_NAME, str(error))
                return
        self.empty_status.setText("Starting...")
        self.session.start()

    def stop_vm(self):
        if self.session.shutdown_requested:
            answer = QMessageBox.question(self, "Force stop", "Force stop the virtual machine? Unsaved guest data may be lost.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.session.stop(force=True)
        else:
            self.session.stop()

    def install_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, "Install APK", "", "Android packages (*.apk)")
        if not path:
            return
        adb = adb_executable()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB not found. Install Android SDK Platform Tools and add adb to PATH.")
            return
        self.session.install_apk(adb, path)

    def show_preview(self):
        """Open the in-client view of the guest camera bridge picture."""
        if not self.session.vm.running:
            QMessageBox.warning(self, APP_NAME, "Start the guest before previewing its camera.")
            return
        port = getattr(self.session.vm, "preview_port", None)
        if not port:
            QMessageBox.warning(self, APP_NAME, "This guest was started without a camera preview port.")
            return
        if self.preview is None:
            preview = CameraPreview(port, self)
            preview.finished.connect(lambda _result=0, preview=preview:
                                     self._preview_closed(preview))
            self.preview = preview
        self.preview.show()
        self.preview.raise_()
        self.preview.activateWindow()

    def _preview_closed(self, preview):
        # A preview that was already replaced by a newer one must not clear it.
        if self.preview is preview:
            self.preview = None

    def close_preview(self):
        if self.preview is not None:
            preview, self.preview = self.preview, None
            preview.close()

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
        self.session.poll()

    def on_started(self, accelerator):
        quality = display_quality_level(self.config.display_quality)
        self.view.setUrl(QUrl(
            f"{self.session.display_url()}#port={self.vm.websocket_port}"
            f"&password={self.vm.password}&quality={quality}"))
        shield_drag_and_drop(self.view)
        self.stack.setCurrentIndex(1)
        self.report(f"QEMU running | {self.config.arch} | {accelerator.upper()}")

    def on_stopped(self, code):
        self.close_display()
        self.empty_status.setText("Stopped" if code == 0 else f"QEMU exited ({code})")
        self.report(self.empty_status.text())

    def on_prepared(self, disk):
        self.empty_status.setText("Guest disk ready")

    def on_failed(self, summary, error, operation):
        self.report(str(error))
        if operation == "start":
            self.close_display()
            self.empty_status.setText("Start failed")
        elif operation == "prepare":
            self.empty_status.setText("Preparation failed")
        self.report_error(summary, error)

    def on_restarting(self, attempt, maximum):
        self.empty_status.setText("Recovering the guest...")

    def close_display(self):
        """Reset the embedded screen; session state and ports are already down."""
        self.view.setUrl(QUrl("about:blank"))
        self.stack.setCurrentIndex(0)
        self.close_preview()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def closeEvent(self, event):
        if self.session.busy:
            QMessageBox.information(self, APP_NAME, "Wait for the current operation to finish before closing.")
            event.ignore()
            return
        if self.session.vm.running:
            answer = QMessageBox.question(self, APP_NAME, "Force stop AndroidBox and close? Shut down first to preserve guest data.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.session.close()
        self.close_display()
        self.power.release()
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
