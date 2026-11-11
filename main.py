"""
Entry point for OpenChromLab — Chromatography Data System.
Educational & University Research Edition.

Run with:
    py main.py
or double-click `OpenChromLab.bat`.
"""

import ctypes
import os
import sys

from agilent_ui.main_window import OpenChromLabApp
from agilent_ui.splash import APP_VERSION, SplashScreen

__version__ = APP_VERSION


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


def enable_windows_dark_mode() -> None:
    """Enable Windows 10/11 native immersive dark mode for titlebars and menus."""
    if sys.platform == "win32":
        try:
            # Ordinal 135 in uxtheme.dll is SetPreferredAppMode (2 = ForceDark)
            ctypes.windll.uxtheme[135](2)
        except Exception:
            pass


def main() -> None:
    enable_windows_dpi_awareness()
    enable_windows_dark_mode()

    cli_dir = None
    args = [a for a in sys.argv[1:] if a != "--no-splash"]
    if args and os.path.exists(args[0]):
        cli_dir = os.path.abspath(args[0])

    show_splash = "--no-splash" not in sys.argv

    if not show_splash:
        app = OpenChromLabApp(initial_workspace=cli_dir)
        app.mainloop()
        return

    # Create app initially hidden while 2-second splash screen loads
    app = OpenChromLabApp(initial_workspace=cli_dir)
    app.withdraw()

    def _reveal_app() -> None:
        if app.winfo_exists():
            app.deiconify()
            app.lift()

    SplashScreen(app, on_complete=_reveal_app, duration_ms=2000)
    app.mainloop()


if __name__ == "__main__":
    main()
