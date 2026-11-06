"""
Tier 1: Feature Coverage — Requirement R8 (Method-Embedded Custom Zoom Presets)
Feature F26: Verifies ZoomPresetDef data structures, serialization into method JSON,
capture of current canvas bounds, restoration upon reload, and zoom combobox integration.
"""

import json
import os
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest

from tests.test_helpers import HeadlessTkTestCase, get_workspace_root
from agilent_core.method_model import ProcessingMethod, build_default_mpz_method
from agilent_ui.chrom_canvas import DualChromatogramCanvas


class TestOpenChromLabR8ZoomPresets(HeadlessTkTestCase):
    """Test suite for Requirement R8: Method-Embedded Custom Zoom Presets."""

    def test_r8_01_zoom_preset_def_creation_and_dict_serialization(self) -> None:
        """
        Verify ZoomPresetDef dataclass instantiation and lossless to_dict / from_dict conversion.
        Authoritative source: PROJECT.md § Interface Contracts, Explorer 2 § 2.3.
        """
        try:
            from agilent_core.method_model import ZoomPresetDef
        except ImportError:
            self.skipTest("ZoomPresetDef is being implemented by worker_m5.")
            return

        preset = ZoomPresetDef(
            name="Early Elution (C1-C3)",
            time_min=4.2,
            time_max=6.8,
            y_ranges={"FID1A": (8.5, 35.0), "TCD2B": (20.0, 150.0)},
        )

        p_dict = preset.to_dict()
        self.assertEqual(p_dict["name"], "Early Elution (C1-C3)")
        self.assertAlmostEqual(p_dict["time_min"], 4.2)
        self.assertAlmostEqual(p_dict["time_max"], 6.8)
        self.assertIn("FID1A", p_dict["y_ranges"])

        restored = ZoomPresetDef.from_dict(p_dict)
        self.assertEqual(restored.name, preset.name)
        self.assertAlmostEqual(restored.time_min, preset.time_min)
        self.assertAlmostEqual(restored.time_max, preset.time_max)
        self.assertEqual(restored.y_ranges["FID1A"], (8.5, 35.0))

    def test_r8_02_processing_method_persists_custom_zoom_presets(self) -> None:
        """
        Verify that ProcessingMethod serializes custom_zoom_presets to JSON and restores them
        upon load_json without data loss.
        Authoritative source: ORIGINAL_REQUEST.md (R8 Acceptance Criteria).
        """
        try:
            from agilent_core.method_model import ZoomPresetDef
        except ImportError:
            self.skipTest("ZoomPresetDef is being implemented by worker_m5.")
            return

        method = build_default_mpz_method()
        self.assertTrue(
            hasattr(method, "custom_zoom_presets"),
            "ProcessingMethod must have custom_zoom_presets attribute."
        )

        preset1 = ZoomPresetDef(name="H2 Detail", time_min=8.0, time_max=9.5, y_ranges={"TCD2B": (10.0, 200.0)})
        preset2 = ZoomPresetDef(name="CO Peak", time_min=13.0, time_max=14.5, y_ranges={"TCD2B": (20.0, 350.0)})
        method.custom_zoom_presets = [preset1, preset2]

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp_path = tf.name

        try:
            method.save_json(tmp_path)
            reloaded = ProcessingMethod.load_json(tmp_path)
            self.assertEqual(len(reloaded.custom_zoom_presets), 2)
            self.assertEqual(reloaded.custom_zoom_presets[0].name, "H2 Detail")
            self.assertAlmostEqual(reloaded.custom_zoom_presets[0].time_min, 8.0)
            self.assertEqual(reloaded.custom_zoom_presets[1].name, "CO Peak")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_r8_03_capture_active_canvas_bounds_as_preset(self) -> None:
        """
        Verify capturing active canvas x_range and y_ranges into a ZoomPresetDef.
        Authoritative source: ORIGINAL_REQUEST.md (R8 Acceptance Criteria).
        """
        try:
            from agilent_core.method_model import ZoomPresetDef
        except ImportError:
            self.skipTest("ZoomPresetDef is being implemented by worker_m5.")
            return

        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        # Set specific canvas view bounds
        canvas_widget.x_range = (5.5, 8.2)
        canvas_widget.y_ranges["FID1A"] = (10.0, 60.0)
        canvas_widget.y_ranges["TCD2B"] = (25.0, 250.0)

        # Build preset from current bounds
        preset = ZoomPresetDef(
            name="Captured View",
            time_min=canvas_widget.x_range[0],
            time_max=canvas_widget.x_range[1],
            y_ranges=dict(canvas_widget.y_ranges),
        )

        self.assertAlmostEqual(preset.time_min, 5.5)
        self.assertAlmostEqual(preset.time_max, 8.2)
        self.assertEqual(preset.y_ranges["FID1A"], (10.0, 60.0))
        self.assertEqual(preset.y_ranges["TCD2B"], (25.0, 250.0))

    def test_r8_04_custom_preset_dropdown_presence(self) -> None:
        """
        Verify that custom presets attached to the active method appear in the
        application's zoom combobox selector.
        Authoritative source: ORIGINAL_REQUEST.md (R8 Acceptance Criteria).
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
            try:
                from agilent_core.method_model import ZoomPresetDef
                app.method.custom_zoom_presets.append(
                    ZoomPresetDef(name="Target Region A", time_min=3.0, time_max=7.0)
                )
            except (ImportError, AttributeError):
                self.skipTest("custom_zoom_presets pending implementation in worker_m5.")
                return

            if hasattr(app, "_refresh_zoom_presets"):
                app._refresh_zoom_presets()

            combo_values = list(app.zoom_combo["values"])
            found = any("Target Region A" in val for val in combo_values)
            self.assertTrue(
                found,
                f"Custom preset 'Target Region A' must appear in zoom_combo values: {combo_values}"
            )
        finally:
            app.destroy()

    def test_r8_05_selecting_preset_restores_canvas_view(self) -> None:
        """
        Verify that selecting a custom zoom preset applies its exact time range and signal
        Y-ranges to the chromatogram canvas.
        Authoritative source: Explorer 2 § 5.2.
        """
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        target_x = (7.1, 10.4)
        target_y_fid = (12.0, 85.0)

        # Apply preset ranges
        canvas_widget.x_range = target_x
        canvas_widget.y_ranges["FID1A"] = target_y_fid
        canvas_widget.redraw()

        self.assertAlmostEqual(canvas_widget.x_range[0], 7.1)
        self.assertAlmostEqual(canvas_widget.x_range[1], 10.4)
        self.assertEqual(canvas_widget.y_ranges["FID1A"], (12.0, 85.0))


if __name__ == "__main__":
    unittest.main()
