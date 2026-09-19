from pathlib import Path
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from androidbox.display import DisplayServer


@unittest.skipUnless((Path(__file__).resolve().parents[1] / "androidbox/web/novnc/core/rfb.js").exists(),
                     "Fetch noVNC assets to test the display server")
class DisplayTests(unittest.TestCase):
    def test_loopback_server_never_uses_reverse_dns(self):
        with patch("socket.getfqdn", side_effect=AssertionError("Unexpected reverse DNS")):
            server = DisplayServer()
            try:
                self.assertEqual(server.server.server_name, "127.0.0.1")
            finally:
                server.close()

    def test_scoped_local_assets_and_cleanup(self):
        server = DisplayServer()
        try:
            self.assertEqual(server.server.server_address[0], "127.0.0.1")
            with urllib.request.urlopen(server.url, timeout=3) as response:
                self.assertIn(b"new RFB", response.read())
            module = server.url.replace("display.html", "novnc/core/rfb.js")
            with urllib.request.urlopen(module, timeout=3) as response:
                self.assertIn("javascript", response.headers["Content-Type"])
                self.assertIn(b"class RFB", response.read())
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(server.url.replace(server.token, "invalid"), timeout=3)
            self.assertEqual(error.exception.code, 404)
        finally:
            server.close()
        self.assertFalse(server.thread.is_alive())
