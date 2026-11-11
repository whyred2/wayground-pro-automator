"""Backward-compatible entry point for the native Windows build."""

import sys

from build_desktop import main


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows. Use scripts/build_desktop.py on Linux or macOS.")
    main()
