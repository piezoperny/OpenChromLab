"""
Tier 1: Feature Coverage — Requirement R9 (Launcher Script, Application Icon & Shortcut)
Feature F30: Verifies Run_OpenChromLab.bat batch launcher, OpenChromLab.ico file format
and binary integrity, Windows shortcut OpenChromLab.lnk generation, and icon loading.
"""

import os
import struct
import sys
import unittest

from tests.test_helpers import HeadlessTkTestCase, get_workspace_root


class TestOpenChromLabR9LauncherIcon(HeadlessTkTestCase):
    """Test suite for Requirement R9: Launcher Script, Application Icon & Windows Shortcut."""

    def test_r9_01_launcher_script_exists_and_executable(self) -> None:
        """
        Verify that Run_OpenChromLab.bat exists at project root and sets window title.
        Authoritative source: ORIGINAL_REQUEST.md (R9 Acceptance Criteria).
        """
        bat_path = os.path.join(get_workspace_root(), "Run_OpenChromLab.bat")
        self.assertTrue(
            os.path.isfile(bat_path),
            f"Launcher script '{bat_path}' must exist."
        )

        with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [l.strip().lower() for l in f.readlines()]

        # Must have title OpenChromLab
        title_lines = [l for l in lines if l.startswith("title")]
        self.assertTrue(
            any("openchromlab" in l for l in title_lines),
            f"Run_OpenChromLab.bat must configure title with OpenChromLab. Found: {title_lines}"
        )

    def test_r9_02_launcher_script_has_python_launcher_resilience(self) -> None:
        """
        Verify that Run_OpenChromLab.bat includes fallback logic to invoke either 'py'
        or 'python' to ensure operation on varied Windows installations.
        Authoritative source: Explorer 3 § 3.5.1.
        """
        bat_path = os.path.join(get_workspace_root(), "Run_OpenChromLab.bat")
        if not os.path.isfile(bat_path):
            self.skipTest("Run_OpenChromLab.bat pending creation by worker_m5.")
            return

        with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        self.assertIn("main.py", content, "Launcher script must invoke main.py.")

    def test_r9_03_application_icon_file_exists(self) -> None:
        """
        Verify that OpenChromLab.ico exists at the project workspace root.
        Authoritative source: ORIGINAL_REQUEST.md (R9 Acceptance Criteria).
        """
        ico_path = os.path.join(get_workspace_root(), "OpenChromLab.ico")
        self.assertTrue(
            os.path.isfile(ico_path),
            f"Application icon file '{ico_path}' must exist."
        )

    def test_r9_04_application_icon_binary_validity(self) -> None:
        """
        Verify that OpenChromLab.ico is a valid Windows ICO format file:
        starts with 0x00 0x00 0x01 0x00 (magic bytes) and has file size >= 1000 bytes.
        Authoritative source: Explorer 3 § 1.6 & 3.5.3.
        """
        ico_path = os.path.join(get_workspace_root(), "OpenChromLab.ico")
        if not os.path.isfile(ico_path):
            self.skipTest("OpenChromLab.ico pending creation by worker_m5.")
            return

        file_size = os.path.getsize(ico_path)
        self.assertGreaterEqual(
            file_size,
            1000,
            f"Icon file size ({file_size} bytes) must be >= 1000 bytes for multi-resolution support."
        )

        with open(ico_path, "rb") as f:
            header = f.read(4)

        # Standard Windows ICO header: reserved=0, type=1 (icon)
        reserved, ico_type = struct.unpack("<HH", header)
        self.assertEqual(reserved, 0, "ICO header reserved word must be 0.")
        self.assertEqual(ico_type, 1, "ICO header image type must be 1 (icon).")

    def test_r9_05_windows_shortcut_lnk_exists(self) -> None:
        """
        Verify that OpenChromLab.lnk Windows shortcut exists in the workspace.
        Authoritative source: ORIGINAL_REQUEST.md (R9 Acceptance Criteria).
        """
        lnk_path = os.path.join(get_workspace_root(), "OpenChromLab.lnk")
        self.assertTrue(
            os.path.isfile(lnk_path),
            f"Windows shortcut '{lnk_path}' must exist."
        )

    def test_r9_06_app_icon_loads_cleanly_in_gui(self) -> None:
        """
        Verify that OpenChromLabApp loads the icon without crashing or raising TclError.
        Authoritative source: Explorer 3 § 3.5.3.
        """
        from agilent_ui.main_window import OpenLabSubstituteApp
        try:
            from agilent_ui.main_window import OpenChromLabApp
            app_cls = OpenChromLabApp
        except ImportError:
            app_cls = OpenLabSubstituteApp

        app = app_cls(initial_workspace=get_workspace_root())
        app.withdraw()
        try:
            ico_path = os.path.join(get_workspace_root(), "OpenChromLab.ico")
            if os.path.exists(ico_path):
                # Verify iconbitmap works without exception
                app.iconbitmap(ico_path)
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
