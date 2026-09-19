import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_frozen import verify


class FrozenVerifierTests(unittest.TestCase):
    def run_report(self, result, screenshot=True, require_runtime=False):
        def child(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 90)
            self.assertTrue(kwargs["check"])
            self.assertNotIn("PYTHONPATH", kwargs["env"])
            self.assertEqual("--require-runtime" in command, require_runtime)
            report = Path(command[command.index("--report") + 1])
            self.assertEqual(report.parent, kwargs["cwd"])
            report.write_text(json.dumps(result), encoding="utf-8")
            if screenshot:
                Path(command[command.index("--screenshot") + 1]).write_bytes(b"image")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "AndroidBox"
            executable.touch()
            with patch("scripts.verify_frozen.subprocess.run", side_effect=child):
                verify(executable, require_runtime=require_runtime)

    def test_required_runtime_must_be_reported(self):
        with self.assertRaisesRegex(ValueError, "runtime"):
            self.run_report({"passed": True, "frozen": True}, require_runtime=True)
        self.run_report({"passed": True, "frozen": True, "runtime": {
            "qemu": {"path": "/bundle/qemu", "version": "QEMU"},
            "adb": {"path": "/bundle/adb", "version": "ADB"},
        }}, require_runtime=True)

    def test_success_requires_frozen_result(self):
        self.run_report({"passed": True, "frozen": True})
        with self.assertRaisesRegex(ValueError, "self-test failed"):
            self.run_report({"passed": True, "frozen": False})

    def test_failed_self_test_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "self-test failed"):
            self.run_report({"passed": False, "frozen": True})

    def test_missing_screenshot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "did not render"):
            self.run_report({"passed": True, "frozen": True}, screenshot=False)

    def test_child_timeout_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "AndroidBox"
            executable.touch()
            with patch("scripts.verify_frozen.subprocess.run", side_effect=subprocess.TimeoutExpired("AndroidBox", 90)), \
                    self.assertRaises(subprocess.TimeoutExpired):
                verify(executable)
