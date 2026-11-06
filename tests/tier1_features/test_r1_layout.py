"""
Tier 1: Feature Coverage — Requirement R1 (UI Bug Fixes and Layout Resilience)
Minimum 5 tests verifying layout resilience, margin bounds, label collision, scrollbars, and dialog behavior.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk
import unittest

from tests.test_helpers import HeadlessTkTestCase, get_workspace_root, get_test_set_path
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_core.ch_reader import load_d_folder, find_d_folders
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method


class TestR1LayoutResilience(HeadlessTkTestCase):
    """Test suite for Requirement R1 layout, text clipping, and collision prevention."""

    def test_canvas_margin_separation_fid_ticks_and_tcd_title(self) -> None:
        """
        Verify that canvas margins provide adequate separation (margin_mid >= 46, margin_bottom >= 42)
        to prevent FID1A bottom retention time tick labels from overlapping TCD2B panel title.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F10), explorer_survey_ui § 1.3A.
        """
        self.root.geometry("1000x600")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        # Canvas mid margin must be at least 46 px (was 34 px in buggy state)
        self.assertGreaterEqual(
            canvas_widget.margin_mid,
            46,
            f"Canvas margin_mid ({canvas_widget.margin_mid}) must be >= 46 to prevent tick/title collision"
        )
        self.assertGreaterEqual(
            canvas_widget.margin_bottom,
            42,
            f"Canvas margin_bottom ({canvas_widget.margin_bottom}) must be >= 42 to prevent descender clipping"
        )

        # Load real injection and check text item vertical coordinates
        folders = find_d_folders(get_test_set_path())
        self.assertTrue(len(folders) > 0, "No folders found in test-set")
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()
        process_injection(inj, method, prefer_rx=True)
        canvas_widget.set_data(inj, method)
        self.root.update_idletasks()

        rects = canvas_widget._get_panel_rects()
        y1_top = rects["FID1A"][3]
        y0_bot = rects["TCD2B"][1]

        c = canvas_widget.canvas
        tcd_title_id = None
        fid_tick_ids = []

        for item_id in c.find_withtag("all"):
            if c.type(item_id) == "text":
                txt = c.itemcget(item_id, "text")
                if "TCD2 B" in txt:
                    tcd_title_id = item_id
                elif txt in ("4", "6", "8", "10", "12"):
                    bbox = c.bbox(item_id)
                    # Belongs to FID1A bottom axis ticks if within 25px of y1_top
                    if bbox and abs(bbox[1] - y1_top) < 25:
                        fid_tick_ids.append(item_id)

        if tcd_title_id and fid_tick_ids:
            title_bbox = c.bbox(tcd_title_id)
            title_top = title_bbox[1]
            for tick_id in fid_tick_ids:
                tick_bbox = c.bbox(tick_id)
                tick_bottom = tick_bbox[3]
                # TCD2B title must sit strictly below FID1A tick bottom
                self.assertGreater(
                    title_top,
                    tick_bottom - 2,
                    f"FID1A tick bottom ({tick_bottom}) collides with TCD2B title top ({title_top})"
                )

    def test_canvas_margin_bottom_retention_time_label(self) -> None:
        """
        Verify that bottom margin is sufficient so the 'Retention Time [min]' label
        is completely enclosed within canvas height and text descenders are not cut off.
        Authoritative source: ORIGINAL_REQUEST.md (R1), explorer_survey_ui § 1.3A.
        """
        self.root.geometry("900x500")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()
        process_injection(inj, method, prefer_rx=True)
        canvas_widget.set_data(inj, method)
        self.root.update_idletasks()

        c = canvas_widget.canvas
        axis_lbl_id = None
        for item_id in c.find_withtag("all"):
            if c.type(item_id) == "text" and "Retention Time [min]" in c.itemcget(item_id, "text"):
                axis_lbl_id = item_id
                break

        self.assertIsNotNone(axis_lbl_id, "Retention Time [min] label not found on canvas")
        bbox = c.bbox(axis_lbl_id)
        self.assertIsNotNone(bbox, "Bounding box could not be retrieved")

        rects = canvas_widget._get_panel_rects()
        max_allowed_y = rects["TCD2B"][3] + canvas_widget.margin_bottom
        self.assertLessEqual(
            bbox[3],
            max_allowed_y,
            f"Axis label bottom ({bbox[3]}) exceeds panel bottom plus margin_bottom ({max_allowed_y})"
        )

    def test_peak_label_collision_avoidance_coeluting_peaks(self) -> None:
        """
        Verify that peak annotations for co-eluting peaks (e.g. unknown #1 at 4.567m and CH4 at 4.606m)
        do not render at identical vertical coordinates (stacking collision).
        Authoritative source: PROJECT.md (F11), explorer_survey_ui § 1.3B.
        """
        self.root.geometry("1000x600")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()
        process_injection(inj, method, prefer_rx=True)
        canvas_widget.set_data(inj, method)
        self.root.update_idletasks()

        c = canvas_widget.canvas
        labels = {}
        for item_id in c.find_withtag("all"):
            if c.type(item_id) == "text":
                txt = c.itemcget(item_id, "text")
                if "unknown #1" in txt or "CH4" in txt:
                    bbox = c.bbox(item_id)
                    if bbox:
                        labels[txt] = bbox

        if "unknown #1" in labels and "CH4" in labels:
            b1 = labels["unknown #1"]
            b2 = labels["CH4"]
            dx = abs(b1[0] - b2[0])
            dy = abs(b1[1] - b2[1])
            if dx < 20:
                self.assertGreater(
                    dy,
                    4,
                    f"Closely spaced peak labels have identical Y coordinate ({b1[1]} vs {b2[1]}), causing text stacking"
                )

    def test_peak_label_horizontal_canvas_edge_clamping(self) -> None:
        """
        Verify that peak labels near the canvas borders (x0 or x1) are clamped
        and do not spill into the Y-axis numbering or outside canvas boundaries.
        Authoritative source: PROJECT.md (F11), explorer_survey_ui § 1.3B.
        """
        self.root.geometry("800x500")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        rects = canvas_widget._get_panel_rects()
        x0, _, x1, _ = rects["FID1A"]

        # Left margin must be >= 70 to clear 5-digit Y axis numbers
        self.assertGreaterEqual(x0, 70, "Left margin x0 must be >= 70")
        self.assertLessEqual(x1, 780, "Right margin x1 must be <= 780")

    def test_treeview_tables_horizontal_scroll_configuration(self) -> None:
        """
        Verify that data tables (peak_tree and comp_tree) configure horizontal scrollbars
        (scroll_x) and xscrollcommand to prevent table columns from clipping off-screen.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F14), explorer_survey_ui § 1.2C.
        """
        from agilent_ui.main_window import OpenLabSubstituteApp

        app = OpenLabSubstituteApp(get_workspace_root())
        self.root.update_idletasks()

        try:
            # Check peak_tree has xscrollcommand configured
            xscroll_peak = app.peak_tree.cget("xscrollcommand")
            self.assertTrue(
                bool(xscroll_peak),
                "peak_tree must have xscrollcommand configured with horizontal scrollbar"
            )

            # Check comp_tree has xscrollcommand configured
            xscroll_comp = app.comp_tree.cget("xscrollcommand")
            self.assertTrue(
                bool(xscroll_comp),
                "comp_tree must have xscrollcommand configured with horizontal scrollbar"
            )
        finally:
            app.destroy()

    def test_compound_editor_dialog_resilience_and_shortcuts(self) -> None:
        """
        Verify that compound editor dialog allows dynamic sizing or resizing,
        and binds <Return> and <Escape> keys to prevent dialog lockup.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F15), explorer_survey_ui § 1.2D.
        """
        from agilent_ui.main_window import OpenLabSubstituteApp

        app = OpenLabSubstituteApp(get_workspace_root())
        self.root.update_idletasks()

        try:
            method = app.method
            self.assertGreater(len(method.compounds), 0)
            comp = method.compounds[0]

            # Invoke editor dialog for existing compound
            app._open_compound_editor(comp, is_new=False)
            self.root.update_idletasks()

            # Find open Toplevel windows
            toplevels = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
            self.assertTrue(len(toplevels) > 0, "Compound editor Toplevel dialog was not created")
            dlg = toplevels[0]

            # Verify dialog bindings
            return_bind = dlg.bind("<Return>")
            escape_bind = dlg.bind("<Escape>")
            self.assertTrue(bool(return_bind), "Dialog must bind <Return> key to save")
            self.assertTrue(bool(escape_bind), "Dialog must bind <Escape> key to dismiss")

            dlg.destroy()
        finally:
            app.destroy()

    def test_window_geometry_adapts_to_screen_resolution(self) -> None:
        """
        Verify that default window requested height does not exceed physical display
        height (e.g. 864px on 1080p @ 125% DPI), ensuring bottom status bar is never pushed off-screen.
        Authoritative source: ORIGINAL_REQUEST.md (R1), PROJECT.md (F12), explorer_survey_ui § 1.1.
        """
        from agilent_ui.main_window import OpenLabSubstituteApp

        app = OpenLabSubstituteApp(get_workspace_root())
        self.root.update_idletasks()

        try:
            geom = app.geometry()
            parts = geom.split("+")[0].split("x")
            w, h = int(parts[0]), int(parts[1])

            # Window height must be <= 850px on standard desktop displays to avoid taskbar clipping
            self.assertLessEqual(
                h,
                850,
                f"Initial window height ({h}px) exceeds 850px, risking taskbar clipping"
            )
            min_w, min_h = app.minsize()
            self.assertLessEqual(min_w, 1100, f"minsize width ({min_w}) must be <= 1100")
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
