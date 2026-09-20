"""Qt desktop shell for the QEMU display and the optional Linux-native backend."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import QLockFile, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QStackedWidget, QStyle, QToolBar, QVBoxLayout, QWidget,
)

from . import APP_ID, APP_NAME
from .adb import install_apk, executable as adb_executable
from .display import DisplayServer
from .process import external_environment
from .runtime import VMConfig, VirtualMachine, default_config, disk_format, executable, load_config, probe, save_config, state_directory


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
                        accelerator=self.accel.currentText(), disk_format=self.format.currentText())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setMinimumSize(640, 480)
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/AppIcon.png")))
        self.vm = VirtualMachine()
        self.server = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.operation = None
        self.was_running = False
        self.native_process = None
        self.log_offset = 0
        self.log_path = state_directory() / "qemu.log"
        self.shutdown_requested = False
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        try:
            self.config = load_config()
        except (ValueError, OSError) as error:
            self.config = default_config(discover_disk=False)
            self.log.appendPlainText(str(error))
        toolbar = QToolBar("Runtime")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        brand = QLabel("  AndroidBox  ")
        brand.setStyleSheet("font-size: 18px; font-weight: 600;")
        toolbar.addWidget(brand)
        self.start_action = self.action(toolbar, "Start", QStyle.SP_MediaPlay, self.start_vm)
        self.stop_action = self.action(toolbar, "Shut down", QStyle.SP_MediaStop, self.stop_vm)
        self.install_action = self.action(toolbar, "Install APK", QStyle.SP_FileIcon, self.install_apk)
        toolbar.addSeparator()
        self.settings_action = self.action(toolbar, "Settings", QStyle.SP_FileDialogDetailedView, self.settings)
        self.action(toolbar, "Full screen", QStyle.SP_TitleBarMaxButton, self.toggle_fullscreen)
        self.logs_action = self.action(toolbar, "Logs", QStyle.SP_FileDialogInfoView,
                                       lambda: self.log.setVisible(self.logs_action.isChecked()))
        self.logs_action.setCheckable(True)
        if sys.platform.startswith("linux"):
            self.native_action = self.action(toolbar, "Linux native", QStyle.SP_ComputerIcon, self.native)
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
        layout.addStretch()
        self.stack.addWidget(empty)
        self.view = QWebEngineView()
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.stack.addWidget(self.view)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.log)
        splitter.setSizes([600, 140])
        self.setCentralWidget(splitter)
        self.log.hide()
        self.statusBar().showMessage("Stopped")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        self.update_actions()

    def action(self, toolbar, label, icon, callback):
        action = QAction(self.style().standardIcon(icon), label, self)
        action.setToolTip(label)
        action.triggered.connect(callback)
        toolbar.addAction(action)
        return action

    def report(self, message):
        self.log.appendPlainText(message)
        self.statusBar().showMessage(message)

    def update_actions(self):
        busy = self.future is not None
        running = self.vm.running
        native_running = self.native_process is not None and self.native_process.poll() is None
        self.start_action.setEnabled(not busy and not running and not native_running)
        self.settings_action.setEnabled(not busy and not running)
        self.stop_action.setEnabled(not busy and running)
        self.install_action.setEnabled(not busy and running and not self.shutdown_requested)
        if hasattr(self, "native_action"):
            self.native_action.setEnabled(not busy and not running and not native_running)

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
                    self.view.setUrl(QUrl(f"{self.server.url}#port={self.vm.websocket_port}&password={self.vm.password}"))
                    self.stack.setCurrentIndex(1)
                    self.report(f"QEMU running | {self.config.arch} | {result.upper()}")
                elif operation == "stop":
                    self.report("Shutdown requested" if self.vm.running else "Stopped")
                else:
                    self.report(result or "Done")
            except Exception as error:
                self.report(str(error))
                if operation == "start":
                    self.empty_status.setText("Start failed")
                    self.close_display()
                QMessageBox.warning(self, APP_NAME, str(error))
        if self.was_running and not self.vm.running:
            self.was_running = False
            self.vm.close_log()
            code = self.vm.process.returncode
            self.close_display()
            self.empty_status.setText("Stopped" if code == 0 else f"QEMU exited ({code})")
            self.report(self.empty_status.text())
            self.stop_action.setToolTip("Shut down")
        self.update_actions()

    def close_display(self):
        self.view.setUrl(QUrl("about:blank"))
        self.stack.setCurrentIndex(0)
        if self.server:
            self.server.close()
            self.server = None

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
