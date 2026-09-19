import sys
from types import SimpleNamespace
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
