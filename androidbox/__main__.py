# AndroidBox — 由异猫工作群（mutantcat.org）发行
# GitHub: https://github.com/Mutantcat-Working-Group
import json
from pathlib import Path
import sys


def _self_test_report(arguments):
    """Return the --report path a self-test invocation asked for, if any."""
    if "--report" not in arguments:
        return None
    index = arguments.index("--report") + 1
    return Path(arguments[index]) if index < len(arguments) else None


def _report_dependency_failure(arguments, message):
    """Leave a self-test report behind even when a console never appears.

    A windowed frozen executable has no console, so a printed message would
    vanish; the CI verifier reads this report instead of the output stream.
    """
    report = _self_test_report(arguments)
    if report is None:
        return
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            "passed": False,
            "frozen": bool(getattr(sys, "frozen", False)),
            "stage": "dependency",
            "errors": [message],
        }) + "\n", encoding="utf-8")
    except OSError:
        pass


def main():
    try:
        if sys.argv[1:2] == ["--qemu-test"]:
            from .qemutest import main as qemutest_main
            return qemutest_main(sys.argv[2:])
        if sys.argv[1:2] == ["--self-test"]:
            from .selftest import main as selftest_main
            return selftest_main(sys.argv[2:])
        from .desktop import main as desktop_main
    except ImportError as error:
        message = (f"AndroidBox desktop dependency unavailable: {error}\n"
                   "Install the desktop client with: python -m pip install '.[desktop]'")
        _report_dependency_failure(sys.argv[2:], message)
        stream = sys.stderr or sys.stdout
        if stream is not None:
            print(message, file=stream)
        return 1
    return desktop_main()


if __name__ == "__main__":
    sys.exit(main())
