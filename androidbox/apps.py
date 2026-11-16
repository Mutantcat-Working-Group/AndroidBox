"""Launch, stop and account for Android apps running inside the guest.

The guest normally shows one Android desktop inside a single noVNC view, which
means every app competes for the same screen and nothing that was opened
earlier is ever told to stop. ApkStart (MIT, github.com/RoutineMiku/apkstart)
solves both: it starts each app in a freeform window of its own and force-stops
the apps the user is no longer looking at. This module is the same behaviour
expressed against ADB, so the desktop client can drive it.

Launching is deliberately tolerant. `am start` can report success for an app
that dies a moment later, so every attempt is followed by a liveness check, and
a launch that fails with freeform is retried full-screen and then through
`monkey`. Only a crash that names the ARM translation layer is treated as
permanent, because no retry will fix a missing translator.

Everything here shells out through `process.run`, so it works the same on the
three host platforms and is testable without a guest by feeding it recorded
output.
"""

import re
import time

from .process import run

# adb shell verbs that take a package name; nothing else may reach them, so a
# package name read from a manifest cannot inject a second command.
SAFE_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")

# A freeform window only exists when Android was told to allow one. These are
# the three settings the emulator-based tools flip, and they need developer
# options enabled before `settings put` will accept them.
FREEFORM_SETTINGS = (
    ("enable_freeform_support", "1"),
    ("force_resizable_activities", "1"),
    ("development_settings_enabled", "1"),
)

# Packages that must never be trimmed: stopping any of them blanks the screen,
# kills the launcher, or breaks the apps that are still running.
NEVER_TRIM = frozenset({
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.android.inputmethod.latin",
    "com.google.android.inputmethod.latin",
    "com.android.webview",
    "com.google.android.webview",
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.android.providers.settings",
    "com.android.server.telecom",
})

# Only touched when the caller asks for deep trimming: background updaters,
# wallpapers and printers, none of which keep an app in front from working.
OPTIONAL_SYSTEM = frozenset({
    "com.android.vending",
    "com.google.android.setupwizard",
    "com.android.printspooler",
    "com.android.wallpapercropper",
    "com.android.dreams.basic",
    "com.android.providers.calendar",
    "com.android.providers.contacts",
    "com.android.managedprovisioning",
    "com.android.statementservice",
    "com.android.backupconfirm",
})

# Anything under these prefixes belongs to the system or a vendor HAL, so a
# per-session trim leaves it alone.
SYSTEM_PREFIXES = ("android", "com.android.", "com.google.android.",
                   "com.qualcomm.", "com.qti.", "vendor.", "com.mediatek.")

# A crash that names any of these cannot be retried away: the app needs a
# binary translator this image does not have.
UNRECOVERABLE = re.compile(
    r"DoBadTrampoline|libndk_translation|UnsatisfiedLinkError|dlopen failed",
    re.IGNORECASE,
)

# How long a launch may take to show a live process before it counts as failed.
LIVENESS_TIMEOUT_SECONDS = 6.0
LIVENESS_POLL_SECONDS = 0.4
# A large app can take tens of seconds to reach its process under a slow image;
# when no crash was logged, the launch is reported as still loading rather than
# failed.
LIVENESS_UNCERTAIN_SECONDS = 12.0


def _shell(adb, target, command, timeout=20):
    """Run one shell command in the guest and return its stdout."""
    result = run([adb, "-s", target, "shell", command], timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip() or f"adb shell failed: {command}")
    return result.stdout


def checked_package(package):
    """Return the package name, or raise if it could not be a package name."""
    if not isinstance(package, str) or not SAFE_PACKAGE.match(package):
        raise ValueError(f"Refusing to use an invalid package name: {package!r}")
    return package


def is_system_package(package):
    return package.startswith(SYSTEM_PREFIXES)


def enable_freeform(adb, target, timeout=12):
    """Ask Android to allow freeform windows; False when it will not."""
    command = "; ".join([f"settings put global {key} {value}" for key, value in FREEFORM_SETTINGS]
                        + ["settings get global enable_freeform_support"])
    try:
        output = _shell(adb, target, command, timeout=timeout)
    except (RuntimeError, OSError):
        return False
    return output.strip().splitlines()[-1].strip() == "1"


def resolve_launcher(adb, target, package):
    """Return the component Android itself resolves as the app's launcher.

    The activity inside the APK is not always the one a launcher starts: many
    Chinese apps do their real initialisation in a splash activity, and going
    straight to the main one leaves the app dead a second later.
    """
    package = checked_package(package)
    command = (f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {package}")
    try:
        lines = [line.strip() for line in _shell(adb, target, command).splitlines() if line.strip()]
    except (RuntimeError, OSError):
        return ""
    # The answer ends with "<pkg>/<class>"; the lines above it are headers.
    for line in reversed(lines):
        if line.startswith(f"{package}/"):
            return line
    return ""


def task_id(adb, target, package):
    """Return the recents task id of a package, or None."""
    package = checked_package(package)
    try:
        output = _shell(adb, target, "dumpsys activity recents")
    except (RuntimeError, OSError):
        return None
    for block in output.split("Recent #")[1:]:
        if package not in block:
            continue
        match = re.search(r"taskId=(\d+)", block)
        if match:
            return int(match.group(1))
    return None


def resize_task(adb, target, package, bounds):
    """Resize an app's task to (left, top, right, bottom); False when unknown."""
    identifier = task_id(adb, target, package)
    if identifier is None:
        return False
    left, top, right, bottom = bounds
    try:
        _shell(adb, target, f"am task resize {identifier} {left} {top} {right} {bottom}")
    except (RuntimeError, OSError):
        return False
    return True


def process_id(adb, target, package):
    """Return the first pid of a package, or "" when it is not running."""
    package = checked_package(package)
    try:
        output = _shell(adb, target, f"pidof {package}", timeout=8).strip()
    except (RuntimeError, OSError):
        return ""
    # A package compiled for 32 and 64 bits answers with two pids.
    return output.split()[0] if output else ""


def crash_log(adb, target, package, timeout=12):
    """Return the crash lines Android logged for a package, if any."""
    package = checked_package(package)
    command = ("logcat -d -t 250 -v brief AndroidRuntime:E DEBUG:E libc:E 2>/dev/null | "
               f"grep -i -E '{package}|FATAL|ndk_translation|SIGABRT|SIGSEGV|UnsatisfiedLink' | tail -n 30")
    try:
        return _shell(adb, target, command, timeout=timeout).strip()
    except (RuntimeError, OSError):
        return ""


def wait_alive(adb, target, package, timeout=LIVENESS_TIMEOUT_SECONDS):
    """Return (alive, crash, uncertain) for a launch that was just issued."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process_id(adb, target, package):
            return True, "", False
        time.sleep(LIVENESS_POLL_SECONDS)
    # No process yet. Only a logged crash says the app really failed; a large
    # app under a slow image can still be starting.
    crash = crash_log(adb, target, package)
    if UNRECOVERABLE.search(crash):
        return False, crash, False
    extra = max(0.0, LIVENESS_UNCERTAIN_SECONDS - timeout)
    deadline = time.monotonic() + extra
    while time.monotonic() < deadline:
        if process_id(adb, target, package):
            return True, "", False
        time.sleep(LIVENESS_POLL_SECONDS)
    crash = crash_log(adb, target, package) if not crash else crash
    return False, crash, not crash


def launch(adb, target, package, activity="", freeform=True, bounds=None):
    """Start an app, falling back until one of the routes works.

    Returns a spoken-for summary string. Raises when every route failed, with
    the crash log attached so the client can explain it.
    """
    package = checked_package(package)
    resolved = resolve_launcher(adb, target, package) or activity
    if resolved and "/" not in resolved:
        component = f"{package}/{resolved}"
    elif resolved:
        component = resolved
    else:
        component = ""
    intent = (["-n", component] if component
              else ["-a", "android.intent.action.MAIN",
                    "-c", "android.intent.category.LAUNCHER", "-p", package])
    # Freeform first, then a plain full-screen start: not every image honours
    # the windowing mode, and a refused windowing mode aborts the whole start.
    modes = ([["--windowingMode", "5"], []] if freeform else [[]])

    last_error = ""
    for mode in modes:
        parts = ["am", "start", *mode, "--activity-clear-top", *intent]
        try:
            output = _shell(adb, target, " ".join(parts))
        except (RuntimeError, OSError) as error:
            last_error = str(error)
            continue
        if re.search(r"Error|Exception", output):
            last_error = output.strip()
            continue
        if bounds:
            resize_task(adb, target, package, bounds)
        alive, crash, uncertain = wait_alive(adb, target, package)
        if alive:
            return f"Started {package}"
        if uncertain:
            return f"Started {package} (still loading)"
        last_error = crash or last_error
        if UNRECOVERABLE.search(crash):
            raise AppLaunchError(package, crash, permanent=True)

    # Last resort: some images cannot resolve a launcher by intent filter.
    try:
        output = _shell(adb, target, f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
        alive, crash, uncertain = wait_alive(adb, target, package, LIVENESS_UNCERTAIN_SECONDS)
        if alive or uncertain:
            return f"Started {package}"
        last_error = crash or last_error
    except (RuntimeError, OSError) as error:
        last_error = last_error or str(error)

    if not last_error:
        return f"Started {package}"
    raise AppLaunchError(package, last_error)


class AppLaunchError(RuntimeError):
    """A launch that no route could complete."""

    def __init__(self, package, detail, permanent=False):
        self.package = package
        self.detail = detail
        self.permanent = permanent
        reason = "needs an ARM translation layer this image does not provide" if permanent \
            else "could not be started"
        super().__init__(f"{package} {reason}: {detail}")


def force_stop(adb, target, package):
    package = checked_package(package)
    try:
        _shell(adb, target, f"am force-stop {package}")
    except (RuntimeError, OSError):
        return False
    return True


def running_packages(adb, target):
    """Return the packages Android currently has in front."""
    try:
        output = _shell(adb, target,
                        'dumpsys activity activities | grep -E "mResumedActivity|ResumedActivity"')
    except (RuntimeError, OSError):
        return []
    packages = []
    for match in re.finditer(r"([A-Za-z][\w.]*)/[.\w$]+", output):
        package = match.group(1)
        if package not in packages:
            packages.append(package)
    return packages


def trim_background(adb, target, keep=(), deep=False):
    """Stop every running app the user is no longer looking at.

    A guest with a few GB of RAM cannot keep every app it ever opened alive;
    leaving them running is what makes a browser launch push the container into
    memory pressure. System packages and anything in `keep` are left alone.
    """
    keep = {checked_package(package) for package in keep}
    stopped = []
    for package in running_packages(adb, target):
        if package in keep or package in NEVER_TRIM:
            continue
        # OPTIONAL_SYSTEM is checked before the system prefix: those packages
        # are com.android.* too, so the prefix test would hide them and deep
        # trimming could never stop anything.
        if package in OPTIONAL_SYSTEM and not deep:
            continue
        if package not in OPTIONAL_SYSTEM and is_system_package(package):
            continue
        if force_stop(adb, target, package):
            stopped.append(package)
    return stopped


def idle(adb, target):
    """Put Android into device-idle so its background work stops.

    Only meaningful once no app window is left; combined with a trimmed
    background it is what lets the guest give its memory back between uses.
    """
    for command in ("am kill-all", "dumpsys deviceidle force-idle"):
        try:
            _shell(adb, target, command)
        except (RuntimeError, OSError):
            pass
