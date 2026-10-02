import sys
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from androidbox.__main__ import main


class EntrypointTests(unittest.TestCase):
    def test_qemu_test_dispatch_does_not_start_user_session(self):
        desktop = Mock(return_value=0)
        diagnostic = Mock(return_value=4)
        with patch.dict(sys.modules, {"androidbox.desktop": SimpleNamespace(main=desktop),
                                      "androidbox.qemutest": SimpleNamespace(main=diagnostic)}), \
                patch.object(sys, "argv", ["AndroidBox", "--qemu-test", "--arch", "aarch64"]):
            self.assertEqual(main(), 4)
        desktop.assert_not_called()
        diagnostic.assert_called_once_with(["--arch", "aarch64"])

    def test_self_test_dispatch_does_not_start_user_session(self):
        desktop = Mock(return_value=0)
        diagnostic = Mock(return_value=3)
        with patch.dict(sys.modules, {"androidbox.desktop": SimpleNamespace(main=desktop),
                                      "androidbox.selftest": SimpleNamespace(main=diagnostic)}), \
                patch.object(sys, "argv", ["AndroidBox", "--self-test", "--report", "result.json"]):
            self.assertEqual(main(), 3)
        desktop.assert_not_called()
        diagnostic.assert_called_once_with(["--report", "result.json"])

    def test_normal_launch_starts_desktop(self):
        desktop = Mock(return_value=0)
        with patch.dict(sys.modules, {"androidbox.desktop": SimpleNamespace(main=desktop)}), \
                patch.object(sys, "argv", ["AndroidBox"]):
            self.assertEqual(main(), 0)
        desktop.assert_called_once_with()

    def test_missing_dependency_writes_a_self_test_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "nested" / "result.json"
            with patch.dict(sys.modules, {"androidbox.selftest": None, "androidbox.desktop": None}), \
                    patch.object(sys, "argv", ["AndroidBox", "--self-test", "--report", str(report)]):
                self.assertEqual(main(), 1)
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(result["passed"])
            self.assertEqual(result["stage"], "dependency")
            self.assertIn("dependency unavailable", result["errors"][0])
