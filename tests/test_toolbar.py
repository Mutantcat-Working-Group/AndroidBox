import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QToolBar

    from androidbox.desktop import TOOLBAR_ICON_SIZE, MainWindow, build_toolbar


LEFT_BUTTONS = [
    ("start", "play", "Start", False),
    ("stop", "stop", "Shut down", False),
    ("install", "install", "Install APK", False),
]
RIGHT_BUTTONS = [
    ("settings", "gear", "Settings", False),
    ("logs", "exclamation", "Logs", True),
    ("fullscreen", "fullscreen", "Full screen", False),
]


def button_actions(toolbar):
    """Return the toolbar's real button actions, skipping widget placeholders."""
    return [action for action in toolbar.actions() if action.text()]


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the desktop toolbar")
class ToolbarTests(unittest.TestCase):
    def setUp(self):
        self.application = QApplication.instance() or QApplication([])

    def toolbar(self):
        window = QMainWindow()
        toolbar = QToolBar("Runtime")
        toolbar.setMovable(False)
        window.addToolBar(toolbar)
        brand = QLabel("  AndroidBox  ")
        ink = toolbar.palette().color(QPalette.ColorRole.WindowText).name()
        actions = build_toolbar(window, toolbar, ink, brand, LEFT_BUTTONS, RIGHT_BUTTONS)
        window.show()
        # Keep the window alive: a collected QMainWindow deletes its children.
        self.window = window
        return window, toolbar, actions

    def test_groups_are_keyed_by_name_and_nothing_separates_them(self):
        _, toolbar, actions = self.toolbar()
        self.assertEqual(set(actions), {button[0] for button in LEFT_BUTTONS + RIGHT_BUTTONS})
        # A separator would add a seventh action, so the row is exactly the six buttons.
        self.assertEqual(len(button_actions(toolbar)), 6)
        for action in toolbar.actions():
            self.assertFalse(action.isSeparator())

    def test_buttons_are_icon_only_with_one_shared_size(self):
        _, toolbar, _ = self.toolbar()
        self.assertEqual(toolbar.toolButtonStyle(), Qt.ToolButtonIconOnly)
        self.assertEqual(toolbar.iconSize(), QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
        for action in button_actions(toolbar):
            self.assertFalse(action.icon().isNull())

    def test_only_the_logs_button_toggles(self):
        _, _, actions = self.toolbar()
        checkable = {name for name, action in actions.items() if action.isCheckable()}
        self.assertEqual(checkable, {"logs"})
        self.assertFalse(actions["logs"].isChecked())

    def test_right_group_sits_right_of_the_left_group(self):
        _, toolbar, actions = self.toolbar()
        left = toolbar.widgetForAction(actions["start"])
        right = toolbar.widgetForAction(actions["settings"])
        self.assertLess(left.x(), right.x())
        self.assertLess(left.x() + left.width(), right.x() + right.width())

    def test_left_group_sits_left_of_the_stretch_and_brand(self):
        _, toolbar, actions = self.toolbar()
        start = toolbar.widgetForAction(actions["start"])
        stop = toolbar.widgetForAction(actions["stop"])
        install = toolbar.widgetForAction(actions["install"])
        self.assertLess(start.x(), stop.x())
        self.assertLess(stop.x(), install.x())

    def test_every_button_carries_a_tooltip(self):
        _, _, actions = self.toolbar()
        for button in LEFT_BUTTONS + RIGHT_BUTTONS:
            self.assertEqual(actions[button[0]].toolTip(), button[2])


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the desktop toolbar")
class MainWindowToolbarTests(unittest.TestCase):
    def window(self):
        from androidbox.desktop import MainWindow

        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory, \
                patch("androidbox.desktop.state_directory", return_value=Path(directory)), \
                patch("androidbox.guestdisk.state_directory", return_value=Path(directory)), \
                patch("androidbox.runtime.state_directory", return_value=Path(directory)), \
                patch("androidbox.desktop.QMessageBox.warning"):
            window = MainWindow()
            window.show()
            return application, window

    def test_main_window_keeps_the_expected_action_names(self):
        _, window = self.window()
        for name in ("start_action", "stop_action", "install_action", "settings_action",
                     "logs_action", "fullscreen_action"):
            self.assertTrue(hasattr(window, name), name)
        toolbar = window.findChildren(QToolBar)[0]
        self.assertFalse(any(action.isSeparator() for action in toolbar.actions()))
        self.assertEqual(toolbar.iconSize(), QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
        # Icon-only buttons: three runtime controls, three window controls, and
        # the Linux native button on Linux alone.
        expected = 7 if sys.platform.startswith("linux") else 6
        self.assertEqual(len(button_actions(toolbar)), expected)
        self.assertEqual(toolbar.toolButtonStyle(), Qt.ToolButtonIconOnly)
        window.close()

    def test_logs_start_collapsed(self):
        _, window = self.window()
        self.assertFalse(window.logs_action.isChecked())
        self.assertFalse(window.log.isVisible())
        window.logs_action.trigger()
        self.assertTrue(window.logs_action.isChecked())
        self.assertTrue(window.log.isVisible())
        window.logs_action.trigger()
        self.assertFalse(window.log.isVisible())
        window.close()

    def test_settings_dialog_offers_the_display_quality_choice(self):
        _, window = self.window()
        from androidbox.desktop import SettingsDialog

        dialog = SettingsDialog(window.config)
        self.assertEqual(dialog.quality.currentText(), window.config.display_quality)
        dialog.quality.setCurrentText("responsive")
        self.assertEqual(dialog.config().display_quality, "responsive")
        window.close()
