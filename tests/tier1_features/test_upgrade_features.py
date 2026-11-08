"""
Tier 1: Feature Coverage — Upgrade Features F1–F12
Tests for:
- F1: Multi-resolution mipmap pyramid (B=16, 64, 256), min_max_in_range, get_decimated_envelope
- F2: Sub-16ms (>= 60 FPS) chromatogram trace rendering and < 1,200 vertex cap
- F3: Out-of-bounds X-coordinate clamping for pan/zoom beyond signal domain
- F4: Y-only decimation cache reuse during vertical pan/scale
- F5: Lightweight tagged overlays for box zoom, draw peak, split cursor, and anchor hover
- F6: Zero-bbox label placement performance
- F7–F11: Complete Dark Mode theme overhaul, PillToggleSwitch, and widget styling
- F12: Multi-resolution 5-frame 32-bit BGRA OpenChromLab.ico generator
"""

import os
import struct
import time
import tkinter as tk
import unittest

from tests.test_helpers import (
    HeadlessTkTestCase,
    get_workspace_root,
    get_test_set_path,
    create_synthetic_injection,
)
from agilent_core.ch_reader import ChromatogramSignal, find_d_folders, load_d_folder
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method
from agilent_ui.theme import ThemePalette, LIGHT_PALETTE, DARK_PALETTE
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.main_window import OpenChromLabApp, PillToggleSwitch
from agilent_ui.method_editor import MethodEditorDialog, _CompoundEditSubDialog, _TimedEventEditSubDialog
from agilent_ui.icon_generator import build_multi_res_ico, render_icon_frame_dib


class TestUpgradeFeatures(HeadlessTkTestCase):
    """Comprehensive tests for Features F1–F12 (60 FPS rendering, dark theme overhaul, and 5-frame ICO)."""

    def test_f1_mipmap_pyramid_and_exact_min_max_queries(self) -> None:
        """
        Verify that ChromatogramSignal builds hierarchical mipmap levels at B=16, 64, 256
        and that min_max_in_range(i0, i1) matches brute-force min/max across arbitrary slices.
        """
        folders = find_d_folders(get_test_set_path())
        self.assertGreater(len(folders), 0)
        inj = load_d_folder(folders[0])
        sig = inj.signals["FID1A"]

        m16 = sig.get_mipmap(16)
        m64 = sig.get_mipmap(64)
        m256 = sig.get_mipmap(256)
        self.assertGreater(len(m16), 500)
        self.assertEqual(len(m64), (len(m16) + 3) // 4)
        self.assertEqual(len(m256), (len(m64) + 3) // 4)

        # Verify exact agreement with brute-force min/max on varied unaligned slices
        n = len(sig.values)
        for i0, i1 in [(0, n - 1), (13, 4501), (1024, 8192), (77, 195), (5000, 11999)]:
            if i1 >= n:
                i1 = n - 1
            vmin, vmax = sig.min_max_in_range(i0, i1)
            sub = sig.values[i0 : i1 + 1]
            self.assertAlmostEqual(vmin, min(sub), places=6)
            self.assertAlmostEqual(vmax, max(sub), places=6)

    def test_f2_trace_decimation_vertex_cap_and_60fps_frame_budget(self) -> None:
        """
        Verify that _draw_chromatogram_trace caps trace vertices to <= 1,500 (<= 3,000 coords)
        and achieves >= 60 FPS (average <= 16.67 ms per frame) on a 12,000-point real injection.
        """
        self.root.geometry("1280x720")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()
        process_injection(inj, method, prefer_rx=True)

        canvas_widget.set_data(inj, method, reset_view=False)
        canvas_widget.x_range = (0.0, 40.0)
        canvas_widget.set_theme(DARK_PALETTE)
        self.root.update_idletasks()

        # Verify trace line vertex count is compact (< 1,500 points = 3,000 coordinates)
        c = canvas_widget.canvas
        trace_items = c.find_withtag("chromatogram_trace")
        self.assertGreaterEqual(len(trace_items), 1)
        for item_id in trace_items:
            coords = c.coords(item_id)
            num_vertices = len(coords) // 2
            self.assertLessEqual(
                num_vertices,
                1500,
                f"Trace vertex count ({num_vertices}) exceeds 1,500 cap",
            )

        # Warmup 2 frames to prime Tcl canvas coordinates & font metrics
        canvas_widget.redraw()
        canvas_widget.redraw()

        # Benchmark 20 consecutive X-pan frames + 20 Y-pan frames
        t0 = time.perf_counter()
        for step in range(20):
            canvas_widget.x_range = (0.5 + step * 0.15, 25.5 + step * 0.15)
            canvas_widget.redraw()
        for step in range(20):
            canvas_widget.y_ranges["FID1A"] = (8.0 + step * 0.2, 26.0 + step * 0.2)
            canvas_widget.redraw()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        avg_frame_ms = elapsed_ms / 40.0
        self.assertLessEqual(
            avg_frame_ms,
            16.67,
            f"Average redraw frame time ({avg_frame_ms:.2f} ms) exceeds 16.67 ms (60 FPS budget)",
        )

    def test_f3_out_of_bounds_x_range_clamping_accuracy(self) -> None:
        """
        Verify that when x_range extends outside [sig.time_min[0], sig.time_min[-1]]
        (e.g., (-10.0, 50.0) for a [0, 40] min signal), the trace starts at the pixel
        corresponding to t=0.0 and ends at t=40.0 rather than stretching across the whole panel.
        """
        self.root.geometry("1000x600")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        inj = create_synthetic_injection()
        method = build_default_mpz_method()
        canvas_widget.set_data(inj, method)
        sig = inj.signals["FID1A"]
        t_first = sig.time_min[0]
        t_last = sig.time_min[-1]

        canvas_widget.x_range = (-10.0, t_last + 15.0)
        canvas_widget.redraw()
        self.root.update_idletasks()

        rect = canvas_widget._get_panel_rects()["FID1A"]
        expected_px_start, _ = canvas_widget._data_to_px("FID1A", t_first, 0.0, rect)
        expected_px_end, _ = canvas_widget._data_to_px("FID1A", t_last, 0.0, rect)

        trace_items = canvas_widget.canvas.find_withtag("trace_FID1A")
        self.assertEqual(len(trace_items), 1)
        coords = canvas_widget.canvas.coords(trace_items[0])
        actual_px_start = coords[0]
        actual_px_end = coords[-2]

        self.assertAlmostEqual(actual_px_start, expected_px_start, delta=2.5)
        self.assertAlmostEqual(actual_px_end, expected_px_end, delta=2.5)

    def test_f4_y_only_decimation_cache_reuse(self) -> None:
        """
        Verify that changing only y_ranges reuses the cached X-decimation envelope
        without recomputing bucket slicing.
        """
        self.root.geometry("1000x600")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()
        canvas_widget.set_data(inj, method)
        canvas_widget.x_range = (0.0, 40.0)
        canvas_widget.redraw()

        self.assertIn("FID1A", canvas_widget._trace_cache)
        cached_data_ref = canvas_widget._trace_cache["FID1A"]["data"]

        # Change Y range only -> cached list object should be reused identically
        canvas_widget.y_ranges["FID1A"] = (5.0, 80.0)
        canvas_widget.redraw()
        self.assertIs(canvas_widget._trace_cache["FID1A"]["data"], cached_data_ref)

    def test_f5_lightweight_tagged_interactive_overlays(self) -> None:
        """
        Verify that box-zoom and split-peak cursor preview use lightweight tagged overlays
        ('overlay_interactive' and 'overlay_cursor') without destroying main trace items.
        """
        self.root.geometry("1000x600")
        canvas_widget = DualChromatogramCanvas(self.root)
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        inj = create_synthetic_injection()
        method = build_default_mpz_method()
        canvas_widget.set_data(inj, method)
        canvas_widget.redraw()

        trace_before = canvas_widget.canvas.find_withtag("trace_FID1A")
        self.assertEqual(len(trace_before), 1)
        trace_id_before = trace_before[0]

        # Simulate box-zoom drag update
        rect = canvas_widget._get_panel_rects()["FID1A"]
        canvas_widget._drag_state = {
            "mode": "zoom_box",
            "sname": "FID1A",
            "start_px": (rect[0] + 40, rect[1] + 20),
            "cur_px": (rect[0] + 180, rect[1] + 90),
        }
        canvas_widget._update_drag_overlay()
        ov_items = canvas_widget.canvas.find_withtag("overlay_interactive")
        self.assertEqual(len(ov_items), 1)
        # Main trace canvas item ID is untouched!
        self.assertEqual(canvas_widget.canvas.find_withtag("trace_FID1A")[0], trace_id_before)

    def test_f7_to_f11_dark_theme_complete_widget_and_switch_styling(self) -> None:
        """
        Verify that switching OpenChromLabApp to dark mode styles topbar, subbar, segmented
        channel/tool pills, sidebar Plot Overlays card, PillToggleSwitch widgets, and canvas
        visual elements (under-curve fill, glow, timed event badges, rotated Y-axis title).
        """
        app = OpenChromLabApp(initial_workspace=get_workspace_root())
        app.withdraw()
        try:
            app.set_theme("dark")
            app.update_idletasks()

            self.assertEqual(app.current_theme_name, "dark")
            self.assertEqual(app.topbar_frame.cget("bg").upper(), DARK_PALETTE.topbar_bg.upper())
            self.assertEqual(app.subbar_frame.cget("bg").upper(), DARK_PALETTE.subbar_bg.upper())
            self.assertEqual(app.ov_frame.cget("bg").upper(), DARK_PALETTE.overlay_card_bg.upper())

            # Active channel pill ("both") has vibrant royal-blue #2563EB background
            self.assertEqual(
                app.channel_rbs["both"].cget("bg").upper(),
                DARK_PALETTE.subbar_active_bg.upper(),
            )
            # Inactive channel pill ("FID1A") has slate background
            self.assertEqual(
                app.channel_rbs["FID1A"].cget("bg").upper(),
                DARK_PALETTE.subbar_btn_bg.upper(),
            )

            # Verify 5 PillToggleSwitch instances + 1 master toggle switch exist and work
            self.assertEqual(len(app.overlay_toggle_switches), 5)
            self.assertIsInstance(app.master_toggle_switch, PillToggleSwitch)
            self.assertTrue(app.chrom_canvas.show_compound_labels.get())
            app.overlay_toggle_switches[0]._on_click()
            self.assertFalse(app.chrom_canvas.show_compound_labels.get())
            app.overlay_toggle_switches[0]._on_click()
            self.assertTrue(app.chrom_canvas.show_compound_labels.get())

            # Load synthetic injection so chromatogram trace, under-fill, and glow render
            inj = create_synthetic_injection()
            app.chrom_canvas.set_data(inj, app.method)
            app.update_idletasks()

            # Verify canvas dark mode visual enhancements (under-fill, glow, y-axis title)
            c = app.chrom_canvas.canvas
            self.assertGreaterEqual(len(c.find_withtag("trace_under_fill")), 1)
            self.assertGreaterEqual(len(c.find_withtag("chromatogram_glow")), 1)
            self.assertGreaterEqual(len(c.find_withtag("y_axis_title")), 1)
        finally:
            app.destroy()

    def test_f12_multi_resolution_5_frame_ico_structure(self) -> None:
        """
        Verify that OpenChromLab.ico contains 5 directory entries (16, 24, 32, 48, 256 px)
        with valid 32-bit BGRA BITMAPINFOHEADER blocks.
        """
        ico_path = os.path.join(get_workspace_root(), "OpenChromLab.ico")
        self.assertTrue(os.path.isfile(ico_path))

        with open(ico_path, "rb") as f:
            data = f.read()

        reserved, ico_type, count = struct.unpack("<HHH", data[:6])
        self.assertEqual(reserved, 0)
        self.assertEqual(ico_type, 1)
        self.assertEqual(count, 5, "OpenChromLab.ico must contain 5 resolution frames (16, 24, 32, 48, 256)")

        widths = []
        for idx in range(count):
            ent_off = 6 + idx * 16
            w_b, h_b, _, _, planes, bpp, bytes_in_res, img_off = struct.unpack(
                "<BBBBHHII", data[ent_off : ent_off + 16]
            )
            actual_w = 256 if w_b == 0 else w_b
            actual_h = 256 if h_b == 0 else h_b
            self.assertEqual(actual_w, actual_h)
            self.assertEqual(planes, 1)
            self.assertEqual(bpp, 32)
            self.assertLessEqual(img_off + bytes_in_res, len(data))

            # Verify BITMAPINFOHEADER at img_off
            bi_size, bi_w, bi_h, bi_planes, bi_bitcount = struct.unpack(
                "<IiiHH", data[img_off : img_off + 16]
            )
            self.assertEqual(bi_size, 40)
            self.assertEqual(bi_w, actual_w)
            self.assertEqual(bi_h, actual_h * 2)
            self.assertEqual(bi_planes, 1)
            self.assertEqual(bi_bitcount, 32)
            widths.append(actual_w)

        self.assertEqual(widths, [16, 24, 32, 48, 256])

    def test_f11_method_editor_dark_theme_and_subdialogs(self) -> None:
        """Verify MethodEditorDialog opens cleanly in dark mode without TypeError or NameError, with zero #FFFFFF backgrounds."""
        app = OpenChromLabApp(initial_workspace=get_workspace_root())
        try:
            app.withdraw()
            app.set_theme("dark")
            app.update_idletasks()

            # Open Method Editor from app
            app._open_method_editor_dialog()
            dlgs = [w for w in app.winfo_children() if isinstance(w, MethodEditorDialog)]
            self.assertEqual(len(dlgs), 1, "MethodEditorDialog failed to open")
            dlg = dlgs[0]
            self.assertEqual(dlg.theme.name, "dark")
            self.assertEqual(str(dlg.cget("bg")).upper(), DARK_PALETTE.bg_app.upper())

            # Check that there are no #FFFFFF or #ffffff backgrounds or tk.RAISED reliefs
            def audit_widgets(widget: tk.Widget) -> None:
                for child in widget.winfo_children():
                    try:
                        bg = str(child.cget("bg")).upper()
                        self.assertNotEqual(bg, "#FFFFFF", f"Found hardcoded #FFFFFF bg in {child}")
                    except (tk.TclError, AttributeError):
                        pass
                    try:
                        relief = str(child.cget("relief")).lower()
                        self.assertNotEqual(relief, "raised", f"Found tk.RAISED relief in {child}")
                    except (tk.TclError, AttributeError):
                        pass
                    audit_widgets(child)

            audit_widgets(dlg)

            # Verify sub-dialogs instantiate without NameError: LIGHT_PALETTE
            comp_sub = _CompoundEditSubDialog(dlg, app.method.compounds[0], is_new=False)
            self.assertIsNotNone(comp_sub)
            comp_sub.destroy()

            event_sub = _TimedEventEditSubDialog(dlg, "FID1A", app.method.signals["FID1A"].timed_events[0], is_new=False)
            self.assertIsNotNone(event_sub)
            event_sub.destroy()
            dlg.destroy()
        finally:
            app.destroy()

    def test_f13_adjust_anchors_segmented_pill_and_rt_bands(self) -> None:
        """Verify _context_action_adjust_anchors updates pill and dark RT window bands exist."""
        app = OpenChromLabApp(initial_workspace=get_workspace_root())
        try:
            app.withdraw()
            app.set_theme("dark")
            app.update_idletasks()

            # Context action updates segmented pill highlight
            app._context_action_adjust_anchors("pk1")
            self.assertEqual(
                app.tool_rbs["drag_anchor"].cget("bg").upper(),
                DARK_PALETTE.subbar_active_bg.upper(),
            )

            # RT window column bands in dark mode
            inj = create_synthetic_injection()
            app.chrom_canvas.set_data(inj, app.method)
            app.chrom_canvas.x_range = (0.0, 20.0)
            app.chrom_canvas.redraw()
            bands = app.chrom_canvas.canvas.find_withtag("rt_window_band")
            self.assertGreater(len(bands), 0, "No rt_window_band rectangles found in dark mode")
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
