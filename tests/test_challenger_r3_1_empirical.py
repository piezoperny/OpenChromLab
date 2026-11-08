"""Empirical Stress-Test Suite — Challenger r3_1 for Milestone 3 (OpenChromLab Round 3).

Focus:
1. 500 Hz mouse event flooding (<B1-Motion> and <MouseWheel>) and 60 FPS throttling verification.
2. Frame time and FPS benchmarks under zoom extremes (span = 40 min vs span = 0.2 min).
3. Canvas item count reduction and label/annotation performance overhead.
4. Memory stability, canvas item leak detection, and after() callback lifecycle.
5. High-frequency direction reversal (jitter stress) and boundary coordinate validity.
6. Widget destruction lifecycle audit for orphaned after() timers.
"""

import gc
import math
import os
import sys
import time
import tkinter as tk
import unittest
from typing import Dict, List, Optional, Tuple

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from agilent_core.ch_reader import (
    ChromatogramSignal,
    find_d_folders,
    load_d_folder,
    InjectionData,
)
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.theme import DARK_PALETTE, LIGHT_PALETTE
from tests.test_helpers import HeadlessTkTestCase, get_test_set_path


class TestEmpiricalCanvasResponsivenessAndThrottling(unittest.TestCase):
    """Rigorous empirical stress testing of canvas responsiveness and throttling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.target_d = os.path.join(get_test_set_path(), "MPZHY14_reaction_261015--120F.D")
        if not os.path.exists(cls.target_d):
            folders = find_d_folders(get_test_set_path())
            assert len(folders) > 0, "No .D folders found"
            cls.target_d = folders[0]

        cls.inj = load_d_folder(cls.target_d)
        cls.method = build_default_mpz_method()
        process_injection(cls.inj, cls.method, prefer_rx=True)

        assert "FID1A" in cls.inj.signals, "FID1A signal missing"
        assert len(cls.inj.signals["FID1A"].values) >= 100000, "FID1A point count under 100k"

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.geometry("1920x1080")
        self.root.withdraw()
        self.canvas_widget = DualChromatogramCanvas(self.root)
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.canvas_widget.set_theme(DARK_PALETTE)
        self.canvas_widget.set_data(self.inj, self.method, reset_view=False)
        self.root.update_idletasks()

    def tearDown(self) -> None:
        # Cancel any pending redraw timer to avoid unhandled Tcl errors during test teardown
        if hasattr(self, "canvas_widget") and self.canvas_widget is not None:
            if getattr(self.canvas_widget, "_pending_redraw_id", None) is not None:
                try:
                    self.canvas_widget.after_cancel(self.canvas_widget._pending_redraw_id)
                except Exception:
                    pass
                self.canvas_widget._pending_redraw_id = None
        try:
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Test 1: 500 Hz Mouse Event Flooding & 60 FPS Throttling
    # ------------------------------------------------------------------

    def test_b1_motion_500hz_event_flooding_throttling(self) -> None:
        """
        Simulate a flood of 200 rapid <B1-Motion> drag events fired at 500 Hz
        (2 ms interval, total burst ~400 ms) mimicking high-performance gaming mice.

        Measures:
        1. Whether event throttling coalesces redraw requests and caps actual redraws to <= ~60 FPS.
        2. UI thread remains responsive and does not freeze.
        3. Accuracy: final canvas view reflects final mouse position.
        """
        canvas_widget = self.canvas_widget
        c = canvas_widget.canvas

        # Set tool to pan_zoom and begin drag in plot body
        rects = canvas_widget._get_panel_rects()
        fid_rect = rects["FID1A"]
        mid_x = (fid_rect[0] + fid_rect[2]) // 2
        mid_y = (fid_rect[1] + fid_rect[3]) // 2

        # Count actual calls to redraw()
        redraw_count = 0
        original_redraw = canvas_widget.redraw

        def tracked_redraw(*args, **kwargs):
            nonlocal redraw_count
            redraw_count += 1
            return original_redraw(*args, **kwargs)

        canvas_widget.redraw = tracked_redraw

        # Initiate Shift+B1 pan drag
        press_event = tk.Event()
        press_event.x = mid_x
        press_event.y = mid_y
        press_event.state = 0x0001  # Shift pressed -> pan mode
        canvas_widget._on_left_down(press_event)

        self.assertIsNotNone(canvas_widget._drag_state)
        self.assertEqual(canvas_widget._drag_state["mode"], "pan")
        initial_x_range = canvas_widget.x_range

        # Reset redraw count after initial setup
        redraw_count = 0

        # Simulate 200 rapid drag motion events at 500 Hz (2 ms nominal interval)
        t_start = time.perf_counter()
        num_events = 200

        for i in range(num_events):
            motion_event = tk.Event()
            motion_event.x = mid_x + i
            motion_event.y = mid_y
            motion_event.state = 0x0001
            canvas_widget._on_left_drag(motion_event)

            # Process pending Tk events and timer callbacks (simulating mainloop tick)
            time.sleep(0.002)
            self.root.update()

        # Release mouse button
        release_event = tk.Event()
        release_event.x = mid_x + num_events
        release_event.y = mid_y
        release_event.state = 0x0001
        canvas_widget._on_left_up(release_event)
        self.root.update()

        t_total = time.perf_counter() - t_start
        final_x_range = canvas_widget.x_range

        effective_fps = redraw_count / t_total

        print(f"\n[BENCHMARK: 500 Hz B1-Motion Drag]")
        print(f"  Events Dispatched: {num_events}")
        print(f"  Total Duration:    {t_total * 1000.0:.1f} ms")
        print(f"  Canvas Redraws:    {redraw_count}")
        print(f"  Effective FPS:     {effective_fps:.1f} FPS")
        print(f"  Initial X Range:   {initial_x_range}")
        print(f"  Final X Range:     {final_x_range}")

        # Throttling check:
        # Without throttling, 200 events would execute 200 redraws.
        # With 60 FPS throttling (~16ms), in ~400-600ms there can be at most ~35-40 redraws.
        self.assertLess(
            redraw_count,
            num_events // 3,
            f"Throttling failed: {redraw_count} redraws executed for {num_events} events (no throttling)",
        )
        self.assertLessEqual(
            effective_fps,
            75.0,
            f"Effective redraw FPS ({effective_fps:.1f}) significantly exceeded 60 FPS cap",
        )
        # Verify panning actually updated the view range
        self.assertNotEqual(initial_x_range, final_x_range, "X range did not pan during drag")

    def test_mousewheel_500hz_event_flooding_throttling(self) -> None:
        """
        Simulate a flood of 200 rapid <MouseWheel> events at high frequency
        (simulating fast-spinning stepped/freewheel gaming mice).

        Measures:
        1. Event coalescing prevents redundant redraw execution.
        2. Capped at ~60 FPS animation rate.
        3. No UI freeze.
        """
        canvas_widget = self.canvas_widget
        rects = canvas_widget._get_panel_rects()
        fid_rect = rects["FID1A"]
        mid_x = (fid_rect[0] + fid_rect[2]) // 2
        mid_y = (fid_rect[1] + fid_rect[3]) // 2

        redraw_count = 0
        original_redraw = canvas_widget.redraw

        def tracked_redraw(*args, **kwargs):
            nonlocal redraw_count
            redraw_count += 1
            return original_redraw(*args, **kwargs)

        canvas_widget.redraw = tracked_redraw

        initial_x_range = canvas_widget.x_range
        num_events = 200
        t_start = time.perf_counter()

        for i in range(num_events):
            wheel_event = tk.Event()
            wheel_event.x = mid_x
            wheel_event.y = mid_y
            wheel_event.delta = 120 if (i % 2 == 0) else -120  # Zoom in and out
            wheel_event.state = 0
            canvas_widget._on_mouse_wheel(wheel_event)

            time.sleep(0.002)
            self.root.update()

        t_total = time.perf_counter() - t_start
        effective_fps = redraw_count / t_total

        print(f"\n[BENCHMARK: 500 Hz MouseWheel Zoom]")
        print(f"  Events Dispatched: {num_events}")
        print(f"  Total Duration:    {t_total * 1000.0:.1f} ms")
        print(f"  Canvas Redraws:    {redraw_count}")
        print(f"  Effective FPS:     {effective_fps:.1f} FPS")

        self.assertLess(
            redraw_count,
            num_events // 3,
            f"MouseWheel throttling failed: {redraw_count} redraws for {num_events} events",
        )
        self.assertLessEqual(
            effective_fps,
            75.0,
            f"MouseWheel effective FPS ({effective_fps:.1f}) exceeded 60 FPS cap",
        )

    # ------------------------------------------------------------------
    # Test 2: Frame Time Benchmarks: Full Zoom-Out vs Zoomed into 1 Peak
    # ------------------------------------------------------------------

    def test_frame_time_zoomed_out_vs_zoomed_into_one_peak(self) -> None:
        """
        Directly measures canvas redraw frame time under two critical extremes:
        1. Completely zoomed out: span = 40 min ([0.0, 40.0] min, all 120,000 points active).
        2. Zoomed into 1 peak: span = 0.2 min ([8.0, 8.2] min, high-resolution peak inspection).

        Measures:
        - Exact redraw() execution time in milliseconds.
        - Calculated FPS (1000.0 / avg_ms).
        - Trace vertex count.
        """
        canvas_widget = self.canvas_widget

        # --- A. Zoomed Out: span = 40.0 min ---
        canvas_widget.x_range = (0.0, 40.0)
        canvas_widget.redraw()
        self.root.update_idletasks()

        # Warmup 5 frames to prime fonts and Tk geometry
        for _ in range(5):
            canvas_widget.redraw()
        self.root.update_idletasks()

        # Measure 30 dynamic frames (panning 0.1 min per frame to avoid static cache reuse)
        n_frames = 30
        times_zoomed_out = []
        for step in range(n_frames):
            canvas_widget.x_range = (step * 0.1, 40.0 + step * 0.1)
            t0 = time.perf_counter()
            canvas_widget.redraw()
            t1 = time.perf_counter()
            times_zoomed_out.append((t1 - t0) * 1000.0)

        avg_ms_out = sum(times_zoomed_out) / len(times_zoomed_out)
        min_ms_out = min(times_zoomed_out)
        max_ms_out = max(times_zoomed_out)
        fps_out = 1000.0 / avg_ms_out

        # Check vertex count for zoomed out
        c = canvas_widget.canvas
        trace_items = c.find_withtag("chromatogram_trace")
        vertices_out = [len(c.coords(it)) // 2 for it in trace_items]

        # --- B. Zoomed into 1 Peak: span = 0.2 min ---
        canvas_widget.x_range = (8.0, 8.2)
        canvas_widget.redraw()
        self.root.update_idletasks()

        for _ in range(5):
            canvas_widget.redraw()
        self.root.update_idletasks()

        times_zoomed_in = []
        for step in range(n_frames):
            canvas_widget.x_range = (8.0 + step * 0.005, 8.2 + step * 0.005)
            t0 = time.perf_counter()
            canvas_widget.redraw()
            t1 = time.perf_counter()
            times_zoomed_in.append((t1 - t0) * 1000.0)

        avg_ms_in = sum(times_zoomed_in) / len(times_zoomed_in)
        min_ms_in = min(times_zoomed_in)
        max_ms_in = max(times_zoomed_in)
        fps_in = 1000.0 / avg_ms_in

        vertices_in = [len(c.coords(it)) // 2 for it in trace_items]

        print(f"\n[BENCHMARK: Zoom Extremes Frame Times]")
        print(f"  Zoomed Out (span=40.0 min):")
        print(f"    Avg Frame Time: {avg_ms_out:.2f} ms ({fps_out:.1f} FPS)")
        print(f"    Min/Max:        {min_ms_out:.2f} ms / {max_ms_out:.2f} ms")
        print(f"    Vertices/Trace: {vertices_out}")
        print(f"  Zoomed In (span=0.2 min):")
        print(f"    Avg Frame Time: {avg_ms_in:.2f} ms ({fps_in:.1f} FPS)")
        print(f"    Min/Max:        {min_ms_in:.2f} ms / {max_ms_in:.2f} ms")
        print(f"    Vertices/Trace: {vertices_in}")

        for v in vertices_out + vertices_in:
            self.assertLessEqual(v, 1500, f"Vertex count {v} exceeded 1,500 cap")
        self.assertLessEqual(avg_ms_out, 16.67, f"Zoomed out frame time {avg_ms_out:.2f} ms exceeded 16.67 ms (60 FPS)")
        self.assertLessEqual(avg_ms_in, 16.67, f"Zoomed in frame time {avg_ms_in:.2f} ms exceeded 16.67 ms (60 FPS)")

    # ------------------------------------------------------------------
    # Test 3: Canvas Item Count & Labels/Annotations Overhead
    # ------------------------------------------------------------------

    def test_canvas_item_count_and_label_overhead(self) -> None:
        """
        Verifies:
        1. Total canvas item count remains bounded and does not explode.
        2. Labels and annotations do not blow up frame time.
        """
        canvas_widget = self.canvas_widget
        c = canvas_widget.canvas

        canvas_widget.x_range = (3.5, 16.5)  # Active peak region with many compounds
        canvas_widget.show_compound_labels.set(True)
        canvas_widget.redraw()
        self.root.update_idletasks()

        items_with_labels = len(c.find_withtag("all"))
        label_items = len(c.find_withtag("peak_label"))
        annotation_items = len(c.find_withtag("peak_annotation"))

        # Measure frame time WITH labels
        n_frames = 25
        t0 = time.perf_counter()
        for step in range(n_frames):
            canvas_widget.x_range = (3.5 + step * 0.05, 16.5 + step * 0.05)
            canvas_widget.redraw()
        time_with_labels_ms = ((time.perf_counter() - t0) * 1000.0) / n_frames

        # Measure frame time WITHOUT labels
        canvas_widget.show_compound_labels.set(False)
        canvas_widget.redraw()
        self.root.update_idletasks()

        items_without_labels = len(c.find_withtag("all"))

        t0 = time.perf_counter()
        for step in range(n_frames):
            canvas_widget.x_range = (3.5 + step * 0.05, 16.5 + step * 0.05)
            canvas_widget.redraw()
        time_without_labels_ms = ((time.perf_counter() - t0) * 1000.0) / n_frames

        label_overhead_ms = time_with_labels_ms - time_without_labels_ms

        print(f"\n[BENCHMARK: Label Overhead & Item Count]")
        print(f"  Canvas Items (with labels):    {items_with_labels}")
        print(f"  Canvas Items (without labels): {items_without_labels}")
        print(f"  Peak Labels rendered:          {label_items}")
        print(f"  Frame Time (with labels):      {time_with_labels_ms:.2f} ms")
        print(f"  Frame Time (without labels):   {time_without_labels_ms:.2f} ms")
        print(f"  Net Label Overhead:            {label_overhead_ms:.2f} ms")

        # Total canvas item count should be well below 1,200 items
        self.assertLess(items_with_labels, 1200, f"Canvas item count ({items_with_labels}) is excessively high")
        # Label overhead should not exceed 5 ms
        self.assertLess(label_overhead_ms, 5.0, f"Label overhead ({label_overhead_ms:.2f} ms) exceeds 5 ms budget")

    # ------------------------------------------------------------------
    # Test 4: Memory Stability & after() Leak Verification
    # ------------------------------------------------------------------

    def test_memory_stability_and_after_lifecycle(self) -> None:
        """
        Stress test memory and Tk callback lifecycle:
        1. 200 rapid request_redraw() calls simulating continuous user interaction.
        2. Ensure _pending_redraw_id is properly cancelled/cleared with no orphaned timers.
        3. Ensure canvas item count returns exactly to initial count when resetting view (zero item leakage).
        """
        canvas_widget = self.canvas_widget
        c = canvas_widget.canvas

        canvas_widget.x_range = (0.0, 40.0)
        canvas_widget.redraw()
        self.root.update_idletasks()

        initial_item_count = len(c.find_withtag("all"))

        # Run 200 interaction cycles using request_redraw()
        for cycle in range(200):
            canvas_widget.x_range = (cycle * 0.05, 40.0 + cycle * 0.05)
            canvas_widget.request_redraw()
            if cycle % 5 == 0:
                self.root.update()

        # Let all scheduled timers finish
        self.root.update()
        time.sleep(0.05)
        self.root.update()

        # At rest, there should be NO pending scheduled redraw timer
        self.assertIsNone(
            canvas_widget._pending_redraw_id,
            "Pending redraw timer was not cleared after completing scheduled redraws",
        )

        # Reset back to original range (0.0, 40.0) and redraw
        canvas_widget.x_range = (0.0, 40.0)
        canvas_widget.redraw()
        self.root.update_idletasks()

        final_item_count = len(c.find_withtag("all"))

        print(f"\n[BENCHMARK: Memory Stability & Lifecycle]")
        print(f"  Initial Canvas Item Count: {initial_item_count}")
        print(f"  Final Canvas Item Count:   {final_item_count}")
        print(f"  Pending Redraw ID at Rest: {canvas_widget._pending_redraw_id}")

        self.assertEqual(
            initial_item_count,
            final_item_count,
            f"Canvas item leakage detected: started with {initial_item_count}, ended with {final_item_count}",
        )

    # ------------------------------------------------------------------
    # Test 5: Rapid Direction Reversal (Jitter Stress)
    # ------------------------------------------------------------------

    def test_rapid_direction_reversal_jitter_stress(self) -> None:
        """
        Simulate erratic high-frequency mouse jitter (rapid left/right direction reversal
        100 times in 200 ms). Verify no coordinate NaN/Inf, no negative dimensions,
        and flawless recovery.
        """
        canvas_widget = self.canvas_widget
        rects = canvas_widget._get_panel_rects()
        fid_rect = rects["FID1A"]
        mid_x = (fid_rect[0] + fid_rect[2]) // 2
        mid_y = (fid_rect[1] + fid_rect[3]) // 2

        press_event = tk.Event()
        press_event.x = mid_x
        press_event.y = mid_y
        press_event.state = 0x0001
        canvas_widget._on_left_down(press_event)

        for i in range(100):
            jitter_x = mid_x + (25 if (i % 2 == 0) else -25)
            motion_event = tk.Event()
            motion_event.x = jitter_x
            motion_event.y = mid_y
            motion_event.state = 0x0001
            canvas_widget._on_left_drag(motion_event)
            if i % 10 == 0:
                self.root.update()

        release_event = tk.Event()
        release_event.x = mid_x
        release_event.y = mid_y
        release_event.state = 0x0001
        canvas_widget._on_left_up(release_event)
        self.root.update()

        x0, x1 = canvas_widget.x_range
        self.assertFalse(math.isnan(x0) or math.isnan(x1), "X range became NaN after jitter stress")
        self.assertFalse(math.isinf(x0) or math.isinf(x1), "X range became Inf after jitter stress")
        self.assertGreater(x1, x0, "X range inverted after jitter stress")

    # ------------------------------------------------------------------
    # Test 6: Destruction Lifecycle & Orphaned after() Callbacks
    # ------------------------------------------------------------------

    def test_destroy_lifecycle_cleans_pending_after_callback(self) -> None:
        """
        Adversarial test: Destroying DualChromatogramCanvas while a redraw is pending
        MUST cancel the after() timer. Otherwise, Tcl attempts to execute
        the callback on a destroyed widget, causing 'invalid command name' errors.
        """
        test_canvas = DualChromatogramCanvas(self.root)
        test_canvas.pack()
        test_canvas.request_redraw()
        self.assertIsNotNone(test_canvas._pending_redraw_id, "Redraw was not scheduled")

        # Destroy widget
        test_canvas.destroy()

        # If destroy() is properly implemented, _pending_redraw_id should be cleared
        self.assertIsNone(
            test_canvas._pending_redraw_id,
            "DualChromatogramCanvas.destroy() failed to cancel and clear _pending_redraw_id, leaving orphaned Tcl after callback",
        )


if __name__ == "__main__":
    unittest.main()
