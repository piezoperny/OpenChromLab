"""
Tier 1: Feature Coverage — Requirement R1 (Software Renaming to OpenChromLab)
Feature F19: Verifies application window title, header labels, backward compatibility
alias, launcher batch scripts, and entry point references.
"""

import os
import sys
import unittest
import tkinter as tk

from tests.test_helpers import HeadlessTkTestCase, get_workspace_root


class TestOpenChromLabR1Renaming(HeadlessTkTestCase):
    """Test suite for Requirement R1: Software Renaming to OpenChromLab."""

    def test_r1_01_window_title_contains_openchromlab(self) -> None:
        """
        Verify that the application window title explicitly contains 'OpenChromLab'.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F19).
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
            title = app.title()
            self.assertIn(
                "OpenChromLab",
                title,
                f"Window title '{title}' must contain 'OpenChromLab' per requirement R1."
            )
        finally:
            app.destroy()

    def test_r1_02_header_banner_label_displays_openchromlab(self) -> None:
        """
        Verify that the primary header label in the top toolbar displays 'OpenChromLab'.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F19).
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
            # Find all tk.Label widgets in the app
            found_header = False
            for child in app.winfo_children():
                if isinstance(child, tk.Frame):
                    for subchild in child.winfo_children():
                        if isinstance(subchild, tk.Label):
                            text = subchild.cget("text")
                            if "OpenChromLab" in text:
                                found_header = True
                                break
                if found_header:
                    break

            self.assertTrue(
                found_header,
                "Top header banner label must display 'OpenChromLab' per requirement R1."
            )
        finally:
            app.destroy()

    def test_r1_03_backward_compatibility_alias_preserved(self) -> None:
        """
        Verify that OpenLabSubstituteApp is preserved as an alias for OpenChromLabApp
        to ensure all legacy test suites and scripts continue to function without modification.
        Authoritative source: PROJECT.md § Interface Contracts (Backward Compatibility Alias).
        """
        import agilent_ui.main_window as mw
        self.assertTrue(
            hasattr(mw, "OpenChromLabApp"),
            "agilent_ui.main_window must define class OpenChromLabApp per requirement R1."
        )
        self.assertTrue(
            hasattr(mw, "OpenLabSubstituteApp"),
            "agilent_ui.main_window must define backward-compatibility alias OpenLabSubstituteApp."
        )
        self.assertIs(
            mw.OpenLabSubstituteApp,
            mw.OpenChromLabApp,
            "OpenLabSubstituteApp must be an identical alias to OpenChromLabApp."
        )

    def test_r1_04_run_openchromlab_bat_script_exists_and_valid(self) -> None:
        """
        Verify that Run_OpenChromLab.bat exists at the workspace root, sets the title
        to OpenChromLab, and executes main.py.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F30).
        """
        bat_path = os.path.join(get_workspace_root(), "Run_OpenChromLab.bat")
        self.assertTrue(
            os.path.isfile(bat_path),
            f"Launcher script '{bat_path}' must exist at the workspace root."
        )

        with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        self.assertIn(
            "OpenChromLab",
            content,
            "Run_OpenChromLab.bat must reference 'OpenChromLab' in title or execution."
        )
        self.assertIn(
            "main.py",
            content,
            "Run_OpenChromLab.bat must execute main.py."
        )

    def test_r1_05_legacy_run_openlab_substitute_bat_exists(self) -> None:
        """
        Verify that the legacy Run_OpenLab_Substitute.bat exists and continues to operate
        or forward to the new launcher without breaking existing user workflows.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md § Architecture.
        """
        legacy_bat_path = os.path.join(get_workspace_root(), "Run_OpenLab_Substitute.bat")
        self.assertTrue(
            os.path.isfile(legacy_bat_path),
            f"Legacy launcher script '{legacy_bat_path}' must remain intact for backward compatibility."
        )

    def test_r1_06_main_entrypoint_references_openchromlab(self) -> None:
        """
        Verify that main.py initializes the application using OpenChromLabApp.
        Authoritative source: PROJECT.md (F19).
        """
        main_py = os.path.join(get_workspace_root(), "main.py")
        self.assertTrue(os.path.isfile(main_py), "main.py must exist at workspace root.")
        with open(main_py, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn(
            "OpenChromLabApp",
            code,
            "main.py should instantiate OpenChromLabApp."
        )


if __name__ == "__main__":
    unittest.main()
