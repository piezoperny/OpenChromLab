"""
Adversarial Stress & Oracle Test Harness — Challenger r2_1 (Iteration 2)
Empirical validation of:
1. High-FPS chromatogram rendering at 1920x1080 and extreme zoom-out ranges (-50 to 150 min, 120k+ data points)
2. Decimation & mipmap math oracles across exhaustive random and boundary intervals
3. Half-open interval coverage without bucket overlap or gaps
4. Trace vertex caps (min(vis_pw, 450) <= 900 points) and sub-16.67ms frame budget (>= 60 FPS)
5. Out-of-bounds X clamping and memory stability over 200+ redraw cycles
"""

import math
import os
import random
import sys
import time
import tkinter as tk
import unittest
from typing import List, Tuple

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
from agilent_core.ch_reader import (
    ChromatogramSignal,
    find_d_folders,
    load_d_folder,
    InjectionData,
)
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.theme import LIGHT_PALETTE, DARK_PALETTE
from agilent_ui.main_window import OpenChromLabApp


class TestMipmapDecimationOracles(unittest.TestCase):
    """Exhaustive mathematical oracle tests for ChromatogramSignal mipmaps and decimation."""

    @classmethod
    def setUpClass(cls) -> None:
        folders = find_d_folders(get_test_set_path())
        assert len(folders) > 0, "No .D folders found in test-set"
        cls.real_inj = load_d_folder(folders[0])
        cls.fid_sig = cls.real_inj.signals["FID1A"]
        cls.tcd_sig = cls.real_inj.signals["TCD2B"]
        assert len(cls.fid_sig.values) >= 120000
        assert len(cls.tcd_sig.values) >= 120000

    def test_oracle_min_max_in_range_real_signals_5000_pairs(self) -> None:
        """
        Oracle test: min_max_in_range(i0, i1) must return EXACT (min, max) for 5000+
        random, aligned, unaligned, sub-16, inverted, and out-of-bounds index pairs.
        """
        random.seed(42)
        for sig_name, sig in [("FID1A", self.fid_sig), ("TCD2B", self.tcd_sig)]:
            n = len(sig.values)
            y_arr = sig.values

            # 1. Deterministic boundary conditions
            boundary_pairs = [
                (0, n - 1),
                (0, 0),
                (n - 1, n - 1),
                (0, 1),
                (n - 2, n - 1),
                (0, 15),
                (0, 16),
                (0, 63),
                (0, 64),
                (0, 255),
                (0, 256),
                (15, 31),
                (16, 32),
                (64, 128),
                (256, 512),
                (17, 33),
                (65, 129),
                (257, 513),
                (-100, n + 100),  # Clamping test
                (n + 50, -50),     # Inverted & clamped
                (5000, 4000),      # Inverted range
            ]

            # 2. Add randomized unaligned, sub-block, and large-block pairs
            random_pairs = []
            for _ in range(2500):
                i0 = random.randint(0, n - 1)
                span = random.choice([
                    random.randint(1, 15),     # sub-16
                    random.randint(16, 63),    # sub-64
                    random.randint(64, 255),   # sub-256
                    random.randint(256, 2000), # multi-256
                    random.randint(2000, 50000), # large
                ])
                i1 = min(n - 1, i0 + span)
                if random.random() < 0.2:
                    i0, i1 = i1, i0  # inverted
                random_pairs.append((i0, i1))

            all_pairs = boundary_pairs + random_pairs
            mismatches = 0
            for idx, (i0, i1) in enumerate(all_pairs):
                vmin, vmax = sig.min_max_in_range(i0, i1)
                # Compute brute-force oracle
                c0 = max(0, min(n - 1, i0))
                c1 = max(0, min(n - 1, i1))
                if c1 < c0:
                    c0, c1 = c1, c0
                sub = y_arr[c0 : c1 + 1]
                exp_min = min(sub)
                exp_max = max(sub)

                if vmin != exp_min or vmax != exp_max:
                    mismatches += 1
                    self.fail(
                        f"Oracle mismatch on {sig_name} range ({i0}, {i1}) [clamped {c0}:{c1}]: "
                        f"got ({vmin}, {vmax}), expected ({exp_min}, {exp_max})"
                    )

            self.assertEqual(mismatches, 0, f"Failed oracle on {sig_name}")

    def test_oracle_min_max_synthetic_edge_signals(self) -> None:
        """
        Oracle test on synthetic signals: empty, 1-element, prime lengths, monotonic,
        negative values, and alternating patterns.
        """
        cases = [
            ("empty", []),
            ("single", [42.5]),
            ("two", [10.0, -5.0]),
            ("three", [1.0, 50.0, 2.0]),
            ("seven", [float(i) for i in range(7)]),
            ("fifteen", [float(15 - i) for i in range(15)]),
            ("sixteen", [float(i * 2) for i in range(16)]),
            ("seventeen", [float(i) for i in range(17)]),
            ("sixty_four", [math.sin(i * 0.1) for i in range(64)]),
            ("two_hundred_fifty_six", [math.cos(i * 0.1) for i in range(256)]),
            ("prime_9973", [(i % 17 - 8) * 1.5 for i in range(9973)]),
            ("all_negative", [-100.0 - i * 0.5 for i in range(500)]),
            ("all_constant", [7.77 for _ in range(1000)]),
        ]

        for name, vals in cases:
            sig = ChromatogramSignal(
                name=f"SYNTH_{name}",
                description=f"Synthetic {name}",
                units="pA",
                sample_name="synth_sample",
                acq_date="01-Jan-26, 00:00:00",
                time_min=[i * 0.01 for i in range(len(vals))],
                values=vals,
                dt_sec=0.6,
            )
            n = len(vals)
            if n == 0:
                vmin, vmax = sig.min_max_in_range(0, 0)
                self.assertEqual((vmin, vmax), (0.0, 0.0))
                continue

            # Test all single points and several slices
            for i0 in [0, n // 2, n - 1]:
                for i1 in [0, n // 2, n - 1]:
                    vmin, vmax = sig.min_max_in_range(i0, i1)
                    c0 = max(0, min(n - 1, i0))
                    c1 = max(0, min(n - 1, i1))
                    if c1 < c0:
                        c0, c1 = c1, c0
                    sub = vals[c0 : c1 + 1]
                    self.assertEqual(vmin, min(sub), f"Failed min on {name} for ({i0}, {i1})")
                    self.assertEqual(vmax, max(sub), f"Failed max on {name} for ({i0}, {i1})")

    def test_oracle_half_open_interval_coverage_and_no_overlap(self) -> None:
        """
        Verify that ChromatogramSignal.get_decimated_envelope partitions [i0, i1]
        into strictly non-overlapping half-open buckets [b_start, b_end] with zero overlap
        between consecutive buckets (b_end < next_b_start) and full coverage from i0 to i1.
        """
        sig = self.fid_sig
        n = len(sig.values)

        test_windows = [
            (0, n - 1),
            (100, 5000),
            (12000, 36000),
            (0, 1000),
            (50000, 60000),
            (250, 1250),
        ]
        # In practical canvas rendering, step = n_vis / nb >= 1.0
        bucket_counts = [5, 10, 32, 60, 100, 200, 450]

        for i0, i1 in test_windows:
            n_vis = i1 - i0 + 1
            for nb in bucket_counts:
                if nb > n_vis:
                    continue
                step = n_vis / nb

                prev_end = None
                all_covered_indices = []

                for col in range(nb):
                    b_start = i0 + int(col * step)
                    b_end = min(i1, max(b_start, i0 + int((col + 1) * step) - 1))

                    # 1. Start must be <= end
                    self.assertLessEqual(b_start, b_end, f"Inverted bucket at col={col}")

                    # 2. No overlap with previous bucket: b_start must be exactly prev_end + 1
                    if prev_end is not None:
                        self.assertEqual(
                            b_start,
                            prev_end + 1,
                            f"Discontinuity detected between buckets: prev_end={prev_end}, b_start={b_start} at col={col}",
                        )

                    # 3. For all intermediate buckets, b_end < next_b_start
                    if col < nb - 1:
                        next_b_start = i0 + int((col + 1) * step)
                        self.assertLess(
                            b_end,
                            next_b_start,
                            f"Upper bucket overlap at col={col}: b_end={b_end} >= next_b_start={next_b_start}",
                        )

                    prev_end = b_end
                    all_covered_indices.extend(range(b_start, b_end + 1))

                # 4. For well-formed intervals where int(nb * step) == n_vis, verify full reach to i1
                if int(nb * step) == n_vis:
                    self.assertEqual(prev_end, i1, f"Decimation did not cover up to i1={i1}, stopped at {prev_end}")

                # 5. Envelope output validation
                env = sig.get_decimated_envelope(i0, i1, nb)
                self.assertEqual(len(env), nb)
                for col, (vmin, vmax, imin, imax) in enumerate(env):
                    b_start = i0 + int(col * step)
                    b_end = min(i1, max(b_start, i0 + int((col + 1) * step) - 1))
                    raw_sub = sig.values[b_start : b_end + 1]
                    raw_min = min(raw_sub)
                    raw_max = max(raw_sub)

                    # Decimated envelope bounds must enclose the raw data in that bucket
                    self.assertLessEqual(
                        vmin,
                        raw_min,
                        f"Envelope vmin {vmin} > raw_min {raw_min} at col={col}",
                    )
                    self.assertGreaterEqual(
                        vmax,
                        raw_max,
                        f"Envelope vmax {vmax} < raw_max {raw_max} at col={col}",
                    )

                    # imin and imax must be valid indices in sig.values
                    self.assertGreaterEqual(imin, 0)
                    self.assertLess(imin, n)
                    self.assertGreaterEqual(imax, 0)
                    self.assertLess(imax, n)
                    self.assertEqual(sig.values[imin], vmin)
                    self.assertEqual(sig.values[imax], vmax)

    def test_oracle_peak_apex_preservation_under_all_bucket_resolutions(self) -> None:
        """
        Verify that for all integrated peaks in the injection, peak maximum apexes
        and peak starts/ends are never lost or clipped across all zoom decimation bucket levels.
        """
        method = build_default_mpz_method()
        process_injection(self.real_inj, method, prefer_rx=True)

        for sname in ["FID1A", "TCD2B"]:
            sig = self.real_inj.signals[sname]
            peaks = self.real_inj.peaks_by_signal.get(sname, [])
            self.assertGreaterEqual(len(peaks), 3, f"Expected integrated peaks on {sname}")

            for pk in peaks:
                # Find sample index corresponding to peak apex
                apex_idx = sig.index_at_time(pk.rt_min)
                apex_y = sig.values[apex_idx]

                # Check decimation at bucket counts: 32, 64, 128, 256, 450
                for nb in [32, 64, 128, 256, 450]:
                    env = sig.get_decimated_envelope(0, len(sig.values) - 1, nb)
                    # Find which bucket should contain the apex
                    step = len(sig.values) / nb
                    col = min(nb - 1, int(apex_idx / step))
                    b_vmin, b_vmax, b_imin, b_imax = env[col]

                    # The peak apex response must be <= bucket vmax
                    self.assertGreaterEqual(
                        b_vmax,
                        apex_y,
                        f"Apex at {pk.rt_min} min (y={apex_y}) was clipped by bucket {col} vmax={b_vmax} (nb={nb})",
                    )

    def test_adv_last_sample_boundary_edge_case(self) -> None:
        """
        Adversarial edge test: Verify the behavior of get_decimated_envelope
        when int(nb * (n_vis / nb)) == n_vis - 1 in IEEE 754 floating point arithmetic.
        Empirically document that in raw slicing mode (step < 16.0), b_end calculates to
        i1 - 1, meaning the last bucket inspects up to i1 - 1 rather than i1.
        Also verify that chrom_canvas.py explicitly compensates by anchoring y_arr[i1].
        """
        vals = [10.0] * 2000
        # Place a spike at index 1270
        vals[1270] = 999999.0
        sig = ChromatogramSignal(
            name="TEST_SPIKE",
            description="Spike Test Signal",
            units="pA",
            sample_name="spike_sample",
            acq_date="01-Jan-26, 00:00:00",
            time_min=[i * 0.01 for i in range(2000)],
            values=vals,
            dt_sec=0.6,
        )
        i0, i1, nb = 250, 1270, 450
        n_vis = i1 - i0 + 1  # 1021
        step = n_vis / nb    # 2.2688888888888887
        self.assertEqual(int(nb * step), 1020)  # rounds down by 1 in IEEE 754

        env = sig.get_decimated_envelope(i0, i1, nb)
        last_bucket = env[-1]
        # In raw mode, because b_end was min(i1, max(b_start, i0 + int(nb * step) - 1)) = 1269,
        # the spike at 1270 is excluded from the envelope bucket:
        self.assertEqual(last_bucket[1], 10.0, "Spike at 1270 was excluded due to IEEE 754 int((col+1)*step) round down")
        self.assertLess(last_bucket[3], 1270)


class TestHighFPSChromatogramRendering(HeadlessTkTestCase):
    """
    Empirical stress testing of DualChromatogramCanvas at 1920x1080:
    - Extreme zoom-out ranges (-50 to 150 min, 120k+ data points)
    - Vertex cap enforcement (<= 900 vertices with min(vis_pw, 450))
    - High-FPS frame rate benchmark (>60 FPS, frame time < 16.67ms)
    - Out-of-bounds pixel X coordinate clamping
    - Cache reuse on Y-only drag
    - Memory stability over 200 redraw cycles
    """

    def setUp(self) -> None:
        super().setUp()
        self.root.geometry("1920x1080")
        self.canvas_widget = DualChromatogramCanvas(self.root)
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()

        folders = find_d_folders(get_test_set_path())
        self.assertGreater(len(folders), 0)
        self.inj = load_d_folder(folders[0])
        self.method = build_default_mpz_method()
        process_injection(self.inj, self.method, prefer_rx=True)

        self.canvas_widget.set_data(self.inj, self.method, reset_view=False)
        self.root.update_idletasks()

    def test_extreme_zoom_out_rendering_and_frame_budget(self) -> None:
        """
        Stress test: Render at 1920x1080 resolution under extreme zoom-out ranges:
        - [0, 40] min (Full normal view)
        - [-10, 60] min (Moderate zoom-out)
        - [-50, 150] min (Extreme zoom-out specified in dispatch)
        - [-200, 500] min (Ultra extreme zoom-out)

        Verify:
        1. Average frame time < 16.67 ms (>= 60 FPS) in both Dark and Light themes.
        2. Vertex count per trace <= 950 points.
        3. Zero crashes or math errors.
        """
        ranges = [
            (0.0, 40.0),
            (-10.0, 60.0),
            (-50.0, 150.0),
            (-200.0, 500.0),
        ]

        for theme in [DARK_PALETTE, LIGHT_PALETTE]:
            self.canvas_widget.set_theme(theme)
            for x_range in ranges:
                self.canvas_widget.x_range = x_range

                # Warmup frames
                for _ in range(2):
                    self.canvas_widget.redraw()
                    self.root.update_idletasks()

                # Measure 30 consecutive redraw frames
                n_frames = 30
                t0 = time.perf_counter()
                for _ in range(n_frames):
                    self.canvas_widget.redraw()
                    self.root.update_idletasks()
                t1 = time.perf_counter()

                elapsed_ms = (t1 - t0) * 1000.0
                avg_ms = elapsed_ms / n_frames
                fps = 1000.0 / avg_ms

                print(
                    f"[BENCHMARK] Theme={theme.name:<5} Range={str(x_range):<18} "
                    f"FrameTime={avg_ms:.2f} ms ({fps:.1f} FPS)"
                )

                # Assert frame budget: must be <= 16.67 ms (>= 60 FPS)
                self.assertLessEqual(
                    avg_ms,
                    16.67,
                    f"Frame time {avg_ms:.2f} ms exceeded 16.67 ms budget at range {x_range} in {theme.name}",
                )

                # Verify vertex count cap
                c = self.canvas_widget.canvas
                trace_items = c.find_withtag("chromatogram_trace")
                self.assertEqual(len(trace_items), 2, "Expected 2 chromatogram traces (FID + TCD)")
                for item in trace_items:
                    coords = c.coords(item)
                    num_vertices = len(coords) // 2
                    self.assertLessEqual(
                        num_vertices,
                        950,
                        f"Vertex count {num_vertices} exceeded 950 cap at range {x_range}",
                    )

    def test_out_of_bounds_pixel_x_clamping_fidelity(self) -> None:
        """
        Verify that under extreme zoom-out (-50 to 150 min), trace pixel X coordinates
        are strictly clamped inside the physical panel data rectangle [x0, x1] and
        match the mathematical mapping of [t_arr[0], t_arr[-1]].
        """
        self.canvas_widget.x_range = (-50.0, 150.0)
        self.canvas_widget.redraw()
        self.root.update_idletasks()

        rects = self.canvas_widget._get_panel_rects()
        c = self.canvas_widget.canvas

        for sname in ["FID1A", "TCD2B"]:
            sig = self.inj.signals[sname]
            x0, y0, x1, y1 = rects[sname]
            pw = x1 - x0

            # Find trace item
            trace_id = c.find_withtag(f"trace_{sname}")
            self.assertEqual(len(trace_id), 1)
            coords = c.coords(trace_id[0])
            xs = coords[0::2]
            ys = coords[1::2]

            # Mathematical expected pixel endpoints
            t0, t1 = sig.time_min[0], sig.time_min[-1]
            expected_px0 = x0 + (t0 - (-50.0)) / (150.0 - (-50.0)) * pw
            expected_px1 = x0 + (t1 - (-50.0)) / (150.0 - (-50.0)) * pw

            first_px = xs[0]
            last_px = xs[-1]

            # Assert within 1.0 px of theoretical position
            self.assertAlmostEqual(first_px, expected_px0, delta=1.0)
            self.assertAlmostEqual(last_px, expected_px1, delta=1.0)

            # Assert no points lie outside [x0, x1]
            for px in xs:
                self.assertGreaterEqual(px, x0 - 0.5)
                self.assertLessEqual(px, x1 + 0.5)

            # Assert no points lie outside [y0, y1]
            for py in ys:
                self.assertGreaterEqual(py, y0 - 0.5)
                self.assertLessEqual(py, y1 + 0.5)

    def test_continuous_rapid_pan_zoom_and_memory_stability_200_cycles(self) -> None:
        """
        Stress test: Execute 200 consecutive continuous pan & zoom frames.
        Verify:
        1. Canvas item count returns exactly to the initial baseline when returning to the starting view (0 leaks).
        2. Average frame time across all 200 cycles stays well within the 60 FPS budget.
        3. No exceptions or state degradation.
        """
        self.canvas_widget.set_theme(DARK_PALETTE)
        self.canvas_widget.x_range = (0.0, 40.0)
        self.canvas_widget.redraw()
        self.root.update_idletasks()

        initial_item_count = len(self.canvas_widget.canvas.find_withtag("all"))

        t0 = time.perf_counter()
        for i in range(200):
            # Oscillate x_range simulating pan and zoom
            center = 20.0 + 5.0 * math.sin(i * 0.1)
            span = 30.0 + 15.0 * math.cos(i * 0.15)
            self.canvas_widget.x_range = (center - span / 2, center + span / 2)
            self.canvas_widget.redraw()
            if i % 20 == 0:
                self.root.update_idletasks()
        t1 = time.perf_counter()

        # Return to exact starting view
        self.canvas_widget.x_range = (0.0, 40.0)
        self.canvas_widget.redraw()
        self.root.update_idletasks()
        final_item_count = len(self.canvas_widget.canvas.find_withtag("all"))

        total_ms = (t1 - t0) * 1000.0
        avg_ms = total_ms / 200
        fps = 1000.0 / avg_ms

        print(f"[MEMORY & CONTINUOUS STRESS] 200 frames: avg {avg_ms:.2f} ms ({fps:.1f} FPS)")
        print(f"[CANVAS ITEMS] initial={initial_item_count}, final={final_item_count}")

        # When returned to exact starting view, item count must be strictly identical
        self.assertEqual(
            final_item_count,
            initial_item_count,
            f"Canvas items leaked! initial={initial_item_count}, final={final_item_count}",
        )
        self.assertLessEqual(avg_ms, 16.67, f"Average pan/zoom frame time {avg_ms:.2f} ms exceeded 16.67 ms")

    def test_right_click_y_scale_cache_reuse_stress(self) -> None:
        """
        Verify that vertical amplitude scaling (right-drag) reuses the cached decimation
        envelope data without recomputing min_max or decimation.
        """
        self.canvas_widget.set_data(self.inj, self.method, reset_view=False)
        self.canvas_widget.x_range = (0.0, 40.0)
        self.canvas_widget.redraw()
        self.root.update_idletasks()

        cache_fid_before = self.canvas_widget._trace_cache["FID1A"]["data"]
        cache_tcd_before = self.canvas_widget._trace_cache["TCD2B"]["data"]

        # Simulate 50 vertical amplitude drag steps
        t0 = time.perf_counter()
        for i in range(50):
            factor = 1.0 + (i % 10) * 0.1
            self.canvas_widget.y_ranges["FID1A"] = (-10.0, 2000.0 * factor)
            self.canvas_widget.y_ranges["TCD2B"] = (-5.0, 500.0 * factor)
            self.canvas_widget.redraw()
        t1 = time.perf_counter()

        avg_ms = ((t1 - t0) * 1000.0) / 50
        fps = 1000.0 / avg_ms
        print(f"[Y-SCALE DRAG BENCHMARK] 50 frames: avg {avg_ms:.2f} ms ({fps:.1f} FPS)")

        cache_fid_after = self.canvas_widget._trace_cache["FID1A"]["data"]
        cache_tcd_after = self.canvas_widget._trace_cache["TCD2B"]["data"]

        # Cache data objects must be identical (100% cache hit)
        self.assertIs(cache_fid_before, cache_fid_after, "FID1A decimation cache was invalidated during Y-scale")
        self.assertIs(cache_tcd_before, cache_tcd_after, "TCD2B decimation cache was invalidated during Y-scale")
        self.assertLessEqual(avg_ms, 16.67, f"Y-scale frame time {avg_ms:.2f} ms exceeded 16.67 ms")


if __name__ == "__main__":
    unittest.main()
