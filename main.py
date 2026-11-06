"""
Entry point for OpenChromLab — Chromatography Data System.
Educational & University Research Edition.

Run with:
    py main.py
or double-click `Run_OpenChromLab.bat`.
"""

import ctypes
import os
import sys

from agilent_ui.main_window import OpenChromLabApp


def enable_windows_dpi_awareness() -> None:
    """Enable high-DPI crisp rendering on Windows 10/11."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def main() -> None:
    enable_windows_dpi_awareness()
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        workspace_dir = os.path.abspath(sys.argv[1])

    app = OpenChromLabApp(initial_workspace=workspace_dir)
    app.mainloop()


if __name__ == "__main__":
    main()
