#!/usr/bin/env python3
"""Open, resize, inspect and close the real Qt window without launching a guest."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication

from androidbox.desktop import MainWindow, SettingsDialog
from androidbox.bundled import verify_runtime
from androidbox.display import DisplayServer
from androidbox.runtime import VMConfig, load_config, reserve_ports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", default=str(Path(tempfile.gettempdir()) / "androidbox-desktop.png"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args(argv)
    if args.report:
        args.report.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as directory, \
            patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
            patch("androidbox.runtime.state_directory", return_value=Path(directory)):
        app = QApplication(sys.argv[:1])
        window = MainWindow()
        window.show()
        failures = []
        finished = False
        diagnostics = {"loads": [], "status": None}
        runtime = {}
        started = time.monotonic()
        window.view.loadFinished.connect(lambda success: diagnostics["loads"].append(success))

        def finish(error=None):
            nonlocal finished
            if finished:
                return
            finished = True
            if error:
                failures.append(str(error))
            window.close()
            app.quit()

        def check_display():
            if finished:
                return

            def inspect(status):
                diagnostics["status"] = status
                # A refused connection still requires successful ES-module/RFB initialization.
                if status == "Display disconnected":
                    finish()
                elif not finished:
                    QTimer.singleShot(200, check_display)

            window.view.page().runJavaScript("document.querySelector('#status')?.textContent", inspect)

        def verify():
            try:
                if args.require_runtime:
                    runtime.update(verify_runtime())
                assert window.windowTitle() == "AndroidBox"
                assert window.start_action.isEnabled()
                assert not window.stop_action.isEnabled()
                assert not window.install_action.isEnabled()
                assert not window.windowIcon().isNull()
                assert not window.log.isVisible()
                assert not window.logs_action.isChecked()
                window.logs_action.trigger()
                assert window.log.isVisible()
                assert window.logs_action.isChecked()
                window.logs_action.trigger()
                assert not window.log.isVisible()
                dialog = SettingsDialog(VMConfig(), window)
                assert dialog.config() == VMConfig()
                dialog.close()
                disk = Path(directory) / "guest.raw"
                disk.write_bytes(b"\x00" * 512)
                with patch("androidbox.desktop.QFileDialog.getOpenFileName", return_value=(str(disk), "")), \
                        patch.object(window.pool, "submit") as submit:
                    window.config = VMConfig()
                    window.start_vm()
                    assert window.config.disk == str(disk)
                    assert window.config.disk_format == "raw"
                    assert load_config().disk == str(disk)
                    submit.assert_called_once()
                    window.future = None
                    window.close_display()
                    window.update_actions()
                assert window.grab().save(args.screenshot)
                window.resize(640, 480)
                app.processEvents()
                assert window.stack.width() > 300
                window.server = DisplayServer()
                port = reserve_ports(1)[0]
                window.view.setUrl(QUrl(f"{window.server.url}#port={port}&password=smoketest"))
                window.stack.setCurrentIndex(1)
                QTimer.singleShot(200, check_display)
            except Exception as error:
                finish(error)

        QTimer.singleShot(1000, verify)
        QTimer.singleShot(args.timeout * 1000, lambda: finish("Timed out loading the embedded noVNC display"))
        app.exec()
        if not finished:
            failures.append("Application exited before completing self-test")
        result = {"passed": not failures, "errors": failures, "frozen": bool(getattr(sys, "frozen", False)),
                  "diagnostics": diagnostics, "runtime": runtime,
                  "elapsed_seconds": round(time.monotonic() - started, 2)}
        if args.report:
            args.report.write_text(json.dumps(result) + "\n", encoding="utf-8")
        if sys.stdout is not None:
            print(json.dumps(result))
        return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
