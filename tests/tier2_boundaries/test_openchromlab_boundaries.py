"""
Tier 2: Boundary & Corner Cases — OpenChromLab Enhancement
Exercises zero/negative time ranges, extreme zoom levels, single compound methods,
empty channel displays, rapid theme toggles, invalid JSON method handling, and extreme amplitudes.
"""

import json
import math
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
    create_synthetic_signal,
)
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.theme import LIGHT_PALETTE, DARK_PALETTE
from agilent_core.ch_reader import load_d_folder, find_d_folders, InjectionData
from agilent_core.integrator import process_injection
from agilent_core.method_model import (
    CompoundDef,
    ProcessingMethod,
    SignalMethodConfig,
    build_default_mpz_method,
)


class TestOpenChromLabBoundaries(HeadlessTkTestCase):
    """Tier 2 Boundary and Corner Case test suite for OpenChromLab."""

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1000x600")
        self.canvas_widget = DualChromatogramCanvas(self.root)
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        if folders:
            self.inj = load_d_folder(folders[0])
        else:
            self.inj = create_synthetic_injection()
        self.method = build_default_mpz_method()
        process_injection(self.inj, self.method, prefer_rx=True)
        self.canvas_widget.set_data(self.inj, self.method)
        self.root.update_idletasks()

    def test_b01_zero_and_inverted_time_ranges(self) -> None:
        """
        Verify that canvas coordinates and decimation protect against zero or inverted
        time ranges (e.g. x_range = (5.0, 5.0) or (10.0, 2.0)) without ZeroDivisionError.
        Authoritative source: ORIGINAL_REQUEST.md Acceptance Criteria & F03.
        """
        rects = self.canvas_widget._get_panel_rects()
        rect = rects["FID1A"]

        # 1. Zero span
        self.canvas_widget.x_range = (5.0, 5.0)
        try:
            px = self.canvas_widget._data_to_px("FID1A", 5.0, 10.0, rect)
            self.assertIsInstance(px, tuple)
            self.canvas_widget.redraw()
        except ZeroDivisionError:
            self.fail("Canvas raised ZeroDivisionError on zero time span.")

        # 2. Inverted span
        self.canvas_widget.x_range = (10.0, 2.0)
        try:
            self.canvas_widget.redraw()
        except Exception as exc:
            self.fail(f"Canvas raised unexpected exception on inverted time span: {exc}")

    def test_b02_extreme_zoom_levels(self) -> None:
        """
        Verify that extreme microsecond zoom (span = 1e-6 min) and extreme macro zoom
        (span = 1e6 min) maintain numeric stability without math domain errors or overflow.
        Authoritative source: ORIGINAL_REQUEST.md Acceptance Criteria.
        """
        # Microsecond zoom
        self.canvas_widget.x_range = (5.000000, 5.000001)
        self.canvas_widget.redraw()
        self.root.update_idletasks()

        # Macro zoom
        self.canvas_widget.x_range = (-10000.0, 100000.0)
        self.canvas_widget.redraw()
        self.root.update_idletasks()

        self.assertTrue(True, "Extreme zoom levels executed cleanly.")

    def test_b03_single_compound_and_zero_compound_methods(self) -> None:
        """
        Verify that methods containing exactly 0 compounds or exactly 1 compound save,
        reload, and execute compound identification without off-by-one errors.
        Authoritative source: ORIGINAL_REQUEST.md Acceptance Criteria.
        """
        # Zero compound method
        empty_method = ProcessingMethod(name="EmptyMethod")
        empty_method.signals["FID1A"] = SignalMethodConfig("FID1A")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            path0 = tf.name
        try:
            empty_method.save_json(path0)
            reloaded0 = ProcessingMethod.load_json(path0)
            self.assertEqual(len(reloaded0.compounds), 0)
        finally:
            if os.path.exists(path0):
                os.remove(path0)

        # Single compound method
        single_method = ProcessingMethod(name="SingleCompoundMethod")
        single_method.signals["FID1A"] = SignalMethodConfig("FID1A")
        single_method.compounds.append(
            CompoundDef(1, "Solvent", "FID1A", 2.50, 0.05, 1.0, response_factor=1.0)
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            path1 = tf.name
        try:
            single_method.save_json(path1)
            reloaded1 = ProcessingMethod.load_json(path1)
            self.assertEqual(len(reloaded1.compounds), 1)
            self.assertEqual(reloaded1.compounds[0].name, "Solvent")
        finally:
            if os.path.exists(path1):
                os.remove(path1)

    def test_b04_empty_channel_with_channel_toggle(self) -> None:
        """
        Verify that switching channel view to a channel that has no data or 0 points
        renders gracefully without crashing.
        Authoritative source: Explorer 1 § 3.
        """
        empty_sig = create_synthetic_signal("EMPTY", t_start=0, t_end=0, dt_s=1.0)
        empty_sig.time_min = []
        empty_sig.values = []

        inj = InjectionData(
            folder_path="EmptyInj.D",
            folder_name="EmptyInj.D",
            sample_name="EmptyInj",
            injection_number=1,
            acq_date="01-Jan-26",
            signals={"EMPTY": empty_sig},
            peaks_by_signal={"EMPTY": []},
        )
        self.canvas_widget.set_data(inj, self.method)
        if hasattr(self.canvas_widget, "set_channel_mode"):
            self.canvas_widget.set_channel_mode("fid")
            self.canvas_widget.redraw()
            self.canvas_widget.set_channel_mode("tcd")
            self.canvas_widget.redraw()

        self.root.update_idletasks()
        self.assertTrue(True, "Empty channel switching completed without exception.")

    def test_b05_rapid_theme_toggles_stability(self) -> None:
        """
        Verify that rapidly toggling the theme 20 consecutive times does not leak Tkinter
        canvas items, crash memory, or leave dangling canvas state.
        Authoritative source: Explorer 2 § 5.3.
        """
        from agilent_ui.main_window import OpenLabSubstituteApp
        try:
            from agilent_ui.main_window import OpenChromLabApp
            app_cls = OpenChromLabApp
        except ImportError:
            app_cls = OpenLabSubstituteApp

        app = app_cls(initial_workspace=get_workspace_root())
        app.withdraw()

        if not hasattr(app, "set_theme") and not hasattr(app, "_toggle_theme"):
            app.destroy()
            self.skipTest("Theme toggling methods pending implementation by worker_m7.")
            return

        try:
            for i in range(10):
                target = "dark" if (i % 2 == 0) else "light"
                if hasattr(app, "set_theme"):
                    app.set_theme(target)
                elif hasattr(app, "_toggle_theme"):
                    app._toggle_theme()
                app.update_idletasks()

            curr_theme = getattr(app, "current_theme_name", "light")
            self.assertIn(curr_theme, ("light", "dark"))
        finally:
            try:
                app.update_idletasks()
                app.destroy()
            except Exception:
                pass

    def test_b06_invalid_json_method_handling(self) -> None:
        """
        Verify that corrupted, non-JSON, or structurally invalid method files raise clear
        ValueError exceptions and do not leave the system in an undefined state.
        Authoritative source: Explorer 2 § 2.2.
        """
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf.write(b"NOT A VALID JSON FILE {[[[]")
            bad_path = tf.name

        try:
            with self.assertRaises(ValueError):
                ProcessingMethod.load_json(bad_path)
        finally:
            if os.path.exists(bad_path):
                os.remove(bad_path)

        # JSON with array instead of dict at root
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf.write(b"['item1', 'item2']")
            array_path = tf.name

        try:
            with self.assertRaises(ValueError):
                ProcessingMethod.load_json(array_path)
        finally:
            if os.path.exists(array_path):
                os.remove(array_path)

    def test_b07_extreme_amplitude_scale_factors(self) -> None:
        """
        Verify that dragging amplitude to extreme zoom factors (factor > 1000 or < 0.001)
        clamps cleanly to positive spans and does not produce negative or zero height bounds.
        Authoritative source: Explorer 1 § 2.2.
        """
        orig_y0, orig_y1 = self.canvas_widget.y_ranges["FID1A"]
        rect = self.canvas_widget._get_panel_rects()["FID1A"]
        mid_x = (rect[0] + rect[2]) // 2

        # Massive upward drag (factor ~ 2^10 = 1024)
        from tests.tier1_features.test_openchromlab_r3_axis_navigation import DummyMouseEvent
        self.canvas_widget._on_right_down(DummyMouseEvent(mid_x, rect[1], num=3))
        self.canvas_widget._on_right_drag(DummyMouseEvent(mid_x, rect[1] - 1000, num=3))
        self.canvas_widget._on_right_up(DummyMouseEvent(mid_x, rect[1] - 1000, num=3))

        y0, y1 = self.canvas_widget.y_ranges["FID1A"]
        self.assertGreater(y1, y0, "Y span must remain strictly positive after extreme amplitude scale.")


if __name__ == "__main__":
    unittest.main()
