#!/usr/bin/env python3
"""Exercise the real Qt -> QEMU -> authenticated noVNC display, without an OS disk."""

import argparse
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from androidbox.desktop import MainWindow
from androidbox.runtime import VMConfig, qmp_execute


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", default="")
    parser.add_argument("--arch", choices=["x86_64", "aarch64"], default="x86_64")
    parser.add_argument("--firmware", default="")
    parser.add_argument("--accel", default="tcg")
    parser.add_argument("--screenshot", default=str(Path(tempfile.gettempdir()) / "androidbox-qemu.png"))
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        disk = root / "blank disk.raw"
        with disk.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024)
        config = VMConfig(disk=str(disk), disk_format="raw", memory_mb=1024, cpus=1,
                          arch=args.arch, qemu=args.qemu, firmware=args.firmware, accelerator=args.accel)
        app = QApplication(sys.argv[:1])
        with patch("androidbox.desktop.state_directory", return_value=root), \
                patch("androidbox.desktop.load_config", return_value=config):
            window = MainWindow()
        window.show()
        finished = False
        passed = False
        started = time.monotonic()

        def finish(error=None):
            nonlocal finished, passed
            if finished:
                return
            finished = True
            passed = error is None
            timer.stop()
            if window.future:
                try:
                    window.future.result(timeout=150)
                except Exception as exception:
                    print(exception, file=sys.stderr)
                window.future = None
            window.vm.terminate()
            if error:
                print(error, file=sys.stderr)
                print(window.log.toPlainText(), file=sys.stderr)
                if window.log_path.exists():
                    print(window.log_path.read_text(errors="replace"), file=sys.stderr)
            window.close()
            app.quit()

        def inspect(result):
            if finished or not result:
                return
            try:
                status = qmp_execute(window.vm.qmp_port, "query-status")
                if not status.get("running"):
                    raise RuntimeError(f"Unexpected QEMU state: {status}")
                qmp_execute(window.vm.qmp_port, "send-key", {"keys": [{"type": "qcode", "data": "esc"}]})
                if not window.grab().save(args.screenshot):
                    raise RuntimeError("Could not save screenshot")
                qmp_execute(window.vm.qmp_port, "quit")
                window.vm.process.wait(timeout=10)
                print(f"Real QEMU/noVNC display passed ({args.arch}/{args.accel}); screenshot: {args.screenshot}")
                finish()
            except Exception as error:
                finish(str(error))

        def poll():
            if finished:
                return
            if time.monotonic() - started > 60:
                finish("Timed out waiting for a nonblank authenticated QEMU framebuffer")
                return
            if window.was_running:
                window.view.page().runJavaScript("""(() => {
                    if (document.title !== 'AndroidBox - Connected') return false;
                    const canvas = document.querySelector('canvas');
                    if (!canvas || !canvas.width || !canvas.height) return false;
                    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
                    for (let i = 4; i < pixels.length; i += 4) {
                        if (pixels[i] !== pixels[0] || pixels[i+1] !== pixels[1] || pixels[i+2] !== pixels[2]) return true;
                    }
                    return false;
                })()""", inspect)

        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(500)
        # Convert modal errors to test failures so a CI run cannot wait for user input.
        with patch("androidbox.desktop.QMessageBox.warning", side_effect=lambda parent, title, message: finish(message)):
            QTimer.singleShot(0, window.start_vm)
            app.exec()
        return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
