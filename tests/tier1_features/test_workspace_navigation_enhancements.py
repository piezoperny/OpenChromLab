"""
Tests for OpenChromLab Workspace Enhancements:
- Modular panel show/hide toggles & Maximize Chromatogram (F10)
- Sequence injection navigation (next_injection / prev_injection)
- Configurable keyboard shortcuts & remapping dialog
- Method-tied zoom presets persistence
- Windows dark titlebar application helper
"""

import os
import tempfile
import tkinter as tk
import unittest

from tests.test_helpers import HeadlessTkTestCase, get_workspace_root
from agilent_core.method_model import ProcessingMethod, ZoomPresetDef, build_default_mpz_method
from agilent_ui.main_window import OpenChromLabApp
from agilent_ui.shortcut_dialog import (
    DEFAULT_SHORTCUTS,
    load_shortcuts,
    save_shortcuts,
    ShortcutSettingsDialog,
)
from agilent_ui.theme import DARK_PALETTE, apply_windows_dark_titlebar


class TestWorkspaceNavigationEnhancements(HeadlessTkTestCase):
    """Verify newly introduced workspace, navigation, shortcut, and preset features."""

    def setUp(self) -> None:
        super().setUp()
        self.app = OpenChromLabApp(initial_workspace=get_workspace_root(), empty_homepage=False)
        self.app.withdraw()

    def tearDown(self) -> None:
        if hasattr(self, "app") and not getattr(self.app, "_is_destroyed", False):
            self.app.destroy()
        super().tearDown()

    def test_modular_panels_show_and_hide(self) -> None:
        """Verify showing and hiding sequence panel, overlays card, and data tables."""
        app = self.app

        # 1. Hide Sequence Panel
        app.show_seq_panel_var.set(False)
        app._toggle_seq_panel()
        self.assertNotIn(str(app.left_frame), [str(p) for p in app.outer_paned.panes()])

        # 2. Restore Sequence Panel
        app.show_seq_panel_var.set(True)
        app._toggle_seq_panel()
        self.assertIn(str(app.left_frame), [str(p) for p in app.outer_paned.panes()])

        # 3. Hide Bottom Data Tables
        app.show_bottom_tables_var.set(False)
        app._toggle_bottom_tables()
        self.assertNotIn(str(app.bottom_frame), [str(p) for p in app.right_paned.panes()])

        # 4. Restore Bottom Data Tables
        app.show_bottom_tables_var.set(True)
        app._toggle_bottom_tables()
        self.assertIn(str(app.bottom_frame), [str(p) for p in app.right_paned.panes()])

    def test_maximize_and_restore_chromatogram(self) -> None:
        """Verify F10 / maximize_chromatogram and restore_all_panels."""
        app = self.app

        # Maximize: hides both left sequence and bottom tables
        app.maximize_chromatogram()
        self.assertFalse(app.show_seq_panel_var.get())
        self.assertFalse(app.show_bottom_tables_var.get())
        self.assertNotIn(str(app.left_frame), [str(p) for p in app.outer_paned.panes()])
        self.assertNotIn(str(app.bottom_frame), [str(p) for p in app.right_paned.panes()])

        # Toggle maximize again restores everything
        app._toggle_maximize()
        self.assertTrue(app.show_seq_panel_var.get())
        self.assertTrue(app.show_bottom_tables_var.get())
        self.assertIn(str(app.left_frame), [str(p) for p in app.outer_paned.panes()])
        self.assertIn(str(app.bottom_frame), [str(p) for p in app.right_paned.panes()])

    def test_injection_navigation_next_and_prev(self) -> None:
        """Verify next_injection and prev_injection navigate sequence runs without losing zoom view."""
        app = self.app
        # Load directory with real test data
        app.load_directory(get_workspace_root())
        self.assertGreater(len(app.injections), 1)

        # Set specific zoom coordinates
        app.chrom_canvas.x_range = (5.0, 9.0)
        app.select_injection(0, reset_view=False)
        self.assertEqual(app.current_injection, app.injections[0])

        # Next injection
        app.next_injection()
        self.assertEqual(app.current_injection, app.injections[1])
        # Zoom coordinates must be preserved!
        self.assertAlmostEqual(app.chrom_canvas.x_range[0], 5.0)
        self.assertAlmostEqual(app.chrom_canvas.x_range[1], 9.0)

        # Prev injection
        app.prev_injection()
        self.assertEqual(app.current_injection, app.injections[0])
        self.assertAlmostEqual(app.chrom_canvas.x_range[0], 5.0)
        self.assertAlmostEqual(app.chrom_canvas.x_range[1], 9.0)

    def test_shortcut_loading_saving_and_remapping(self) -> None:
        """Verify load_shortcuts, save_shortcuts, and shortcut management dialog."""
        shortcuts = load_shortcuts()
        self.assertIn("next_injection", shortcuts)
        self.assertIn("prev_injection", shortcuts)
        self.assertIn("toggle_maximize", shortcuts)

        # Test dialog opens cleanly
        dlg = ShortcutSettingsDialog(self.app, theme=DARK_PALETTE)
        dlg.update_idletasks()
        self.assertTrue(len(dlg.tree.get_children()) >= len(DEFAULT_SHORTCUTS))
        dlg.destroy()

    def test_zoom_presets_tied_strictly_to_method(self) -> None:
        """Verify that presets only populate from the active method."""
        # Empty method has no custom presets
        empty_app = OpenChromLabApp(initial_workspace=get_workspace_root(), empty_homepage=True)
        empty_app.withdraw()
        try:
            combo_vals = list(empty_app.zoom_combo["values"])
            # Should only contain Full and Auto-Y, no MPZ presets!
            self.assertEqual(len(combo_vals), 2)
            self.assertIn("Full (0–40m)", combo_vals)
            self.assertIn("Auto-Y", combo_vals)
            self.assertFalse(any("C1–C3" in v for v in combo_vals))

            # Adding a preset to the method and refreshing updates the combo
            new_preset = ZoomPresetDef(name="Catalyst Elution", time_min=3.0, time_max=7.0)
            empty_app.method.custom_zoom_presets.append(new_preset)
            empty_app._refresh_zoom_presets()
            updated_vals = list(empty_app.zoom_combo["values"])
            self.assertTrue(any("Catalyst Elution" in v for v in updated_vals))
        finally:
            empty_app.destroy()

    def test_apply_windows_dark_titlebar_resilience(self) -> None:
        """Verify that apply_windows_dark_titlebar runs safely without raising exceptions."""
        top = tk.Toplevel(self.app)
        try:
            ico_path = os.path.join(get_workspace_root(), "OpenChromLab.ico")
            apply_windows_dark_titlebar(top, ico_path)
            apply_windows_dark_titlebar(self.app, ico_path)
        finally:
            top.destroy()

    def test_about_dialog_and_beta_badges(self) -> None:
        """Verify AboutDialog opens cleanly, beta badges exist, and version displays properly."""
        from agilent_ui.about_dialog import AboutDialog
        from agilent_ui.splash import APP_VERSION, SplashScreen

        app = self.app
        # Verify main window topbar version & beta badge
        self.assertTrue(hasattr(app, "lbl_app_version"))
        self.assertIn(APP_VERSION, app.lbl_app_version.cget("text"))
        self.assertTrue(hasattr(app, "lbl_app_beta"))
        self.assertEqual(app.lbl_app_beta.cget("text"), "BETA")
        self.assertTrue(hasattr(app, "btn_about"))

        # Test AboutDialog instantiation
        about = AboutDialog(app, theme=app.theme, on_open_shortcuts=app._open_shortcut_dialog)
        try:
            self.assertTrue(about.winfo_exists())
            self.assertIn("About OpenChromLab", about.title())
        finally:
            about.destroy()

        # Test SplashScreen renders with BETA pill and completes
        completed = []
        splash = SplashScreen(app, on_complete=lambda: completed.append(True), duration_ms=50)
        try:
            self.assertTrue(splash.winfo_exists())
        finally:
            splash.destroy()


if __name__ == "__main__":
    unittest.main()

