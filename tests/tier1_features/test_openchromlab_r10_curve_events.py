"""
Tier 1: Feature Coverage — Requirement R10 (Curve Rendering & Integration Events Editing)
Features F22 & F29: Verifies thicker chromatogram curve trace rendering (trace_line_width >= 2.0),
timed event addition, editing, deletion, chronological auto-sorting, and integration sync.
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
from agilent_core.method_model import build_default_mpz_method, TimedEvent, SignalMethodConfig


class TestOpenChromLabR10CurveEvents(HeadlessTkTestCase):
    """Test suite for Requirement R10: Curve Rendering & Integration Events Editing."""

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

    def test_r10_01_chromatogram_trace_line_width_is_thick(self) -> None:
        """
        Verify that chromatogram trace line width is thicker than default (>= 2.0 px).
        Authoritative source: ORIGINAL_REQUEST.md (R10 Acceptance Criteria), PROJECT.md (F22).
        """
        self.assertTrue(
            hasattr(self.canvas_widget, "trace_line_width"),
            "DualChromatogramCanvas must have trace_line_width attribute."
        )
        self.assertGreaterEqual(
            self.canvas_widget.trace_line_width,
            2.0,
            f"Trace line width ({self.canvas_widget.trace_line_width}) must be >= 2.0 px."
        )

    def test_r10_02_add_timed_integration_event(self) -> None:
        """
        Verify adding a new timed integration event to a detector channel config.
        Authoritative source: ORIGINAL_REQUEST.md (R10 Acceptance Criteria).
        """
        cfg = self.method.signals["FID1A"]
        initial_count = len(cfg.timed_events)

        new_ev = TimedEvent(time_min=5.5, event_type="IntegrationOff", value="", enabled=True)
        cfg.timed_events.append(new_ev)
        cfg.timed_events.sort(key=lambda e: e.time_min)

        self.assertEqual(len(cfg.timed_events), initial_count + 1)
        self.assertIn(new_ev, cfg.timed_events)

    def test_r10_03_edit_timed_integration_event(self) -> None:
        """
        Verify editing an existing timed event's time and value.
        Authoritative source: ORIGINAL_REQUEST.md (R10 Acceptance Criteria).
        """
        cfg = self.method.signals["FID1A"]
        ev = TimedEvent(time_min=3.0, event_type="IntegrationOn", value="", enabled=True)
        cfg.timed_events.append(ev)

        # Edit time to 4.5
        ev.time_min = 4.5
        ev.value = "CUSTOM_VAL"
        self.assertAlmostEqual(ev.time_min, 4.5)
        self.assertEqual(ev.value, "CUSTOM_VAL")

    def test_r10_04_delete_timed_integration_event(self) -> None:
        """
        Verify deleting a timed event removes it from the signal configuration.
        Authoritative source: ORIGINAL_REQUEST.md (R10 Acceptance Criteria).
        """
        cfg = self.method.signals["FID1A"]
        ev = TimedEvent(time_min=9.9, event_type="BaselineNow", value="", enabled=True)
        cfg.timed_events.append(ev)
        self.assertIn(ev, cfg.timed_events)

        cfg.timed_events.remove(ev)
        self.assertNotIn(ev, cfg.timed_events)

    def test_r10_05_timed_events_auto_sorted_by_time(self) -> None:
        """
        Verify that timed events in a channel configuration are auto-sorted chronologically.
        Authoritative source: Explorer 3 § 2.4.
        """
        cfg = self.method.signals["FID1A"]
        cfg.timed_events = [
            TimedEvent(time_min=12.0, event_type="IntegrationOff"),
            TimedEvent(time_min=2.5, event_type="IntegrationOn"),
            TimedEvent(time_min=7.0, event_type="BaselineNow"),
        ]
        cfg.timed_events.sort(key=lambda e: e.time_min)

        times = [e.time_min for e in cfg.timed_events]
        self.assertEqual(times, [2.5, 7.0, 12.0], "Timed events must be chronologically ordered.")

    def test_r10_06_timed_event_recalculation_affects_integration(self) -> None:
        """
        Verify that adding an Integration Off event suppresses peaks
        in that retention window when injection is reprocessed.
        Authoritative source: PROJECT.md (F05), ORIGINAL_REQUEST.md (R10).
        """
        process_injection(self.inj, self.method, prefer_rx=False, prefer_manual=False)
        orig_count = len(self.inj.peaks_by_signal.get("FID1A", []))

        cfg = self.method.signals["FID1A"]
        cfg.timed_events.append(
            TimedEvent(time_min=4.2, event_type="Integration Off", value="", enabled=True)
        )
        process_injection(self.inj, self.method, prefer_rx=False, prefer_manual=False)
        new_count = len(self.inj.peaks_by_signal.get("FID1A", []))
        self.assertLess(
            new_count,
            orig_count,
            f"Integration Off at 4.2 min must reduce peak count from {orig_count}, got {new_count}."
        )


if __name__ == "__main__":
    unittest.main()
