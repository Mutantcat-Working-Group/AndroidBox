#!/usr/bin/env python3
# Copyright 2021 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
# PYTHON_ARGCOMPLETE_OK
import os
import sys

if __name__ == "__main__":
    os.umask(0o0022)
    if sys.platform != "linux" or "--desktop" in sys.argv:
        from androidbox.__main__ import main
        if "--desktop" in sys.argv:
            sys.argv.remove("--desktop")
        sys.exit(main())
    else:
        import tools
        sys.exit(tools.main())
