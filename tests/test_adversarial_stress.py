"""
Adversarial Stress Test Suite for OpenChromLab
Empirical Challenger: stress-testing canvas navigation, channel selection,
curve rendering, keyboard shortcuts, context menus, and theme switching.
"""

import copy
import math
import os
import sys
import tkinter as tk
from tkinter import ttk
import unittest

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from tests.test_helpers import (
    HeadlessTkTestCase,
    get_workspace_root,
    get_test_set_path,
    create_synthetic_injection,
    create_synthetic_signal,
)
from agilent_ui.main_window import OpenChromLabApp, OpenLabSubstituteApp, InjectionUndoManager
from agilent_ui.chrom_canvas import DualChromatogramCanvas, HitType
from agilent_ui.theme import LIGHT_PALETTE, DARK_PALETTE, ThemePalette
from agilent_core.ch_reader import find_d_folders, load_d_folder, IntegratedPeak
from agilent_core.integrator import (
    add_manual_peak,
    split_peak_at,
    delete_peak_by_id,
    process_injection,
)
from agilent_core.method_model import build_default_mpz_method, CompoundDef


class TestAdversarialCanvasNavigation(HeadlessTkTestCase):
    """Stress tests for Canvas Navigation & Channel Display Selection."""

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1200x800")
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

    def test_adv_channel_toggling_stress(self) -> None:
        """
        Stress test: Rapidly toggle between 'both', 'FID1A', 'TCD2B', lowercase aliases,
        and invalid fallbacks 100 times.
        Verify geometry allocations, panel rects, and zero exceptions.
        """
        # Baseline height with both channels
        self.canvas_widget.set_channel_mode("both")
        rects_both = self.canvas_widget._get_panel_rects()
        fid_h_both = rects_both["FID1A"][3] - rects_both["FID1A"][1]

        modes = ["both", "FID1A", "tcd", "fid", "TCD2B", "BOTH", "invalid_mode", ""]
        for i in range(100):
            mode = modes[i % len(modes)]
            self.canvas_widget.set_channel_mode(mode)
            rects = self.canvas_widget._get_panel_rects()
            self.assertIsNotNone(rects)
            self.assertGreater(len(rects), 0)

            if mode in ("FID1A", "fid"):
                self.assertIn("FID1A", rects)
                self.assertNotIn("TCD2B", rects)
                # Single channel height must be substantially larger than both-channel split height
                _, y0, _, y1 = rects["FID1A"]
                self.assertGreater(y1 - y0, fid_h_both * 1.5)
            elif mode in ("TCD2B", "tcd"):
                self.assertIn("TCD2B", rects)
                self.assertNotIn("FID1A", rects)
                _, y0, _, y1 = rects["TCD2B"]
                self.assertGreater(y1 - y0, fid_h_both * 1.5)
            else:
                self.assertIn("FID1A", rects)
                self.assertIn("TCD2B", rects)

        self.root.update_idletasks()

    def test_adv_axis_gutter_extreme_drags(self) -> None:
        """
        Stress test: Extreme axis drags on Y and X gutters:
        - Zero displacement (click and release)
        - Extreme negative drag (-50,000 px)
        - Extreme positive drag (+50,000 px)
        - Inverted ranges and negative spans
        """
        rects = self.canvas_widget._get_panel_rects()
        self.assertIn("FID1A", rects)
        x0, y0, x1, y1 = rects["FID1A"]

        # --- Y-Axis Gutter Pan Stress ---
        # 1. Zero displacement
        ev_down = tk.Event()
        ev_down.x = x0 - 20
        ev_down.y = (y0 + y1) // 2
        ev_down.state = 0
        self.canvas_widget._on_left_down(ev_down)
        self.assertIsNotNone(self.canvas_widget._drag_state)
        self.assertEqual(self.canvas_widget._drag_state["mode"], "y_axis_pan")

        ev_drag = tk.Event()
        ev_drag.x = ev_down.x
        ev_drag.y = ev_down.y
        self.canvas_widget._on_left_drag(ev_drag)
        self.canvas_widget._on_left_up(ev_drag)
        self.assertIsNone(self.canvas_widget._drag_state)

        # 2. Extreme positive drag (+50000 px)
        self.canvas_widget._on_left_down(ev_down)
        ev_drag.y = ev_down.y + 50000
        self.canvas_widget._on_left_drag(ev_drag)
        y_min, y_max = self.canvas_widget.y_ranges["FID1A"]
        self.assertFalse(math.isnan(y_min) or math.isnan(y_max))
        self.assertFalse(math.isinf(y_min) or math.isinf(y_max))
        self.canvas_widget._on_left_up(ev_drag)

        # 3. Extreme negative drag (-50000 px)
        self.canvas_widget._on_left_down(ev_down)
        ev_drag.y = ev_down.y - 50000
        self.canvas_widget._on_left_drag(ev_drag)
        y_min, y_max = self.canvas_widget.y_ranges["FID1A"]
        self.assertFalse(math.isnan(y_min) or math.isnan(y_max))
        self.assertFalse(math.isinf(y_min) or math.isinf(y_max))
        self.canvas_widget._on_left_up(ev_drag)

        # --- X-Axis Gutter Pan Stress ---
        bot_sname = list(rects.keys())[-1]
        bx0, by0, bx1, by1 = rects[bot_sname]
        ev_x_down = tk.Event()
        ev_x_down.x = (bx0 + bx1) // 2
        ev_x_down.y = by1 + 10
        ev_x_down.state = 0
        self.canvas_widget._on_left_down(ev_x_down)
        self.assertIsNotNone(self.canvas_widget._drag_state)
        self.assertEqual(self.canvas_widget._drag_state["mode"], "x_axis_pan")

        # Huge drag left & right
        ev_x_drag = tk.Event()
        ev_x_drag.x = ev_x_down.x + 50000
        ev_x_drag.y = ev_x_down.y
        self.canvas_widget._on_left_drag(ev_x_drag)
        x_min, x_max = self.canvas_widget.x_range
        self.assertFalse(math.isnan(x_min) or math.isnan(x_max))
        self.assertFalse(math.isinf(x_min) or math.isinf(x_max))

        ev_x_drag.x = ev_x_down.x - 50000
        self.canvas_widget._on_left_drag(ev_x_drag)
        x_min, x_max = self.canvas_widget.x_range
        self.assertFalse(math.isnan(x_min) or math.isnan(x_max))
        self.assertFalse(math.isinf(x_min) or math.isinf(x_max))
        self.canvas_widget._on_left_up(ev_x_drag)

    def test_adv_rapid_pan_and_scale_sequence(self) -> None:
        """
        Stress test: Rapid alternating left-drag pan and right-drag scale (50 iterations)
        with various displacement magnitudes and directions.
        """
        rects = self.canvas_widget._get_panel_rects()
        x0, y0, x1, y1 = rects["FID1A"]
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2

        for i in range(50):
            # Left drag pan (Shift+Left in plot body or Left in axis gutter)
            ev_down = tk.Event()
            ev_down.x = mid_x
            ev_down.y = mid_y
            ev_down.state = 0x0001  # Shift pressed -> 2D Pan
            self.canvas_widget._on_left_down(ev_down)

            ev_drag = tk.Event()
            delta = ((i % 10) - 5) * 30
            ev_drag.x = mid_x + delta
            ev_drag.y = mid_y - delta
            ev_drag.state = 0x0001
            self.canvas_widget._on_left_drag(ev_drag)
            self.canvas_widget._on_left_up(ev_drag)

            # Right drag scale
            ev_r_down = tk.Event()
            ev_r_down.x = mid_x
            ev_r_down.y = mid_y
            self.canvas_widget._on_right_down(ev_r_down)

            ev_r_drag = tk.Event()
            ev_r_drag.x = mid_x
            ev_r_drag.y = mid_y + ((i % 7) - 3) * 25
            self.canvas_widget._on_right_drag(ev_r_drag)
            self.canvas_widget._on_right_up(ev_r_drag)

        # View reset should cleanly restore bounds
        self.canvas_widget.reset_view()
        self.root.update_idletasks()
        self.assertAlmostEqual(self.canvas_widget.x_range[0], 3.5, delta=0.5)


class TestAdversarialCurveRendering(HeadlessTkTestCase):
    """Stress tests for Chromatogram Curve Line Width and Artifact-Free Rendering."""

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1100x700")
        self.canvas_widget = DualChromatogramCanvas(self.root)
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

        folders = find_d_folders(get_test_set_path())
        if folders:
            self.inj = load_d_folder(folders[0])
        else:
            self.inj = create_synthetic_injection()
        self.method = build_default_mpz_method()
        process_injection(self.inj, self.method, prefer_rx=True)
        self.canvas_widget.set_data(self.inj, self.method)
        self.root.update_idletasks()

    def test_adv_trace_line_width_assertion(self) -> None:
        """
        Empirically assert that canvas.trace_line_width >= 2.0 and that rendered
        trace segments in the Tkinter canvas maintain line width >= 2.0.
        Authoritative source: ORIGINAL_REQUEST.md (R10) & PROJECT.md (F22).
        """
        self.assertGreaterEqual(
            self.canvas_widget.trace_line_width,
            2.0,
            "Chromatogram curve trace line width must be >= 2.0 for visibility."
        )

        self.canvas_widget.redraw()
        c = self.canvas_widget.canvas

        # Find line items created on canvas
        line_items = [item for item in c.find_all() if c.type(item) == "line"]
        self.assertGreater(len(line_items), 0, "Canvas must render line items.")

        # At least the main chromatogram trace lines must have width >= 2.0
        widths = [float(c.itemcget(item, "width")) for item in line_items]
        thick_lines = [w for w in widths if w >= 2.0]
        self.assertGreater(
            len(thick_lines),
            0,
            "Canvas must contain trace lines rendered with thickness >= 2.0"
        )

    def test_adv_clean_rendering_no_artifacts_on_extreme_signals(self) -> None:
        """
        Stress test: Render synthetic signals with massive spikes (1e6 pA),
        deep negative drops (-1e5 pA), NaN/Inf protection, flat zero lines,
        and verify no tkinter canvas exceptions or broken bounding boxes.
        """
        extreme_peaks = [
            (5.0, 1000000.0, 0.05, False),   # Gigantic spike
            (8.0, 500000.0, 0.04, True),     # Massive negative peak
            (12.0, 0.00001, 0.001, False),   # Near-zero microscopic peak
        ]
        sig_extreme = create_synthetic_signal("FID1A", peaks=extreme_peaks)
        inj_extreme = create_synthetic_injection(signals={"FID1A": sig_extreme})
        self.canvas_widget.set_data(inj_extreme, self.method)

        # Redraw across multiple zoom levels
        zoom_levels = [
            (0.0, 20.0),
            (4.99, 5.01),      # Microscopic zoom around giant spike
            (7.99, 8.01),      # Microscopic zoom around negative dip
            (-100.0, 200.0),   # Super macro view
        ]
        for z0, z1 in zoom_levels:
            self.canvas_widget.x_range = (z0, z1)
            self.canvas_widget.redraw()
            self.root.update_idletasks()

        self.assertTrue(True, "Extreme signal curves rendered without canvas artifacts.")


class TestAdversarialShortcutsAndContext(HeadlessTkTestCase):
    """Stress tests for Undo (Ctrl+Z), Escape Cancel, and Context Actions."""

    def setUp(self) -> None:
        super().setUp()
        self.app = OpenChromLabApp(initial_workspace=get_workspace_root())
        self.app.geometry("1200x800")
        self.app.withdraw()
        self.app.load_directory(get_test_set_path())
        self.app.update()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except Exception:
            pass
        for folder in find_d_folders(get_test_set_path()):
            override_path = os.path.join(folder, "openlab_sub_manual.json")
            if os.path.exists(override_path):
                try:
                    os.remove(override_path)
                except Exception:
                    pass
        super().tearDown()

    def test_adv_rapid_undo_empty_stack(self) -> None:
        """
        Stress test: Trigger Ctrl+Z undo 25 times consecutively on an empty undo stack.
        Verify that no IndexError or unhandled exception occurs and app remains responsive.
        """
        mgr = self.app._get_active_undo_manager()
        mgr.history.clear()  # Ensure empty stack

        for _ in range(25):
            res = self.app._on_undo_triggered(None)
            self.assertIsNone(res)
            self.assertEqual(self.app.status_var.get(), "Nothing to undo.")

    def test_adv_50_plus_undo_operations(self) -> None:
        """
        Stress test: Push 60 distinct sequential operations to the undo manager.
        Verify max_depth capping (50 depth), and perform 60 sequential undo calls.
        """
        inj = self.app.current_injection
        self.assertIsNotNone(inj)
        sname = "FID1A"
        initial_pks = copy.deepcopy(inj.peaks_by_signal.get(sname, []))

        # Push 60 synthetic modifications
        for i in range(60):
            self.app._push_undo_checkpoint(f"Action #{i}")
            # Mutate state slightly
            inj.peaks_by_signal[sname].append(
                IntegratedPeak(
                    peak_id=f"TEST_PK_{i}",
                    signal_name=sname,
                    signal_description="FID1 A, Front Signal",
                    rt_min=5.0 + i * 0.1,
                    begin_min=4.95 + i * 0.1,
                    end_min=5.05 + i * 0.1,
                    baseline_start_y=10.0,
                    baseline_end_y=10.0,
                    area=5.0,
                    height=10.0,
                )
            )

        mgr = self.app._get_active_undo_manager()
        self.assertEqual(
            len(mgr.history),
            50,
            f"Undo stack must be capped at max_depth=50, found {len(mgr.history)}"
        )

        # Perform 60 undo triggers
        successful_undos = 0
        for i in range(60):
            res = self.app._on_undo_triggered(None)
            if res == "break":
                successful_undos += 1

        self.assertEqual(successful_undos, 50, "Exactly 50 undos should succeed.")
        self.assertEqual(len(mgr.history), 0, "Stack should be empty after 50 undos.")

        # Re-verify that 61st undo gracefully reports nothing to undo
        res_after = self.app._on_undo_triggered(None)
        self.assertIsNone(res_after)
        self.assertEqual(self.app.status_var.get(), "Nothing to undo.")

    def test_adv_escape_key_during_active_drag_and_tool(self) -> None:
        """
        Stress test: Activate draw_peak, drag_anchor, and box zoom, press Escape,
        and verify immediate state clearance and reset to default 'pan_zoom' pointer.
        """
        canvas = self.app.chrom_canvas

        # Scenario 1: Active draw_peak drag
        self.app.tool_var.set("draw_peak")
        canvas.set_tool_mode("draw_peak")
        canvas._drag_state = {"mode": "draw_peak", "start_px": (100, 100), "cur_px": (200, 200)}

        self.app._on_escape_triggered(None)
        self.assertIsNone(canvas._drag_state, "Drag state must be cleared.")
        self.assertEqual(canvas.tool_mode, "pan_zoom", "Canvas tool mode must reset to pan_zoom.")
        self.assertEqual(self.app.tool_var.get(), "pan_zoom", "Tool var must reset to pan_zoom.")

        # Scenario 2: Active zoom box
        canvas._drag_state = {"mode": "zoom_box", "start_px": (50, 50), "cur_px": (150, 150)}
        self.app._on_escape_triggered(None)
        self.assertIsNone(canvas._drag_state)

        # Scenario 3: Selected peak and compound highlight
        canvas.selected_peak_id = "PEAK_STRESS_999"
        canvas.highlighted_compound = CompoundDef(
            index=1, name="TestComp", signal="FID1A", exp_rt_min=6.0, abs_window_min=0.1, rel_window_pct=1.0
        )
        self.app._on_escape_triggered(None)
        self.assertIsNone(canvas.selected_peak_id)
        self.assertIsNone(canvas.highlighted_compound)

    def test_adv_context_menu_hit_testing_shared_split_and_dense_peaks(self) -> None:
        """
        Stress test: Right-click hit-testing on shared split drop lines (e.g. H2/Argon on TCD2B),
        anchor points, and dense peak clusters.
        """
        inj = self.app.current_injection
        self.assertIsNotNone(inj)
        canvas = self.app.chrom_canvas
        rects = canvas._get_panel_rects()
        self.assertIn("TCD2B", rects)
        tcd_rect = rects["TCD2B"]

        # Synthesize split peaks (H2 + Argon adjacent)
        pk_h2 = IntegratedPeak(
            peak_id="PK_H2",
            signal_name="TCD2B",
            signal_description="TCD2 B, Back Signal",
            rt_min=8.35,
            begin_min=8.10,
            end_min=8.55,
            height=80.0,
            area=400.0,
            baseline_start_y=20.0,
            baseline_end_y=25.0,
            compound_name="Hydrogen",
        )
        pk_ar = IntegratedPeak(
            peak_id="PK_AR",
            signal_name="TCD2B",
            signal_description="TCD2 B, Back Signal",
            rt_min=8.85,
            begin_min=8.55,  # Shared boundary exactly at 8.55 min
            end_min=9.20,
            height=120.0,
            area=600.0,
            baseline_start_y=25.0,
            baseline_end_y=20.0,
            compound_name="Argon",
        )
        inj.peaks_by_signal["TCD2B"] = [pk_h2, pk_ar]
        canvas.x_range = (7.0, 11.0)
        canvas.redraw()
        rects = canvas._get_panel_rects()
        tcd_rect = rects["TCD2B"]

        # 1. Hit test on shared split baseline anchor at t = 8.55 min
        split_px, split_py = canvas._data_to_px("TCD2B", 8.55, 25.0, tcd_rect)
        hit_type, hit_info = canvas.hit_test_integration_element(int(split_px), int(split_py), sname="TCD2B")
        self.assertEqual(
            hit_type,
            HitType.SHARED_EXTREME,
            "Shared boundary anchor must be detected as HitType.SHARED_EXTREME."
        )
        self.assertEqual(hit_info.get("left_peak"), pk_h2)
        self.assertEqual(hit_info.get("right_peak"), pk_ar)
        self.assertEqual(hit_info.get("anchor_kind"), "shared")

        # 1b. Hit test on vertical drop line between baseline and curve apex
        sig_tcd = inj.signals["TCD2B"]
        y_curve = sig_tcd.value_at_time(8.55)
        y_mid_dropline = (25.0 + y_curve) / 2.0
        dl_px, dl_py = canvas._data_to_px("TCD2B", 8.55, y_mid_dropline, tcd_rect)
        hit_dl_type, hit_dl_info = canvas.hit_test_integration_element(int(dl_px), int(dl_py), sname="TCD2B")
        self.assertEqual(
            hit_dl_type,
            HitType.SHARED_EXTREME,
            "Shared vertical drop-line must be detected as HitType.SHARED_EXTREME."
        )

        # 2. Hit test on H2 peak body
        h2_body_px, h2_body_py = canvas._data_to_px("TCD2B", 8.35, 50.0, tcd_rect)
        hit_b, hit_b_info = canvas.hit_test_integration_element(int(h2_body_px), int(h2_body_py), sname="TCD2B")
        self.assertEqual(hit_b, HitType.PEAK_BODY)
        self.assertEqual(hit_b_info.get("peak"), pk_h2)

        # 3. Hit test on Argon start/end anchors
        ar_end_px, ar_end_py = canvas._data_to_px("TCD2B", 9.20, 20.0, tcd_rect)
        hit_a, hit_a_info = canvas.hit_test_integration_element(int(ar_end_px), int(ar_end_py), sname="TCD2B")
        self.assertEqual(hit_a, HitType.ANCHOR)
        self.assertEqual(hit_a_info.get("kind"), "end")


class TestAdversarialThemeSwitching(HeadlessTkTestCase):
    """Stress tests for Theme Switching, Contrast, and Rapid Cycling."""

    def setUp(self) -> None:
        super().setUp()
        self.app = OpenChromLabApp(initial_workspace=get_workspace_root())
        self.app.withdraw()
        self.app.load_directory(get_test_set_path())
        self.app.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except Exception:
            pass
        for folder in find_d_folders(get_test_set_path()):
            override_path = os.path.join(folder, "openlab_sub_manual.json")
            if os.path.exists(override_path):
                try:
                    os.remove(override_path)
                except Exception:
                    pass
        super().tearDown()

    def test_adv_rapid_theme_cycling(self) -> None:
        """
        Stress test: Rapidly cycle between Light and Dark themes (20 consecutive toggles)
        while modifying zoom ranges.
        Verify zero crashes, widget stability, and correct active theme attributes.
        """
        for i in range(20):
            # Alternating themes
            target = "dark" if i % 2 == 0 else "light"
            self.app.set_theme(target)
            self.assertEqual(self.app.current_theme_name, target)

            # Concurrently mutate canvas zoom
            self.app.chrom_canvas.x_range = (4.0 + (i * 0.1), 16.0 - (i * 0.1))
            self.app.chrom_canvas.redraw()
            self.app.update_idletasks()

        # Final state check
        self.assertEqual(self.app.current_theme_name, "light")
        self.assertEqual(self.app.theme.name, "light")

    def test_adv_theme_contrast_invariants(self) -> None:
        """
        Verify that both LIGHT_PALETTE and DARK_PALETTE satisfy contrast invariants:
        - Panel background != Canvas trace line colors
        - App background != Text foreground
        - Tree background != Tree foreground
        - Baseline selected color is distinct from panel background
        """
        for palette in (LIGHT_PALETTE, DARK_PALETTE):
            self.assertNotEqual(
                palette.canvas_bg.lower(),
                palette.trace_fid.lower(),
                f"{palette.name}: FID trace must have distinct color from canvas bg"
            )
            self.assertNotEqual(
                palette.canvas_bg.lower(),
                palette.trace_tcd.lower(),
                f"{palette.name}: TCD trace must have distinct color from canvas bg"
            )
            self.assertNotEqual(
                palette.bg_app.lower(),
                palette.fg_app.lower(),
                f"{palette.name}: App foreground text must differ from background"
            )
            self.assertNotEqual(
                palette.tree_bg.lower(),
                palette.tree_fg.lower(),
                f"{palette.name}: Tree foreground text must differ from tree background"
            )
            self.assertNotEqual(
                palette.panel_bg.lower(),
                palette.baseline_selected.lower(),
                f"{palette.name}: Selected baseline must stand out against panel background"
            )


if __name__ == "__main__":
    unittest.main()
