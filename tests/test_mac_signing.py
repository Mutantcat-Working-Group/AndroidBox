from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sign_macos import sign_app


class MacSigningTests(unittest.TestCase):
    def test_qemu_gets_hypervisor_entitlement_before_bundle_seal(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "AndroidBox.app"
            qemu = app / "Contents/Frameworks/runtime/bin/qemu-system-aarch64"
            qemu.parent.mkdir(parents=True)
            qemu.touch()
            with patch("scripts.sign_macos.subprocess.run") as run:
                sign_app(app)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn("--entitlements", commands[0])
            self.assertEqual(commands[0][-1], str(qemu))
            self.assertEqual(commands[1], ["codesign", "--force", "--sign", "-", str(app)])
            self.assertIn("--verify", commands[2])
            self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))
