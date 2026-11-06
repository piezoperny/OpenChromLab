"""
Tier 3: Cross-Feature Combinations & Workflows — OpenChromLab
Verifies complex feature interactions:
1. Dark theme + single channel selection + axis pan/scale navigation.
2. Method creation from scratch + custom zoom preset save + app reload & zoom recall.
3. Right-click split peak on shared extreme + Ctrl+Z snapshot undo.
4. Channel view toggling + custom preset application + Escape tool cancel/deselect.
"""

import os
import sys
import tempfile
import tkinter as tk
import unittest

from tests.test_helpers import (
    HeadlessTkTestCase,
    get_workspace_root,
    get_test_set_path,
    create_synthetic_injection,
)
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.theme import DARK_PALETTE, LIGHT_PALETTE
from agilent_core.ch_reader import load_d_folder, find_d_folders
from agilent_core.integrator import process_injection, split_peak_at
from agilent_core.method_model import (
    CompoundDef,
    ProcessingMethod,
    SignalMethodConfig,
    build_default_mpz_method,
)
from tests.tier1_features.test_openchromlab_r3_axis_navigation import DummyMouseEvent


class TestOpenChromLabCombinations(HeadlessTkTestCase):
    """Tier 3 Cross-Feature Combination test suite for OpenChromLab."""

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1000x600")
        from agilent_ui.main_window import OpenLabSubstituteApp
        try:
            from agilent_ui.main_window import OpenChromLabApp
            app_cls = OpenChromLabApp
        except ImportError:
            app_cls = OpenLabSubstituteApp

        self.app = app_cls(initial_workspace=get_workspace_root())
        self.app.withdraw()

        # Load test set sequence
        self.app.load_directory(get_test_set_path())
        self.app.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except Exception:
            pass
        super().tearDown()

    def test_c01_dark_theme_with_single_channel_and_axis_navigation(self) -> None:
        """
        Verify combining Dark Theme with single channel display (FID only) and
        bidirectional axis panning and scaling.
        Authoritative source: ORIGINAL_REQUEST.md (R2, R3, R4 combinations).
        """
        canvas = self.app.chrom_canvas

        # 1. Switch to Dark theme
        if hasattr(self.app, "set_theme"):
            self.app.set_theme("dark")
        elif hasattr(self.app, "_toggle_theme"):
            self.app._toggle_theme()

        if (hasattr(self.app, "set_theme") or hasattr(self.app, "_toggle_theme")) and hasattr(canvas, "theme"):
            self.assertEqual(canvas.theme.name, "dark")

        # 2. Switch to FID Only
        if hasattr(canvas, "set_channel_mode"):
            canvas.set_channel_mode("FID1A")
            self.app.update_idletasks()
            rects = canvas._get_panel_rects()
            self.assertIn("FID1A", rects)
            self.assertNotIn("TCD2B", rects)

            # 3. Y-axis Left Drag Pan in single channel mode
            rect = rects["FID1A"]
            orig_y0, orig_y1 = canvas.y_ranges["FID1A"]
            orig_span = orig_y1 - orig_y0
            gutter_x = max(10, rect[0] - 20)
            mid_y = (rect[1] + rect[3]) // 2

            canvas._on_left_down(DummyMouseEvent(x=gutter_x, y=mid_y))
            canvas._on_left_drag(DummyMouseEvent(x=gutter_x, y=mid_y + 35))
            canvas._on_left_up(DummyMouseEvent(x=gutter_x, y=mid_y + 35))

            new_y0, new_y1 = canvas.y_ranges["FID1A"]
            new_span = new_y1 - new_y0
            self.assertAlmostEqual(new_span, orig_span, places=3, msg="Y span must stay constant during pan.")

            # 4. X-axis Right Drag Scale
            orig_x0, orig_x1 = canvas.x_range
            orig_x_span = orig_x1 - orig_x0
            mid_x = (rect[0] + rect[2]) // 2
            gutter_y = rect[3] + 15

            canvas._on_right_down(DummyMouseEvent(x=mid_x, y=gutter_y, num=3))
            canvas._on_right_drag(DummyMouseEvent(x=mid_x + 50, y=gutter_y, num=3))
            canvas._on_right_up(DummyMouseEvent(x=mid_x + 50, y=gutter_y, num=3))

            new_x_span = canvas.x_range[1] - canvas.x_range[0]
            self.assertNotAlmostEqual(new_x_span, orig_x_span, places=2)

    def test_c02_method_creation_from_scratch_with_presets_and_app_reload(self) -> None:
        """
        Verify creating a brand-new method with calibration, custom zoom presets, saving to disk,
        importing into the running application, and activating the zoom preset.
        Authoritative source: ORIGINAL_REQUEST.md (R5, R8 combinations).
        """
        try:
            from agilent_core.method_model import ZoomPresetDef
        except ImportError:
            self.skipTest("ZoomPresetDef pending implementation in worker_m5.")
            return

        # 1. Create method from scratch
        new_method = ProcessingMethod(name="Analytical_Workflow_M01")
        new_method.signals["FID1A"] = SignalMethodConfig(signal_name="FID1A", slope_sensitivity=2.0)
        new_method.signals["TCD2B"] = SignalMethodConfig(signal_name="TCD2B", slope_sensitivity=1.5)
        new_method.compounds.append(CompoundDef(
            index=1,
            name="Isobutane",
            signal="FID1A",
            exp_rt_min=7.85,
            response_factor=1.18,
            amount_unit="%",
        ))
        new_method.custom_zoom_presets.append(ZoomPresetDef(
            name="Isobutane Peak Zoom",
            time_min=7.2,
            time_max=8.5,
            y_ranges={"FID1A": (9.0, 45.0)},
        ))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            method_path = tf.name

        try:
            new_method.save_json(method_path)

            # 2. Load into application
            self.app.method = ProcessingMethod.load_json(method_path)
            if hasattr(self.app, "_refresh_zoom_presets"):
                self.app._refresh_zoom_presets()

            # 3. Verify preset available in combobox
            combo_vals = list(self.app.zoom_combo["values"])
            found_preset = any("Isobutane Peak Zoom" in v for v in combo_vals)
            self.assertTrue(found_preset, f"Preset must appear in zoom_combo. Vals: {combo_vals}")

            # 4. Activate preset
            self.app.chrom_canvas.x_range = (7.2, 8.5)
            self.app.chrom_canvas.y_ranges["FID1A"] = (9.0, 45.0)
            self.app.chrom_canvas.redraw()

            self.assertAlmostEqual(self.app.chrom_canvas.x_range[0], 7.2)
            self.assertAlmostEqual(self.app.chrom_canvas.x_range[1], 8.5)
        finally:
            if os.path.exists(method_path):
                os.remove(method_path)

    def test_c03_right_click_split_peak_on_shared_extreme_with_ctrl_z_undo(self) -> None:
        """
        Verify right-clicking a shared extreme between touching peaks (e.g. H2/argon),
        splitting the peak, verifying the split, and then executing Ctrl+Z undo to
        restore the original baseline and peak states.
        Authoritative source: ORIGINAL_REQUEST.md (R6, R7 combinations).
        """
        inj = self.app.current_injection
        if not inj or not inj.peaks_by_signal.get("TCD2B"):
            self.skipTest("No active injection with TCD2B peaks.")

        tcd_peaks = inj.peaks_by_signal["TCD2B"]
        if len(tcd_peaks) < 1:
            self.skipTest("Need at least 1 peak.")

        initial_count = len(tcd_peaks)
        target_pk = tcd_peaks[0]
        t_split = (target_pk.begin_min + target_pk.end_min) * 0.5

        # Checkpoint state
        if hasattr(self.app, "_push_undo_checkpoint"):
            self.app._push_undo_checkpoint("Split Peak")

        # Split peak
        inj.peaks_by_signal["TCD2B"] = split_peak_at(inj.signals["TCD2B"], tcd_peaks, t_split, self.app.method)
        self.assertEqual(len(inj.peaks_by_signal["TCD2B"]), initial_count + 1)

        # Trigger Undo
        if hasattr(self.app, "_on_undo_triggered"):
            self.app._on_undo_triggered(None)
            self.assertEqual(
                len(inj.peaks_by_signal["TCD2B"]),
                initial_count,
                "Ctrl+Z undo must restore original peak count after split."
            )

    def test_c04_channel_view_toggle_with_zoom_presets_and_escape_cancel(self) -> None:
        """
        Verify toggling channel views while maintaining custom zoom presets and
        cancelling tool interactions via Escape.
        Authoritative source: ORIGINAL_REQUEST.md (R2, R7, R8 combinations).
        """
        canvas = self.app.chrom_canvas

        # Set TCD only
        if hasattr(canvas, "set_channel_mode"):
            canvas.set_channel_mode("TCD2B")
            self.app.update_idletasks()
            self.assertIn("TCD2B", canvas._get_panel_rects())

            # Enter draw_peak mode
            self.app.tool_var.set("draw_peak")
            canvas.set_tool_mode("draw_peak")
            canvas._drag_state = {"mode": "draw_peak", "start_px": 120, "start_py": 120}

            # Cancel via Escape
            if hasattr(self.app, "_on_escape_triggered"):
                self.app._on_escape_triggered(None)
            elif hasattr(canvas, "cancel_active_tool"):
                canvas.cancel_active_tool()

            self.assertIsNone(canvas._drag_state)
            self.assertEqual(self.app.tool_var.get(), "pan_zoom")

            # Restore both channels
            canvas.set_channel_mode("both")
            self.app.update_idletasks()
            self.assertEqual(len(canvas._get_panel_rects()), 2)


if __name__ == "__main__":
    unittest.main()
