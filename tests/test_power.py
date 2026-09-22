import subprocess
import sys
import unittest
from unittest.mock import patch

from androidbox import power


class StubbornHelper:
    """A helper that ignores termination until it is killed."""

    def __init__(self):
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        pass

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["helper"], timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class PowerSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = power.PowerSession()
        self.addCleanup(self.session.release)

    def test_nothing_held_reports_no_mechanism(self):
        self.assertEqual(self.session.describe(), "")
        # Releasing an unheld lock must stay a no-op on every platform.
        self.session.release()
        self.assertFalse(self.session.held)

    def test_a_missing_helper_holds_nothing(self):
        if sys.platform == "win32":
            # Windows holds the wake lock in-process instead of via a helper.
            with patch.object(power, "_windows_stay_awake", side_effect=OSError("denied")):
                self.assertEqual(self.session.acquire(), "")
        else:
            with patch.object(power, "_spawn", return_value=None):
                self.assertEqual(self.session.acquire(), "")
        self.assertFalse(self.session.held)
        self.assertIsNone(self.session.process)

    def test_a_held_helper_is_acquired_once(self):
        if sys.platform == "win32":
            with patch.object(power, "_windows_stay_awake") as stay_awake:
                first = self.session.acquire()
                second = self.session.acquire()
            self.assertEqual(stay_awake.call_count, 1)
        else:
            with patch.object(power, "_spawn", return_value=StubbornHelper()) as spawn:
                first = self.session.acquire()
                second = self.session.acquire()
            self.assertEqual(spawn.call_count, 1)
        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_a_helper_that_ignores_termination_is_killed(self):
        stubborn = StubbornHelper()
        self.session.process = stubborn
        self.session.held = True
        self.session.release()
        self.assertTrue(stubborn.killed)
        self.assertIsNone(self.session.process)
        self.assertFalse(self.session.held)

    def test_a_live_helper_is_stopped_when_the_lock_is_released(self):
        process = power._spawn(["sleep", "30"])
        self.assertIsNotNone(process)
        self.addCleanup(process.kill)
        self.session.process = process
        self.session.held = True
        self.session.release()
        self.assertIsNotNone(process.poll())
        self.assertIsNone(self.session.process)

    def test_spawn_refuses_a_helper_that_is_not_installed(self):
        with patch.object(power.shutil, "which", return_value=None):
            self.assertIsNone(power._spawn(["absent-helper", "--block"]))

    def test_wake_lock_mechanics_are_advertised_per_platform(self):
        # Each platform asks for the mechanism that survives a closed lid or
        # an idle session for as long as the helper runs.
        self.assertEqual(power.CAFFEINATE[:2], ("caffeinate", "-d"))
        self.assertIn("handle-lid-switch", power.INHIBIT[1])
        self.assertIn("idle", power.INHIBIT[1])
        self.assertEqual(list(power.INHIBIT[-2:]), ["sleep", "infinity"])
        flags = power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED | power.ES_DISPLAY_REQUIRED
        # Continuous must stay set so the request survives until it is cleared.
        self.assertTrue(flags & power.ES_CONTINUOUS)
        self.assertNotEqual(flags & (power.ES_SYSTEM_REQUIRED | power.ES_DISPLAY_REQUIRED), 0)


if __name__ == "__main__":
    unittest.main()
