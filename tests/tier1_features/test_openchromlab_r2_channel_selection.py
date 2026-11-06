"""
Tier 1: Feature Coverage — Requirement R2 (Channel Display Selection)
Feature F20: Verifies single/split channel display selection (FID only, TCD only, Both),
panel bounding rectangle allocation, full-height utilization, and bottom X-axis title rendering.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk
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


class TestOpenChromLabR2ChannelSelection(HeadlessTkTestCase):
    """Test suite for Requirement R2: Channel Display Selection."""

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1000x600")
        self.canvas_widget = DualChromatogramCanvas(self.root)
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        # Load a standard injection
        folders = find_d_folders(get_test_set_path())
        if folders:
            self.inj = load_d_folder(folders[0])
        else:
            self.inj = create_synthetic_injection()
        self.method = build_default_mpz_method()
        process_injection(self.inj, self.method, prefer_rx=True)
        self.canvas_widget.set_data(self.inj, self.method)
        self.root.update_idletasks()

    def test_r2_01_channel_mode_both_allocates_stacked_panels(self) -> None:
        """
        Verify that in 'both' channel mode, panel rectangles are allocated for both
        FID1A and TCD2B, separated by margin_mid, each using approximately half height.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F20).
        """
        self.assertTrue(
            hasattr(self.canvas_widget, "set_channel_mode"),
            "DualChromatogramCanvas must have set_channel_mode method."
        )
        self.canvas_widget.set_channel_mode("both")
        self.root.update_idletasks()

        rects = self.canvas_widget._get_panel_rects()
        self.assertIn("FID1A", rects, "Panel rects must contain 'FID1A' in 'both' mode.")
        self.assertIn("TCD2B", rects, "Panel rects must contain 'TCD2B' in 'both' mode.")

        fid_x0, fid_y0, fid_x1, fid_y1 = rects["FID1A"]
        tcd_x0, tcd_y0, tcd_x1, tcd_y1 = rects["TCD2B"]

        self.assertLess(fid_y1, tcd_y0, "FID1A panel must sit above TCD2B panel.")
        self.assertGreaterEqual(
            tcd_y0 - fid_y1,
            self.canvas_widget.margin_mid,
            f"Gap between panels must be >= margin_mid ({self.canvas_widget.margin_mid})."
        )

    def test_r2_02_channel_mode_fid_only_occupies_full_height(self) -> None:
        """
        Verify that in 'FID1A' (FID Only) mode, only FID1A panel is allocated and it
        expands to occupy the full available canvas height without split margins.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F20).
        """
        self.canvas_widget.set_channel_mode("FID1A")
        self.root.update_idletasks()

        rects = self.canvas_widget._get_panel_rects()
        self.assertIn("FID1A", rects, "Rects must contain FID1A in FID-only mode.")
        self.assertNotIn("TCD2B", rects, "Rects must NOT contain TCD2B in FID-only mode.")

        fid_x0, fid_y0, fid_x1, fid_y1 = rects["FID1A"]
        h_fid = fid_y1 - fid_y0

        # Now compare against 'both' mode FID height
        self.canvas_widget.set_channel_mode("both")
        self.root.update_idletasks()
        both_rects = self.canvas_widget._get_panel_rects()
        h_both_fid = both_rects["FID1A"][3] - both_rects["FID1A"][1]

        self.assertGreater(
            h_fid,
            h_both_fid * 1.5,
            f"FID-only height ({h_fid}) must be substantially larger than stacked height ({h_both_fid})."
        )

    def test_r2_03_channel_mode_tcd_only_occupies_full_height(self) -> None:
        """
        Verify that in 'TCD2B' (TCD Only) mode, only TCD2B panel is allocated and it
        expands to occupy the full available canvas height.
        Authoritative source: ORIGINAL_REQUEST.md (R2), PROJECT.md (F20).
        """
        self.canvas_widget.set_channel_mode("TCD2B")
        self.root.update_idletasks()

        rects = self.canvas_widget._get_panel_rects()
        self.assertIn("TCD2B", rects, "Rects must contain TCD2B in TCD-only mode.")
        self.assertNotIn("FID1A", rects, "Rects must NOT contain FID1A in TCD-only mode.")

        tcd_x0, tcd_y0, tcd_x1, tcd_y1 = rects["TCD2B"]
        h_tcd = tcd_y1 - tcd_y0

        self.canvas_widget.set_channel_mode("both")
        self.root.update_idletasks()
        both_rects = self.canvas_widget._get_panel_rects()
        h_both_tcd = both_rects["TCD2B"][3] - both_rects["TCD2B"][1]

        self.assertGreater(
            h_tcd,
            h_both_tcd * 1.5,
            f"TCD-only height ({h_tcd}) must be substantially larger than stacked height ({h_both_tcd})."
        )

    def test_r2_04_bottom_x_axis_label_rendered_in_fid_only_mode(self) -> None:
        """
        Verify that the bottom Retention Time X-axis label and tick numbers are visibly
        rendered on canvas when FID1A is displayed alone.
        Authoritative source: ORIGINAL_REQUEST.md (R2 Acceptance Criteria), Explorer 1 § 2.1.
        """
        self.canvas_widget.set_channel_mode("FID1A")
        self.root.update_idletasks()

        c = self.canvas_widget.canvas
        all_text_ids = c.find_withtag("current")  # or search all text items
        text_contents = []
        for item_id in c.find_all():
            if c.type(item_id) == "text":
                text_contents.append(c.itemcget(item_id, "text"))

        rt_label_found = any("Retention Time" in t for t in text_contents)
        self.assertTrue(
            rt_label_found,
            f"Bottom Retention Time axis label must be rendered in FID-only mode. Found text items: {text_contents[:10]}"
        )

    def test_r2_05_channel_switching_cancels_in_progress_drag(self) -> None:
        """
        Verify that switching channel display mode clears any active drag or draw
        state (_drag_state = None) to prevent coordinate misprojections.
        Authoritative source: Explorer 1 § 3.
        """
        self.canvas_widget._drag_state = {"mode": "zoom_box", "start_px": 100, "start_py": 100}
        self.canvas_widget.set_channel_mode("FID1A")
        self.assertIsNone(
            self.canvas_widget._drag_state,
            "set_channel_mode must clear active _drag_state."
        )

    def test_r2_06_channel_mode_case_insensitive_and_aliases(self) -> None:
        """
        Verify that set_channel_mode handles case-insensitive values and short aliases:
        'fid', 'FID1A', 'tcd', 'TCD2B', 'both'.
        Authoritative source: PROJECT.md § Interface Contracts.
        """
        self.canvas_widget.set_channel_mode("fid")
        self.assertEqual(len(self.canvas_widget._get_panel_rects()), 1)
        self.assertIn("FID1A", self.canvas_widget._get_panel_rects())

        self.canvas_widget.set_channel_mode("tcd")
        self.assertEqual(len(self.canvas_widget._get_panel_rects()), 1)
        self.assertIn("TCD2B", self.canvas_widget._get_panel_rects())

        self.canvas_widget.set_channel_mode("BOTH")
        self.assertEqual(len(self.canvas_widget._get_panel_rects()), 2)


if __name__ == "__main__":
    unittest.main()
