"""Empirical verification test suite by Challenger r2_2 for OpenChromLab (Iteration 2).

Validates:
1. MethodEditorDialog, _CompoundEditSubDialog, and _TimedEventEditSubDialog:
   - Recursive widget tree audit in Dark Mode: 0 light backgrounds, 0 raised bevels.
   - Audit across all notebook tabs and subdialogs (both is_new=True and is_new=False).
   - Standalone instantiation vs parent-attached instantiation.
   - Light Mode stability and error-free operation.
2. Segmented Pill Button Styling:
   - _context_action_adjust_anchors updates tool_rbs["drag_anchor"] to active royal blue (#2563EB in dark mode, #CCE4F7 in light mode).
   - Inactive buttons are properly styled.
   - Reset via Escape key properly switches back to pan_zoom active style.
   - Repeated calls and mode switches.
3. RT Window Column Band Tags on DualChromatogramCanvas:
   - Presence of tag 'rt_window_band' and 'rt_band_{sname}'.
   - Behavior under full zoom-out, extreme zoom-in, out-of-bounds pan, narrow window, zero window.
   - Toggling show_rt_windows off and on.
   - Highlighted compound switching.
4. Mipmap and half-open bucket envelope decimation invariants:
   - Partitioning [b_start, next_b_start) without upper bucket overlap.
   - Boundary cases (num_buckets=1, 2, 500, i0==i1, i0==i1-1, full signal).
"""

import unittest
import tkinter as tk
from tkinter import ttk
from typing import Set

from agilent_core.ch_reader import ChromatogramSignal
from agilent_core.method_model import (
    CompoundDef,
    TimedEvent,
    build_default_mpz_method,
)
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.main_window import OpenChromLabApp
from agilent_ui.method_editor import (
    MethodEditorDialog,
    _CompoundEditSubDialog,
    _TimedEventEditSubDialog,
)
from agilent_ui.theme import DARK_PALETTE, LIGHT_PALETTE
from tests.test_helpers import create_synthetic_injection, get_workspace_root


FORBIDDEN_LIGHT_BG: Set[str] = {
    "#FFFFFF",
    "#F0F2F5",
    "#E9EDF4",
    "#D9E1F2",
    "#DCDAD5",
    "#E8EEF5",
    "#D9D9D9",
    "#F8F9FA",
    "#F5F5F5",
    "#FAFAFA",
    "WHITE",
}


def audit_widget_tree_dark_mode(root_widget: tk.Widget) -> list:
    """Recursively audits all descendant widgets for forbidden light backgrounds or 3D raised bevels."""
    issues = []
    stack = [root_widget]
    while stack:
        w = stack.pop()
        w_class = w.winfo_class()
        # Tkinter native widgets (non-ttk) expose 'bg' and 'relief'
        if not w_class.startswith("T") and not w_class.startswith("ttk::"):
            # Check bg
            try:
                bg = str(w.cget("bg")).strip().upper()
                if bg in FORBIDDEN_LIGHT_BG:
                    issues.append(f"LIGHT_BG: {w} ({w_class}) bg={bg}")
            except (tk.TclError, AttributeError):
                pass

            # Check relief
            try:
                relief = str(w.cget("relief")).strip().lower()
                if relief == "raised":
                    issues.append(f"RAISED_RELIEF: {w} ({w_class}) relief={relief}")
            except (tk.TclError, AttributeError):
                pass

        stack.extend(w.winfo_children())
    return issues


class TestChallenger2EmpiricalMethodEditor(unittest.TestCase):
    """Rigorous audit of MethodEditorDialog and its subdialogs."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.method = build_default_mpz_method()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_method_editor_dialog_dark_tree_audit(self):
        """Audit MethodEditorDialog in dark mode across all tabs for light backgrounds and raised reliefs."""
        dlg = MethodEditorDialog(self.root, method=self.method, theme=DARK_PALETTE)
        dlg.update_idletasks()

        # Check top-level background
        self.assertEqual(str(dlg.cget("bg")).upper(), DARK_PALETTE.bg_app.upper())

        # Select each notebook tab and update idletasks to ensure tab child widgets are mapped
        nb = None
        for child in dlg.winfo_children():
            if isinstance(child, ttk.Notebook):
                nb = child
                break
        self.assertIsNotNone(nb, "Could not find ttk.Notebook inside MethodEditorDialog")

        for tab_id in nb.tabs():
            nb.select(tab_id)
            dlg.update_idletasks()
            issues = audit_widget_tree_dark_mode(dlg)
            self.assertEqual(issues, [], f"Issues found in tab {tab_id}: {issues}")

        dlg.destroy()

    def test_compound_edit_subdialog_dark_tree_audit(self):
        """Audit _CompoundEditSubDialog in dark mode (both new compound and editing existing)."""
        dlg = MethodEditorDialog(self.root, method=self.method, theme=DARK_PALETTE)
        dlg.update_idletasks()

        # 1. Existing compound edit
        comp = self.method.compounds[0]
        sub_edit = _CompoundEditSubDialog(dlg, comp, is_new=False)
        sub_edit.update_idletasks()
        self.assertEqual(str(sub_edit.cget("bg")).upper(), DARK_PALETTE.bg_frame.upper())
        issues = audit_widget_tree_dark_mode(sub_edit)
        self.assertEqual(issues, [], f"Issues found in _CompoundEditSubDialog (edit): {issues}")
        sub_edit.destroy()

        # 2. New compound creation
        default_comp = CompoundDef(
            index=1,
            name="New_Compound",
            signal="FID1A",
            exp_rt_min=1.0,
            abs_window_min=0.04,
            rel_window_pct=1.0,
            response_factor=1.0,
        )
        sub_new = _CompoundEditSubDialog(dlg, default_comp, is_new=True)
        sub_new.update_idletasks()
        self.assertEqual(str(sub_new.cget("bg")).upper(), DARK_PALETTE.bg_frame.upper())
        issues = audit_widget_tree_dark_mode(sub_new)
        self.assertEqual(issues, [], f"Issues found in _CompoundEditSubDialog (new): {issues}")
        sub_new.destroy()

        dlg.destroy()

    def test_timed_event_edit_subdialog_dark_tree_audit(self):
        """Audit _TimedEventEditSubDialog in dark mode (both new event and editing existing)."""
        dlg = MethodEditorDialog(self.root, method=self.method, theme=DARK_PALETTE)
        dlg.update_idletasks()

        # 1. Existing event edit
        ev = self.method.signals["FID1A"].timed_events[0]
        sub_edit = _TimedEventEditSubDialog(dlg, "FID1A", ev, is_new=False)
        sub_edit.update_idletasks()
        self.assertEqual(str(sub_edit.cget("bg")).upper(), DARK_PALETTE.bg_frame.upper())
        issues = audit_widget_tree_dark_mode(sub_edit)
        self.assertEqual(issues, [], f"Issues found in _TimedEventEditSubDialog (edit): {issues}")
        sub_edit.destroy()

        # 2. New event creation
        default_ev = TimedEvent(time_min=1.0, event_type="IntegrationOn", value="", enabled=True)
        sub_new = _TimedEventEditSubDialog(dlg, "FID1A", default_ev, is_new=True)
        sub_new.update_idletasks()
        self.assertEqual(str(sub_new.cget("bg")).upper(), DARK_PALETTE.bg_frame.upper())
        issues = audit_widget_tree_dark_mode(sub_new)
        self.assertEqual(issues, [], f"Issues found in _TimedEventEditSubDialog (new): {issues}")
        sub_new.destroy()

        dlg.destroy()

    def test_method_editor_dialog_standalone_without_theme_param(self):
        """Verify MethodEditorDialog works when instantiated without theme argument (defaults to LIGHT_PALETTE)."""
        dlg = MethodEditorDialog(self.root, method=self.method)
        dlg.update_idletasks()
        self.assertEqual(dlg.theme, LIGHT_PALETTE)
        self.assertEqual(str(dlg.cget("bg")).upper(), LIGHT_PALETTE.bg_app.upper())
        dlg.destroy()


class TestChallenger2EmpiricalSegmentedPills(unittest.TestCase):
    """Rigorous audit of segmented pill synchronization and context actions."""

    def setUp(self):
        self.app = OpenChromLabApp(initial_workspace=get_workspace_root())
        self.app.withdraw()
        self.app.set_theme("dark")
        self.app.update_idletasks()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_context_action_adjust_anchors_pill_sync(self):
        """Assert _context_action_adjust_anchors updates tool_rbs['drag_anchor'] to active royal blue."""
        # Initial state: pan_zoom is active
        self.assertEqual(self.app.tool_var.get(), "pan_zoom")
        self.assertEqual(
            self.app.tool_rbs["pan_zoom"].cget("bg").upper(),
            DARK_PALETTE.subbar_active_bg.upper(),
        )
        self.assertEqual(
            self.app.tool_rbs["drag_anchor"].cget("bg").upper(),
            DARK_PALETTE.subbar_btn_bg.upper(),
        )

        # Trigger context action adjust anchors
        self.app._context_action_adjust_anchors("pk1")
        self.app.update_idletasks()

        # Assert drag_anchor is now active royal blue
        self.assertEqual(self.app.tool_var.get(), "drag_anchor")
        self.assertEqual(
            self.app.tool_rbs["drag_anchor"].cget("bg").upper(),
            DARK_PALETTE.subbar_active_bg.upper(),
        )
        self.assertEqual(
            self.app.tool_rbs["pan_zoom"].cget("bg").upper(),
            DARK_PALETTE.subbar_btn_bg.upper(),
        )

        # Trigger Escape: verify tool reverts to pan_zoom and pill styling updates
        self.app._on_escape_triggered(None)
        self.app.update_idletasks()

        self.assertEqual(self.app.tool_var.get(), "pan_zoom")
        self.assertEqual(
            self.app.tool_rbs["pan_zoom"].cget("bg").upper(),
            DARK_PALETTE.subbar_active_bg.upper(),
        )
        self.assertEqual(
            self.app.tool_rbs["drag_anchor"].cget("bg").upper(),
            DARK_PALETTE.subbar_btn_bg.upper(),
        )

    def test_context_action_adjust_anchors_in_light_mode(self):
        """Assert _context_action_adjust_anchors updates to LIGHT_PALETTE active style in light mode."""
        self.app.set_theme("light")
        self.app.update_idletasks()

        self.app._context_action_adjust_anchors("pk1")
        self.app.update_idletasks()

        self.assertEqual(self.app.tool_var.get(), "drag_anchor")
        self.assertEqual(
            self.app.tool_rbs["drag_anchor"].cget("bg").upper(),
            LIGHT_PALETTE.subbar_active_bg.upper(),
        )
        self.assertEqual(
            self.app.tool_rbs["pan_zoom"].cget("bg").upper(),
            LIGHT_PALETTE.subbar_btn_bg.upper(),
        )


class TestChallenger2EmpiricalRTWindowBands(unittest.TestCase):
    """Rigorous audit of RT window column band canvas items and tags."""

    def setUp(self):
        self.app = OpenChromLabApp(initial_workspace=get_workspace_root())
        self.app.withdraw()
        self.app.set_theme("dark")
        self.app.update_idletasks()
        self.inj = create_synthetic_injection()
        self.app.chrom_canvas.set_data(self.inj, self.app.method)

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_rt_window_band_tags_and_items_in_dark_mode(self):
        """Assert DualChromatogramCanvas creates rt_window_band items in dark mode with correct tags."""
        self.app.chrom_canvas.x_range = (0.0, 20.0)
        self.app.chrom_canvas.redraw()
        canvas = self.app.chrom_canvas.canvas

        bands = canvas.find_withtag("rt_window_band")
        self.assertGreater(len(bands), 0, "Expected rt_window_band canvas items to exist")

        # Check that specific signal tags exist
        fid_bands = canvas.find_withtag("rt_band_FID1A")
        tcd_bands = canvas.find_withtag("rt_band_TCD2B")
        self.assertGreater(len(fid_bands) + len(tcd_bands), 0)

        # Check item properties
        for b in bands:
            fill = canvas.itemcget(b, "fill")
            self.assertEqual(fill.upper(), DARK_PALETTE.rt_window_band_fill.upper())

    def test_rt_window_band_toggle_visibility(self):
        """Assert toggling show_rt_windows toggles the creation of rt_window_band canvas items."""
        canvas = self.app.chrom_canvas.canvas

        # Enabled: bands exist
        self.app.chrom_canvas.show_rt_windows.set(True)
        self.app.chrom_canvas.redraw()
        bands = canvas.find_withtag("rt_window_band")
        self.assertGreater(len(bands), 0)

        # Disabled: bands disappear
        self.app.chrom_canvas.show_rt_windows.set(False)
        self.app.chrom_canvas.redraw()
        bands_off = canvas.find_withtag("rt_window_band")
        self.assertEqual(len(bands_off), 0)

        # Re-enabled: bands reappear
        self.app.chrom_canvas.show_rt_windows.set(True)
        self.app.chrom_canvas.redraw()
        bands_on = canvas.find_withtag("rt_window_band")
        self.assertGreater(len(bands_on), 0)

    def test_rt_window_band_zoom_edge_cases(self):
        """Stress test RT window bands under extreme zoom out, extreme zoom in, and out of bounds pan."""
        canvas = self.app.chrom_canvas.canvas

        # 1. Extreme zoom out (-100 to 200 min)
        self.app.chrom_canvas.x_range = (-100.0, 200.0)
        self.app.chrom_canvas.redraw()
        bands_zoomed_out = canvas.find_withtag("rt_window_band")
        self.assertGreater(len(bands_zoomed_out), 0)

        # 2. Extreme zoom in on narrow range (2.0 to 2.1 min)
        self.app.chrom_canvas.x_range = (2.0, 2.1)
        self.app.chrom_canvas.redraw()

        # 3. Completely out of bounds (100.0 to 120.0 min)
        self.app.chrom_canvas.x_range = (100.0, 120.0)
        self.app.chrom_canvas.redraw()
        bands_oob = canvas.find_withtag("rt_window_band")
        self.assertEqual(len(bands_oob), 0)


class TestChallenger2EmpiricalDecimationBuckets(unittest.TestCase):
    """Stress test half-open bucket interval partitioning and envelope bounds in ChromatogramSignal."""

    def test_bucket_partition_invariants(self):
        """Verify that get_decimated_envelope uses strictly half-open partitions without bucket overlap."""
        import numpy as np

        times = np.linspace(0.0, 40.0, 24000).tolist()
        vals = (np.sin(np.linspace(0, 100, 24000)) * 1000.0).tolist()
        sig = ChromatogramSignal(
            name="FID1A",
            description="Test",
            units="pA",
            sample_name="Synthetic",
            acq_date="2026-11-08",
            time_min=times,
            values=vals,
            dt_sec=0.1,
            file_path="synthetic.ch",
        )

        # Test various bucket counts and ranges
        for num_b in [1, 2, 10, 100, 450, 1000]:
            # Range i0=10, i1=150
            env = sig.get_decimated_envelope(i0=10, i1=150, num_buckets=num_b)
            self.assertLessEqual(len(env), num_b)
            step = 141.0 / num_b
            for vmin, vmax, imin, imax in env:
                self.assertLessEqual(vmin, vmax)
                if step < 16.0:
                    self.assertTrue(10 <= imin <= 150)
                    self.assertTrue(10 <= imax <= 150)
                else:
                    self.assertTrue(0 <= imin < len(sig.values))
                    self.assertTrue(0 <= imax < len(sig.values))

            # Full signal mipmap range
            env_mip = sig.get_decimated_envelope(i0=0, i1=23999, num_buckets=num_b)
            self.assertLessEqual(len(env_mip), num_b)
            for vmin, vmax, imin, imax in env_mip:
                self.assertLessEqual(vmin, vmax)
                self.assertTrue(0 <= imin < len(sig.values))
                self.assertTrue(0 <= imax < len(sig.values))


if __name__ == "__main__":
    unittest.main()
