"""Serve only bundled display assets on a random, local-only capability URL."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
from socketserver import TCPServer
import threading
from urllib.parse import urlsplit


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves an unused hostname here and can block the Qt thread.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class DisplayServer:
    def __init__(self):
        root = Path(__file__).parent / "web"
        if not (root / "novnc/core/rfb.js").is_file():
            raise ValueError("noVNC assets are missing. Run: python scripts/fetch_novnc.py")
        self.token = secrets.token_urlsafe(24)
        prefix = "/" + self.token + "/"

        class Handler(SimpleHTTPRequestHandler):
            extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript"}

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root), **kwargs)

            def do_GET(self):
                if not urlsplit(self.path).path.startswith(prefix):
                    self.send_error(404)
                    return
                self.path = "/" + self.path[len(prefix):]
                super().do_GET()

            def do_HEAD(self):
                self.send_error(405)

            def list_directory(self, path):
                self.send_error(403)

            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                super().end_headers()

            def log_message(self, *args):
                pass

        self.server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}{prefix}display.html"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
