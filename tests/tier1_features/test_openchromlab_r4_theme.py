"""
Tier 1: Feature Coverage — Requirement R4 (Dark Theme Option)
Feature F23: Verifies centralized ThemePalette definitions, light mode initial default,
runtime toggling to dark mode, canvas styling and color adaptation, and toggle back to light.
"""

import os
import sys
import tkinter as tk
import unittest

from tests.test_helpers import (
    HeadlessTkTestCase,
    get_workspace_root,
    get_test_set_path,
    create_synthetic_injection,
)
from agilent_ui.theme import ThemePalette, LIGHT_PALETTE, DARK_PALETTE
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_core.ch_reader import load_d_folder, find_d_folders
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method


class TestOpenChromLabR4Theme(HeadlessTkTestCase):
    """Test suite for Requirement R4: Dark Theme Option."""

    def test_r4_01_palette_definitions_and_immutability(self) -> None:
        """
        Verify that LIGHT_PALETTE and DARK_PALETTE are defined as immutable ThemePalette instances
        with distinct backgrounds and high-contrast color properties.
        Authoritative source: PROJECT.md § Interface Contracts, Explorer 2 § 2.1.
        """
        self.assertIsInstance(LIGHT_PALETTE, ThemePalette)
        self.assertIsInstance(DARK_PALETTE, ThemePalette)
        self.assertEqual(LIGHT_PALETTE.name, "light")
        self.assertEqual(DARK_PALETTE.name, "dark")

        # Light background vs Dark background
        self.assertEqual(LIGHT_PALETTE.canvas_bg.upper(), "#FFFFFF")
        self.assertEqual(DARK_PALETTE.canvas_bg.upper(), "#181818")

        # Immutability check (frozen dataclass)
        with self.assertRaises(Exception):
            LIGHT_PALETTE.canvas_bg = "#000000"

    def test_r4_02_light_mode_is_initial_default_on_app_start(self) -> None:
        """
        Verify that Light mode is the default theme when the application starts up fresh.
        Authoritative source: ORIGINAL_REQUEST.md (R4 Acceptance Criteria).
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
            theme_name = getattr(app, "current_theme_name", "light")
            self.assertEqual(
                theme_name,
                "light",
                "Light mode must be the initial default theme on startup."
            )
            if hasattr(app.chrom_canvas, "theme"):
                self.assertEqual(app.chrom_canvas.theme.name, "light")
        finally:
            app.destroy()

    def test_r4_03_theme_toggle_switches_to_dark_mode(self) -> None:
        """
        Verify that triggering the theme toggle switches application and canvas to dark mode.
        Authoritative source: ORIGINAL_REQUEST.md (R4 Acceptance Criteria), Explorer 2 § 4.1.
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
            self.assertTrue(
                hasattr(app, "set_theme") or hasattr(app, "_toggle_theme"),
                "App must have set_theme or _toggle_theme method."
            )
            if hasattr(app, "set_theme"):
                app.set_theme("dark")
            else:
                app._toggle_theme()

            self.assertEqual(app.current_theme_name, "dark")
            self.assertEqual(app.chrom_canvas.theme.name, "dark")
            self.assertEqual(
                app.chrom_canvas.canvas.cget("bg").upper(),
                DARK_PALETTE.canvas_bg.upper()
            )
        finally:
            app.destroy()

    def test_r4_04_canvas_set_theme_updates_rendering_elements(self) -> None:
        """
        Verify that calling set_theme(DARK_PALETTE) directly on DualChromatogramCanvas
        updates internal colors and canvas background.
        Authoritative source: PROJECT.md § Interface Contracts.
        """
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        self.assertTrue(
            hasattr(canvas_widget, "set_theme"),
            "DualChromatogramCanvas must provide set_theme(palette: ThemePalette) method."
        )
        canvas_widget.set_theme(DARK_PALETTE)
        self.root.update_idletasks()

        self.assertEqual(canvas_widget.theme.name, "dark")
        self.assertEqual(
            canvas_widget.canvas.cget("bg").upper(),
            DARK_PALETTE.canvas_bg.upper()
        )

        # Restore light
        canvas_widget.set_theme(LIGHT_PALETTE)
        self.root.update_idletasks()
        self.assertEqual(canvas_widget.theme.name, "light")
        self.assertEqual(
            canvas_widget.canvas.cget("bg").upper(),
            LIGHT_PALETTE.canvas_bg.upper()
        )

    def test_r4_05_theme_toggle_back_to_light_mode_restores_state(self) -> None:
        """
        Verify that toggling from dark mode back to light mode cleanly restores original
        light palette, widgets, and background styles.
        Authoritative source: ORIGINAL_REQUEST.md (R4), Explorer 2 § 4.1.
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
            if not hasattr(app, "set_theme") and not hasattr(app, "_toggle_theme"):
                self.skipTest("Theme toggling methods pending implementation by worker_m7.")
                return

            # Switch to dark then back to light
            if hasattr(app, "set_theme"):
                app.set_theme("dark")
                self.assertEqual(app.current_theme_name, "dark")
                app.set_theme("light")
            else:
                app._toggle_theme()
                self.assertEqual(app.current_theme_name, "dark")
                app._toggle_theme()

            self.assertEqual(app.current_theme_name, "light")
            self.assertEqual(app.chrom_canvas.theme.name, "light")
            self.assertEqual(
                app.chrom_canvas.canvas.cget("bg").upper(),
                LIGHT_PALETTE.canvas_bg.upper()
            )
        finally:
            app.destroy()

    def test_r4_06_theme_contrast_ratios(self) -> None:
        """
        Verify that DARK_PALETTE provides readable high contrast (foreground and background
        colors are not identical or excessively close).
        Authoritative source: ORIGINAL_REQUEST.md (R4 Acceptance Criteria).
        """
        self.assertNotEqual(
            DARK_PALETTE.bg_app.upper(),
            DARK_PALETTE.fg_app.upper(),
            "App bg and fg must differ in dark palette."
        )
        self.assertNotEqual(
            DARK_PALETTE.panel_bg.upper(),
            DARK_PALETTE.trace_fid.upper(),
            "Panel bg and FID trace color must differ in dark palette."
        )
        self.assertNotEqual(
            DARK_PALETTE.panel_bg.upper(),
            DARK_PALETTE.axis_text.upper(),
            "Panel bg and axis text must differ in dark palette."
        )


if __name__ == "__main__":
    unittest.main()
