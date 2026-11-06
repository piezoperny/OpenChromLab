"""
Tier 1: Feature Coverage — Requirement R3 (Bidirectional Axis Pan & Scale Navigation)
Feature F21: Verifies Y-axis left-drag relative pan (constant scale), Y-axis right-drag scale,
X-axis left-drag relative pan (constant scale), X-axis right-drag scale, and preservation
of plot-body Agilent box zoom and amplitude scaling.
"""

import math
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
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_core.ch_reader import load_d_folder, find_d_folders
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method


class DummyMouseEvent:
    """Mock Tkinter mouse event."""
    def __init__(self, x: int, y: int, state: int = 0, num: int = 1):
        self.x = x
        self.y = y
        self.state = state
        self.num = num
        self.x_root = x
        self.y_root = y


class TestOpenChromLabR3AxisNavigation(HeadlessTkTestCase):
    """Test suite for Requirement R3: Bidirectional Axis Pan & Scale Navigation."""

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

    def test_r3_01_y_axis_gutter_left_drag_pans_range_constant_scale(self) -> None:
        """
        Verify that left-click dragging on the Y-axis gutter shifts the Y range up/down
        without changing the axis scale (Y max - Y min remains constant).
        Authoritative source: ORIGINAL_REQUEST.md (R3 Acceptance Criteria), Explorer 1 § 2.2.
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_y = (y0 + y1) // 2

        # Point in Y-axis gutter (left of panel left boundary x0)
        gutter_x = max(10, x0 - 20)

        # Baseline Y range
        orig_y0, orig_y1 = self.canvas_widget.y_ranges["FID1A"]
        orig_span = orig_y1 - orig_y0

        # Simulate Left Press on Y-axis gutter
        press_ev = DummyMouseEvent(x=gutter_x, y=mid_y)
        self.canvas_widget._on_left_down(press_ev)

        # Simulate Drag downwards by 40 pixels
        drag_ev = DummyMouseEvent(x=gutter_x, y=mid_y + 40)
        self.canvas_widget._on_left_drag(drag_ev)
        self.canvas_widget._on_left_up(drag_ev)

        new_y0, new_y1 = self.canvas_widget.y_ranges["FID1A"]
        new_span = new_y1 - new_y0

        # Scale invariance: difference between Y max and Y min must remain constant
        self.assertAlmostEqual(
            new_span,
            orig_span,
            places=3,
            msg=f"Y scale must remain constant during Y-axis pan. Orig span: {orig_span}, new span: {new_span}"
        )
        # Position translation: Y range bounds must have shifted
        self.assertNotEqual(
            new_y0,
            orig_y0,
            "Y bounds must have translated after left-dragging on Y-axis gutter."
        )

    def test_r3_02_y_axis_gutter_right_drag_adjusts_scale(self) -> None:
        """
        Verify that right-click dragging on the Y-axis gutter adjusts the Y scale
        (Y max - Y min changes).
        Authoritative source: ORIGINAL_REQUEST.md (R3 Acceptance Criteria), Explorer 1 § 2.2.
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_y = (y0 + y1) // 2
        gutter_x = max(10, x0 - 20)

        orig_y0, orig_y1 = self.canvas_widget.y_ranges["FID1A"]
        orig_span = orig_y1 - orig_y0

        # Simulate Right Press on Y-axis gutter
        press_ev = DummyMouseEvent(x=gutter_x, y=mid_y, num=3)
        self.canvas_widget._on_right_down(press_ev)

        # Drag upwards to scale/zoom in
        drag_ev = DummyMouseEvent(x=gutter_x, y=mid_y - 50, num=3)
        self.canvas_widget._on_right_drag(drag_ev)
        self.canvas_widget._on_right_up(drag_ev)

        new_y0, new_y1 = self.canvas_widget.y_ranges["FID1A"]
        new_span = new_y1 - new_y0

        # Scale must have changed
        self.assertNotAlmostEqual(
            new_span,
            orig_span,
            places=2,
            msg=f"Y scale must be modified by right-dragging on Y axis gutter. Orig: {orig_span}, new: {new_span}"
        )

    def test_r3_03_x_axis_gutter_left_drag_pans_range_constant_scale(self) -> None:
        """
        Verify that left-click dragging on the bottom X-axis gutter translates the time
        range without changing the time span (X max - X min remains constant).
        Authoritative source: ORIGINAL_REQUEST.md (R3 Acceptance Criteria), Explorer 1 § 2.2.
        """
        rects = self.canvas_widget._get_panel_rects()
        bottom_panel = list(rects.keys())[-1]
        x0, y0, x1, y1 = rects[bottom_panel]
        mid_x = (x0 + x1) // 2

        # Point in bottom X-axis gutter (below bottom panel border)
        gutter_y = y1 + 15

        orig_x0, orig_x1 = self.canvas_widget.x_range
        orig_span = orig_x1 - orig_x0

        # Simulate Left Press on X-axis gutter
        press_ev = DummyMouseEvent(x=mid_x, y=gutter_y)
        self.canvas_widget._on_left_down(press_ev)

        # Drag rightwards by 50 pixels
        drag_ev = DummyMouseEvent(x=mid_x + 50, y=gutter_y)
        self.canvas_widget._on_left_drag(drag_ev)
        self.canvas_widget._on_left_up(drag_ev)

        new_x0, new_x1 = self.canvas_widget.x_range
        new_span = new_x1 - new_x0

        # Scale invariance: difference between X max and X min must remain constant
        self.assertAlmostEqual(
            new_span,
            orig_span,
            places=3,
            msg=f"Time scale must remain constant during X-axis pan. Orig span: {orig_span}, new span: {new_span}"
        )
        self.assertNotEqual(
            new_x0,
            orig_x0,
            "Time range bounds must have shifted after left-dragging on X-axis gutter."
        )

    def test_r3_04_x_axis_gutter_right_drag_adjusts_scale(self) -> None:
        """
        Verify that right-click dragging on the bottom X-axis gutter adjusts the time scale
        (X max - X min changes).
        Authoritative source: ORIGINAL_REQUEST.md (R3 Acceptance Criteria), Explorer 1 § 2.2.
        """
        rects = self.canvas_widget._get_panel_rects()
        bottom_panel = list(rects.keys())[-1]
        x0, y0, x1, y1 = rects[bottom_panel]
        mid_x = (x0 + x1) // 2
        gutter_y = y1 + 15

        orig_x0, orig_x1 = self.canvas_widget.x_range
        orig_span = orig_x1 - orig_x0

        # Simulate Right Press on X-axis gutter
        press_ev = DummyMouseEvent(x=mid_x, y=gutter_y, num=3)
        self.canvas_widget._on_right_down(press_ev)

        # Drag horizontally to adjust time scale
        drag_ev = DummyMouseEvent(x=mid_x + 60, y=gutter_y, num=3)
        self.canvas_widget._on_right_drag(drag_ev)
        self.canvas_widget._on_right_up(drag_ev)

        new_x0, new_x1 = self.canvas_widget.x_range
        new_span = new_x1 - new_x0

        self.assertNotAlmostEqual(
            new_span,
            orig_span,
            places=2,
            msg=f"Time scale must be modified by right-dragging on X axis. Orig: {orig_span}, new: {new_span}"
        )

    def test_r3_05_plot_body_left_drag_preserves_agilent_box_zoom(self) -> None:
        """
        Verify that left-click drag in the center plot body initiates box zoom (zoom_box mode)
        preserving Feature F07 compatibility.
        Authoritative source: PROJECT.md (F07, F21), Explorer 1 § 2.2.
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        press_ev = DummyMouseEvent(x=mid_x, y=mid_y)
        self.canvas_widget._on_left_down(press_ev)

        drag_state = self.canvas_widget._drag_state
        self.assertIsNotNone(drag_state, "Drag state must be active after left down in plot body.")
        self.assertEqual(
            drag_state.get("mode"),
            "zoom_box",
            f"Center plot body left click must initiate 'zoom_box', got '{drag_state.get('mode')}'."
        )

    def test_r3_06_plot_body_right_drag_preserves_vertical_amplitude_scaling(self) -> None:
        """
        Verify that right-click drag in the center plot body initiates vertical amplitude
        scaling preserving Feature F08 compatibility.
        Authoritative source: PROJECT.md (F08, F21), Explorer 1 § 2.2.
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        press_ev = DummyMouseEvent(x=mid_x, y=mid_y, num=3)
        self.canvas_widget._on_right_down(press_ev)

        drag_state = self.canvas_widget._drag_state
        self.assertIsNotNone(drag_state, "Drag state must be active after right down in plot body.")
        self.assertEqual(
            drag_state.get("mode"),
            "y_amplitude",
            f"Center plot body right click must initiate 'y_amplitude', got '{drag_state.get('mode')}'."
        )


if __name__ == "__main__":
    unittest.main()
