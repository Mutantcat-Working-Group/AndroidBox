#!/usr/bin/env python3
"""Keep Android's captive-portal probe pointed at a local 204 endpoint.

The guest network works, but Android marks the Ethernet link as only partially
connected when its default validation endpoints (Google connectivity checks)
are unreachable from the user's network.  That makes apps report "no internet"
even though DNS and traffic are fine.  This helper serves a tiny 204 response
on the AndroidBox bridge and rewrites Android's captive-portal settings to use
it, then revalidates once so the link comes up as fully connected.
"""

import http.server
import logging
import shutil
import subprocess
import sys
import threading
import time


LXC_PATH = "/var/lib/androidbox/lxc"
CONTAINER = "androidbox"
SETTINGS_PORT_80 = {
    "captive_portal_http_url": "http://192.168.240.1/generate_204",
    "captive_portal_https_url": "http://192.168.240.1/generate_204",
    "captive_portal_use_https": "0",
    "captive_portal_mode": "1",
    "captive_portal_detection_enabled": "1",
}
CHECK_INTERVAL_SECONDS = 10
REVALIDATE_WAIT_SECONDS = 35


class _NoContent(http.server.BaseHTTPRequestHandler):
    """Answer every captive-portal probe with an HTTP 204."""

    def _send_204(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = _send_204
    do_HEAD = _send_204
    do_POST = _send_204

    def log_message(self, format, *args):
        return


def _run(args, timeout=15, env=None):
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _lxc(args, timeout=15):
    env = {
        "PATH": "/system/bin:/system/xbin:/usr/sbin:/usr/bin:/sbin:/bin",
        "ANDROID_ROOT": "/system",
        "ANDROID_DATA": "/data",
    }
    return _run(
        ["lxc-attach", "-P", LXC_PATH, "-n", CONTAINER, "--"] + args,
        timeout,
        env=env,
    )


def _container_pid():
    result = _run(["lxc-info", "-P", LXC_PATH, "-n", CONTAINER, "-pH"], timeout=10)
    return result.stdout.strip() if result.returncode == 0 else ""


def _container_running():
    result = _run(["lxc-info", "-P", LXC_PATH, "-n", CONTAINER, "-sH"], timeout=10)
    return result.stdout.strip() == "RUNNING"


def _serve_204():
    for port in (80, 8080):
        try:
            server = http.server.ThreadingHTTPServer(("0.0.0.0", port), _NoContent)
        except OSError:
            logging.warning("could not bind port %s for the 204 helper", port)
            continue
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return port
    raise RuntimeError("no free port for the local 204 helper")


def _settings(port):
    settings = dict(SETTINGS_PORT_80)
    if port != 80:
        base = f"http://192.168.240.1:{port}/generate_204"
        settings["captive_portal_http_url"] = base
        settings["captive_portal_https_url"] = base
    return settings


def _apply_settings(port):
    changed = False
    for key, expected in _settings(port).items():
        result = _lxc(["/system/bin/settings", "get", "global", key])
        if result.returncode != 0 or result.stdout.strip() != expected:
            result = _lxc(["/system/bin/settings", "put", "global", key, expected])
            if result.returncode == 0:
                changed = True
            else:
                logging.warning(
                    "could not set Android setting %s: %s",
                    key,
                    result.stderr.strip(),
                )
    return changed


def _toggle_ethernet():
    pid = _container_pid()
    if not pid:
        logging.warning("could not find the Android container PID to revalidate")
        return False
    for action in ("down", "up"):
        result = _run(["nsenter", "-t", pid, "-n", "ip", "link", "set", "eth0", action])
        if result.returncode != 0:
            logging.warning("could not bring Android eth0 %s: %s", action, result.stderr.strip())
            return False
        time.sleep(1)
    return True


def _validated():
    result = _lxc(["/system/bin/dumpsys", "connectivity"], timeout=20)
    if result.returncode != 0:
        return False
    return any(
        "Ethernet CONNECTED" in line and "VALIDATED" in line
        for line in result.stdout.splitlines()
    )


def main():
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if shutil.which("lxc-info") is None or shutil.which("lxc-attach") is None:
        raise RuntimeError("lxc tools are not installed in the AndroidBox guest")
    port = _serve_204()
    logging.info("local 204 helper listening on port %s", port)

    revalidated = False
    while True:
        try:
            if not _container_running():
                revalidated = False
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue
            changed = _apply_settings(port)
            if not revalidated:
                if changed:
                    logging.info("Android captive-portal settings updated")
                if not _validated():
                    logging.info("revalidating Android network once")
                    _toggle_ethernet()
                    deadline = time.monotonic() + REVALIDATE_WAIT_SECONDS
                    while time.monotonic() < deadline:
                        if _validated():
                            logging.info("Android network fully validated")
                            break
                        time.sleep(2)
                revalidated = True
        except Exception as exc:  # keep the helper alive through transient LXC errors
            logging.warning("network helper cycle failed: %s", exc)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
