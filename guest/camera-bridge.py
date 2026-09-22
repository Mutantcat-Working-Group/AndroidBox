"""Feed the guest loopback camera from the frames the host streams over TCP.

Runs inside the Ubuntu support layer only. One ffmpeg process turns MJPEG
frames into a V4L2 stream and writes them to the loopback camera device, while
this script decides what goes into that pipe: the frames the host sends over
port 7100 while a webcam is attached, or a still test pattern while it sends
nothing, so the Android camera app always has a picture to show. Only the guest
standard library is used, because the guest receives this file from the seed.
"""

from pathlib import Path
import socket
import subprocess
import sys
import time

CAMERA_PORT = 7100
# How long the guest waits for host frames before it puts the test pattern back
# on screen, and how often that pattern is refreshed while it keeps waiting.
IDLE_FALLBACK = 3.0
TEST_PATTERN_INTERVAL = 2.0
STILL_PATTERN = Path("/var/lib/androidbox/camera-pattern.jpg")


def capture_test_pattern():
    """Render one still frame for hosts without a webcam, once per boot."""
    if STILL_PATTERN.is_file():
        return
    STILL_PATTERN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=1",
                    "-frames:v", "1", str(STILL_PATTERN)], check=False)


def start_encoder(video):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "image2pipe", "-vcodec", "mjpeg", "-i", "pipe:0",
               "-vf", "format=yuv420p", "-f", "v4l2", video]
    return subprocess.Popen(command, stdin=subprocess.PIPE)


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"
    if not Path(video).exists():
        print(f"camera bridge: {video} is not available", file=sys.stderr)
        return 1
    capture_test_pattern()
    encoder = start_encoder(video)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("0.0.0.0", CAMERA_PORT))
        listener.listen(1)
    except OSError as error:
        print(f"camera bridge: cannot listen on {CAMERA_PORT}: {error}", file=sys.stderr)
        encoder.kill()
        return 1
    listener.settimeout(0.5)
    last_host_frame = 0.0
    last_pattern = 0.0
    try:
        while True:
            if encoder.poll() is not None:
                print("camera bridge: the frame encoder stopped", file=sys.stderr)
                return 1
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                pass
            else:
                with connection:
                    connection.settimeout(IDLE_FALLBACK)
                    while True:
                        try:
                            payload = connection.recv(262144)
                        except socket.timeout:
                            break
                        if not payload:
                            break
                        try:
                            encoder.stdin.write(payload)
                            encoder.stdin.flush()
                        except (BrokenPipeError, ValueError, OSError):
                            print("camera bridge: the frame encoder went away",
                                  file=sys.stderr)
                            return 1
                        last_host_frame = time.monotonic()
            if time.monotonic() - last_host_frame > IDLE_FALLBACK:
                now = time.monotonic()
                if now - last_pattern >= TEST_PATTERN_INTERVAL:
                    last_pattern = now
                    try:
                        encoder.stdin.write(STILL_PATTERN.read_bytes())
                        encoder.stdin.flush()
                    except (OSError, ValueError):
                        print("camera bridge: the frame encoder went away", file=sys.stderr)
                        return 1
    finally:
        listener.close()
        if encoder.poll() is None:
            encoder.kill()
            try:
                encoder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


if __name__ == "__main__":
    sys.exit(main())
