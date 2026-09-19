import sys


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
        print(f"AndroidBox desktop dependency unavailable: {error}\n"
              "Install the desktop client with: python -m pip install '.[desktop]'", file=sys.stderr)
        return 1
    return desktop_main()


if __name__ == "__main__":
    sys.exit(main())
