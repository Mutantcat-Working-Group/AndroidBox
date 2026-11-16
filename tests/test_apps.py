"""Exercise the app launcher against recorded ADB output.

Every decision these helpers make is a pure function of what `adb shell`
printed, so the tests feed it what a real guest prints and assert on the
result. `run` is the only thing that leaves the module, and it is stubbed.
"""

import unittest
from unittest.mock import patch

from androidbox import apps


class RecordingRun:
    """Stand in for process.run, answering per command and recording calls."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, argv, timeout=None, **kwargs):
        command = argv[-1]
        self.calls.append(command)
        for needle, response in self.answers.items():
            if needle in command:
                if isinstance(response, list):
                    # The same command can answer differently on each call.
                    reply = response.pop(0) if len(response) > 1 else response[0]
                else:
                    reply = response
                return Result(reply)
        return Result("")


class Result:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class PackageNameTests(unittest.TestCase):
    def test_a_package_name_is_checked_before_it_reaches_a_shell(self):
        self.assertEqual(apps.checked_package("com.example.app"), "com.example.app")
        for invalid in ("", "com.example; rm -rf /", "-x", "com.exa mple", 123):
            with self.assertRaises(ValueError, msg=repr(invalid)):
                apps.checked_package(invalid)

    def test_system_packages_are_recognised(self):
        self.assertTrue(apps.is_system_package("com.android.settings"))
        self.assertTrue(apps.is_system_package("com.google.android.gms"))
        self.assertFalse(apps.is_system_package("com.example.app"))


class FreeformTests(unittest.TestCase):
    def test_freeform_is_enabled_by_setting_the_three_globals(self):
        recorder = RecordingRun({"settings get global enable_freeform_support": "1"})
        with patch.object(apps, "run", recorder):
            self.assertTrue(apps.enable_freeform("adb", "127.0.0.1:5555"))
        command = recorder.calls[-1]
        self.assertIn("enable_freeform_support 1", command)
        self.assertIn("force_resizable_activities 1", command)
        self.assertIn("development_settings_enabled 1", command)

    def test_freeform_reports_false_when_android_refuses(self):
        recorder = RecordingRun({"enable_freeform_support": "0"})
        with patch.object(apps, "run", recorder):
            self.assertFalse(apps.enable_freeform("adb", "t"))


class LauncherResolutionTests(unittest.TestCase):
    def test_the_resolved_launcher_is_taken_from_the_last_matching_line(self):
        output = ("priority=0\n"
                  "com.example.app/com.example.app.SplashActivity\n")
        with patch.object(apps, "run", RecordingRun({"resolve-activity": output})):
            self.assertEqual(apps.resolve_launcher("adb", "t", "com.example.app"),
                             "com.example.app/com.example.app.SplashActivity")

    def test_an_unresolvable_launcher_returns_empty(self):
        with patch.object(apps, "run", RecordingRun({"resolve-activity": "No activity found"})):
            self.assertEqual(apps.resolve_launcher("adb", "t", "com.example.app"), "")


class LivenessTests(unittest.TestCase):
    def test_a_running_process_counts_as_alive(self):
        with patch.object(apps, "run", RecordingRun({"pidof": "1234 5678"})):
            alive, crash, uncertain = apps.wait_alive("adb", "t", "com.example.app")
        self.assertTrue(alive)
        self.assertFalse(uncertain)

    def test_an_arm_translation_crash_marks_the_launch_permanent(self):
        crash = "FATAL EXCEPTION: UnsatisfiedLinkError: dlopen failed: libndk_translation.so"
        with patch.object(apps, "run", RecordingRun({"pidof": "", "logcat": crash})):
            with patch.object(apps.time, "sleep"):
                alive, detail, uncertain = apps.wait_alive("adb", "t", "com.example.app", timeout=0)
        self.assertFalse(alive)
        self.assertFalse(uncertain)
        self.assertIn("UnsatisfiedLinkError", detail)

    def test_no_process_and_no_crash_is_reported_as_uncertain(self):
        # A large app under a slow image can still be starting; calling that a
        # failure would make the client retry a launch that is merely slow.
        with patch.object(apps, "run", RecordingRun({"pidof": "", "logcat": ""})), \
                patch.object(apps, "LIVENESS_UNCERTAIN_SECONDS", 0):
            alive, crash, uncertain = apps.wait_alive("adb", "t", "com.example.app", timeout=0)
        self.assertFalse(alive)
        self.assertTrue(uncertain)


class LaunchTests(unittest.TestCase):
    def test_a_freeform_launch_is_tried_first_and_succeeds(self):
        answers = {
            "resolve-activity": "com.example.app/com.example.app.Main\n",
            "--windowingMode 5": "Starting: Intent",
            "pidof": "4242",
        }
        recorder = RecordingRun(answers)
        with patch.object(apps, "run", recorder), patch.object(apps, "wait_alive",
                                                               return_value=(True, "", False)):
            summary = apps.launch("adb", "t", "com.example.app")
        self.assertIn("Started", summary)
        self.assertIn("--windowingMode 5", recorder.calls[1])

    def test_a_refused_windowing_mode_falls_back_to_fullscreen(self):
        answers = {
            "resolve-activity": "com.example.app/com.example.app.Main",
            "--windowingMode 5": "Error: Activity not started",
            "am start --activity-clear-top": "Starting: Intent",
        }
        recorder = RecordingRun(answers)
        with patch.object(apps, "run", recorder), patch.object(apps, "wait_alive",
                                                               return_value=(True, "", False)):
            summary = apps.launch("adb", "t", "com.example.app")
        self.assertIn("Started", summary)
        starts = [call for call in recorder.calls if call.startswith("am start")]
        self.assertEqual(len(starts), 2)
        self.assertNotIn("--windowingMode", starts[1])

    def test_monkey_is_the_last_resort(self):
        answers = {
            "resolve-activity": "",
            "am start": "Error type 3",
            "monkey": "Events injected: 1",
        }
        recorder = RecordingRun(answers)
        with patch.object(apps, "run", recorder), patch.object(apps, "wait_alive",
                                                               return_value=(True, "", False)):
            summary = apps.launch("adb", "t", "com.example.app")
        self.assertIn("Started", summary)
        self.assertTrue(any(call.startswith("monkey") for call in recorder.calls))

    def test_a_permanent_crash_is_raised_instead_of_retried(self):
        crash = "java.lang.UnsatisfiedLinkError: dlopen failed: libndk_translation.so"
        answers = {"resolve-activity": "", "am start": "Starting: Intent"}
        with patch.object(apps, "run", RecordingRun(answers)), \
                patch.object(apps, "wait_alive", return_value=(False, crash, False)):
            with self.assertRaises(apps.AppLaunchError) as caught:
                apps.launch("adb", "t", "com.example.app")
        self.assertTrue(caught.exception.permanent)
        self.assertIn("translation layer", str(caught.exception))

    def test_every_route_failing_raises(self):
        answers = {"resolve-activity": "", "am start": "Error", "monkey": "No activities found"}
        with patch.object(apps, "run", RecordingRun(answers)), \
                patch.object(apps, "wait_alive", return_value=(False, "", False)):
            with self.assertRaises(apps.AppLaunchError):
                apps.launch("adb", "t", "com.example.app")


class TrimTests(unittest.TestCase):
    def test_background_apps_are_stopped_but_the_foreground_one_is_kept(self):
        resumed = ("mResumedActivity: ActivityRecord{1 u0 com.example.keep/.Main t5}\n"
                   "mResumedActivity: ActivityRecord{2 u0 com.example.stale/.Main t6}\n")
        answers = {"dumpsys activity activities": resumed, "am force-stop": ""}
        recorder = RecordingRun(answers)
        with patch.object(apps, "run", recorder):
            stopped = apps.trim_background("adb", "t", keep={"com.example.keep"})
        self.assertEqual(stopped, ["com.example.stale"])
        self.assertFalse(any("com.example.keep" in call for call in recorder.calls))

    def test_system_packages_are_never_trimmed(self):
        resumed = "mResumedActivity: ActivityRecord{1 u0 com.android.settings/.Home t1}\n"
        recorder = RecordingRun({"dumpsys activity activities": resumed})
        with patch.object(apps, "run", recorder):
            self.assertEqual(apps.trim_background("adb", "t"), [])
        self.assertEqual(len(recorder.calls), 1)
        self.assertIn("dumpsys activity activities", recorder.calls[0])

    def test_optional_packages_are_only_trimmed_when_deep(self):
        resumed = "mResumedActivity: ActivityRecord{1 u0 com.android.vending/.Main t1}\n"
        with patch.object(apps, "run", RecordingRun({"dumpsys activity activities": resumed})):
            self.assertEqual(apps.trim_background("adb", "t"), [])
        with patch.object(apps, "run", RecordingRun({"dumpsys activity activities": resumed})):
            self.assertEqual(apps.trim_background("adb", "t", deep=True), ["com.android.vending"])


if __name__ == "__main__":
    unittest.main()
