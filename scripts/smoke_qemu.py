#!/usr/bin/env python3
"""Run the Qt/QEMU integration check from a source checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from androidbox.qemutest import main


if __name__ == "__main__":
    sys.exit(main())
