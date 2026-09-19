#!/usr/bin/env python3
"""Exercise the same desktop self-test used by frozen release builds."""

from androidbox.selftest import main


if __name__ == "__main__":
    raise SystemExit(main())
