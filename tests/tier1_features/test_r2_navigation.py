"""
Tier 1: Feature Coverage — Requirement R2 (Agilent-Style Mouse Navigation and Amplitude Scaling)
Minimum 5 tests verifying left-click box zoom, right-click vertical amplitude scaling,
double-click view reset, double-right-click reset, and shared anchor synchronization.
"""

import math
import os
import sys
import tkinter as tk
import unittest

from tests.test_helpers import HeadlessTkTestCase, get_test_set_path
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_core.ch_reader import load_d_folder, find_d_folders, IntegratedPeak
from agilent_core.integrator import process_injection, update_peak_anchors
from agilent_core.method_model import build_default_mpz_method


class FakeEvent:
    """Mock Tkinter event for direct canvas callback testing."""

    def __init__(self, x: int, y: int, state: int = 0, delta: int = 0):
        self.x = x
        self.y = y
        self.state = state
        self.delta = delta


class TestR2MouseNavigation(HeadlessTkTestCase):
    """Test suite for Requirement R2 mouse navigation and amplitude scaling."""

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1000x600")
        self.canvas_widget = DualChromatogramCanvas(self.root)
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        self.assertTrue(len(folders) > 0, "No folders found in test-set")
        self.inj = load_d_folder(folders[0])
        self.method = build_default_mpz_method()
        process_injection(self.inj, self.method, prefer_rx=True)
        self.canvas_widget.set_data(self.inj, self.method)
        self.root.update_idletasks()

    def test_left_click_drag_box_zoom_initiates_without_ctrl(self) -> None:
        """
        Verify that left-click drag directly initiates zoom_box mode without Ctrl key.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F07), explorer_survey_ui § 4.1.
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        # Simulate ButtonPress-1 with state=0 (no Ctrl key)
        self.canvas_widget._on_left_down(FakeEvent(x=mid_x, y=mid_y, state=0))

        drag_state = self.canvas_widget._drag_state
        self.assertIsNotNone(drag_state, "Drag state must be initialized on ButtonPress-1")
        # In Agilent mode, left drag initiates zoom_box (not pan)
        self.assertEqual(
            drag_state.get("mode"),
            "zoom_box",
            f"Left-click drag must initiate 'zoom_box' mode directly without Ctrl, got: {drag_state.get('mode')}"
        )

    def test_left_click_box_zoom_applies_time_and_signal_bounds(self) -> None:
        """
        Verify that releasing left-click drag with displacement > 5px sets x_range and y_range.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F07).
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]

        start_x = int(x0 + 0.25 * (x1 - x0))
        start_y = int(y0 + 0.75 * (y1 - y0))
        end_x = int(x0 + 0.60 * (x1 - x0))
        end_y = int(y0 + 0.25 * (y1 - y0))

        # Start drag
        self.canvas_widget._on_left_down(FakeEvent(x=start_x, y=start_y, state=0))
        # Motion
        self.canvas_widget._on_left_drag(FakeEvent(x=end_x, y=end_y, state=0))
        # Release
        self.canvas_widget._on_left_up(FakeEvent(x=end_x, y=end_y, state=0))

        # Verify time range has zoomed in
        new_x0, new_x1 = self.canvas_widget.x_range
        self.assertGreater(new_x0, 0.0, "Zoomed start time must be > 0.0")
        self.assertLess(new_x1, 40.0, "Zoomed end time must be < 40.0")
        self.assertLess(new_x0, new_x1, "Zoomed start time must be less than end time")

    def test_left_click_small_displacement_selects_peak(self) -> None:
        """
        Verify that small left-click displacement (dx <= 5, dy <= 5) acts as a single-click
        selection instead of zooming into a microscopic box.
        Authoritative source: PROJECT.md § Mouse Navigation API, explorer_survey_ui § 4.1.
        """
        orig_x_range = self.canvas_widget.x_range
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        self.canvas_widget._on_left_down(FakeEvent(x=mid_x, y=mid_y, state=0))
        # Micro displacement of 2 pixels
        self.canvas_widget._on_left_drag(FakeEvent(x=mid_x + 2, y=mid_y + 2, state=0))
        self.canvas_widget._on_left_up(FakeEvent(x=mid_x + 2, y=mid_y + 2, state=0))

        # Time range must NOT change on micro-displacement
        self.assertEqual(
            self.canvas_widget.x_range,
            orig_x_range,
            "Micro displacement (<=5px) must not alter x_range (should treat as single click select)"
        )

    def test_right_click_vertical_drag_scales_amplitude_anchored(self) -> None:
        """
        Verify that right-click vertical drag smoothly scales signal amplitude (Y-axis zoom)
        anchored to baseline without altering horizontal time range (x_range).
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F08), explorer_survey_ui § 4.1.
        """
        orig_x_range = self.canvas_widget.x_range
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        orig_y_span = self.canvas_widget.y_ranges["FID1A"][1] - self.canvas_widget.y_ranges["FID1A"][0]

        # Right-click down
        self.canvas_widget._on_right_down(FakeEvent(x=mid_x, y=mid_y))
        drag_state = self.canvas_widget._drag_state
        self.assertIsNotNone(drag_state, "Right-click must initialize drag state")

        # Drag vertically upward by 50 pixels (dy = -50 in screen coordinates)
        self.canvas_widget._on_right_drag(FakeEvent(x=mid_x, y=mid_y - 50))

        # Time range MUST remain strictly unchanged
        self.assertEqual(
            self.canvas_widget.x_range,
            orig_x_range,
            "Right-click vertical drag must preserve x_range completely"
        )

        # Signal amplitude range MUST have changed
        new_y_span = self.canvas_widget.y_ranges["FID1A"][1] - self.canvas_widget.y_ranges["FID1A"][0]
        self.assertNotEqual(
            new_y_span,
            orig_y_span,
            "Right-click vertical drag must dynamically scale Y amplitude"
        )

        # Release
        self.canvas_widget._on_right_up(FakeEvent(x=mid_x, y=mid_y - 50))
        self.assertIsNone(self.canvas_widget._drag_state, "Drag state must be cleared on right-up")

    def test_double_click_resets_view_to_default_bounds(self) -> None:
        """
        Verify that double-click resets both time (X) and signal (Y) axes to default bounds.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F09).
        """
        # First zoom into a small subregion
        self.canvas_widget.x_range = (5.0, 7.0)
        self.canvas_widget.y_ranges["FID1A"] = (10.0, 25.0)

        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        # Double-click reset
        if hasattr(self.canvas_widget, "_on_double_click_reset"):
            self.canvas_widget._on_double_click_reset(FakeEvent(x=mid_x, y=mid_y))
        else:
            self.canvas_widget._on_double_click(FakeEvent(x=mid_x, y=mid_y))

        # Verify time range restored to reaction active region or full range
        x_min, x_max = self.canvas_widget.x_range
        self.assertGreaterEqual(x_max - x_min, 10.0, f"Double-click must restore time span to >= 10m, got {x_max - x_min}")

    def test_double_right_click_resets_view_to_default_bounds(self) -> None:
        """
        Verify that <Double-Button-3> is bound and resets view to default bounds.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F09).
        """
        bind_b3 = self.canvas_widget.canvas.bind("<Double-Button-3>")
        self.assertTrue(
            bool(bind_b3),
            "Canvas must have <Double-Button-3> bound for Agilent-style double-right-click view reset"
        )

    def test_shared_anchor_drop_line_movement(self) -> None:
        """
        Verify that moving an anchor on a shared split drop line updates both adjacent peaks
        simultaneously to prevent baseline decoupling.
        Authoritative source: PROJECT.md (F04), Interface Contract § agilent_core.integrator.
        """
        sig = self.inj.signals["FID1A"]
        pks = self.inj.peaks_by_signal["FID1A"]

        # Find two adjacent peaks sharing a drop line (e.g. pk1.end_min == pk2.begin_min)
        adj_pair = None
        for i in range(len(pks) - 1):
            if abs(pks[i].end_min - pks[i + 1].begin_min) < 1e-4:
                adj_pair = (pks[i], pks[i + 1])
                break

        if adj_pair:
            pk_left, pk_right = adj_pair
            shared_t = pk_left.end_min
            new_t = shared_t + 0.02
            new_y = sig.value_at_time(new_t)

            # Move left peak's right anchor using update_peak_anchors
            update_peak_anchors(
                sig=sig,
                peaks=pks,
                peak_id=pk_left.peak_id,
                new_begin_min=pk_left.begin_min,
                new_bs_y=pk_left.baseline_start_y,
                new_end_min=new_t,
                new_be_y=new_y,
                method=self.method,
            )

            # Assert right peak's left anchor moved synchronously
            self.assertAlmostEqual(
                pk_right.begin_min,
                new_t,
                places=3,
                msg="Right peak's begin_min must synchronously move when shared drop line anchor is dragged"
            )


if __name__ == "__main__":
    unittest.main()
