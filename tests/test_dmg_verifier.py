from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_frozen


class DmgVerifierTests(unittest.TestCase):
    def test_verifies_mounted_application_and_detaches_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "AndroidBox.dmg"
            image.touch()

            def command(args, **kwargs):
                return subprocess.CompletedProcess(args, 0)

            with patch("scripts.verify_frozen.subprocess.run", side_effect=command) as run, \
                    patch.object(verify_frozen, "verify", side_effect=ValueError("test failure")) as verify, \
                    self.assertRaisesRegex(ValueError, "test failure"):
                verify_frozen.verify_dmg(image, require_runtime=True)
            verify.assert_called_once()
            self.assertTrue(verify.call_args.kwargs["require_runtime"])
            executable = verify.call_args.args[0]
            self.assertEqual(executable.parts[-4:], ("AndroidBox.app", "Contents", "MacOS", "AndroidBox"))
            self.assertEqual(run.call_args.args[0][:2], ["hdiutil", "detach"])
            self.assertEqual(run.call_args.args[0][2], str(executable.parents[3]))
