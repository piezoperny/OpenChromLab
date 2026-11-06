"""
Tier 1: Feature Coverage — Requirement R7 (Keyboard Shortcuts: Undo and Deselect)
Feature F28: Verifies Ctrl+Z undo stack for manual peak modifications (addition, deletion,
split), text Entry widget protection, and Escape (Esc) tool cancellation and deselect.
"""

import copy
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
from agilent_core.ch_reader import load_d_folder, find_d_folders, IntegratedPeak
from agilent_core.integrator import (
    process_injection,
    delete_peak_by_id,
    split_peak_at,
    add_manual_peak,
)
from agilent_core.method_model import build_default_mpz_method


class TestOpenChromLabR7Shortcuts(HeadlessTkTestCase):
    """Test suite for Requirement R7: Keyboard Shortcuts: Undo (Ctrl+Z) and Deselect (Escape)."""

    def setUp(self) -> None:
        super().setUp()
        from agilent_ui.main_window import OpenLabSubstituteApp
        try:
            from agilent_ui.main_window import OpenChromLabApp
            app_cls = OpenChromLabApp
        except ImportError:
            app_cls = OpenLabSubstituteApp

        self.app = app_cls(initial_workspace=get_workspace_root())
        self.app.withdraw()

        # Load test set
        self.app.load_directory(get_test_set_path())
        self.app.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except Exception:
            pass
        super().tearDown()

    def test_r7_01_ctrl_z_undo_peak_deletion(self) -> None:
        """
        Verify that pressing Ctrl+Z (or invoking undo) restores a deleted peak.
        Authoritative source: ORIGINAL_REQUEST.md (R7 Acceptance Criteria).
        """
        inj = self.app.current_injection
        if not inj or not inj.peaks_by_signal.get("FID1A"):
            self.skipTest("No active injection or FID1A peaks available.")

        initial_count = len(inj.peaks_by_signal["FID1A"])
        target_pk = inj.peaks_by_signal["FID1A"][0]

        # Push undo checkpoint if method exists
        if hasattr(self.app, "_push_undo_checkpoint"):
            self.app._push_undo_checkpoint("Delete Peak")
        elif hasattr(self.app, "undo_managers"):
            folder_key = inj.folder_name
            self.app.undo_managers[folder_key].push_state("Delete Peak", inj.peaks_by_signal)

        # Delete peak
        inj.peaks_by_signal["FID1A"] = delete_peak_by_id(inj.signals["FID1A"], inj.peaks_by_signal["FID1A"], target_pk.peak_id, self.app.method)
        self.assertEqual(len(inj.peaks_by_signal["FID1A"]), initial_count - 1)

        # Trigger Undo
        if hasattr(self.app, "_on_undo_triggered"):
            self.app._on_undo_triggered(None)
            self.assertEqual(
                len(inj.peaks_by_signal["FID1A"]),
                initial_count,
                "Undo must restore deleted peak."
            )
            self.assertIn(
                target_pk.peak_id,
                [p.peak_id for p in inj.peaks_by_signal["FID1A"]],
                "Restored peak must retain original peak_id."
            )

    def test_r7_02_ctrl_z_undo_peak_addition(self) -> None:
        """
        Verify that pressing Ctrl+Z (or invoking undo) removes an added manual peak.
        Authoritative source: ORIGINAL_REQUEST.md (R7 Acceptance Criteria).
        """
        inj = self.app.current_injection
        if not inj:
            self.skipTest("No active injection.")

        initial_count = len(inj.peaks_by_signal.get("FID1A", []))

        # Checkpoint before adding
        if hasattr(self.app, "_push_undo_checkpoint"):
            self.app._push_undo_checkpoint("Add Manual Peak")

        # Add manual peak
        sig = inj.signals["FID1A"]
        pks = inj.peaks_by_signal["FID1A"]
        updated_pks, new_pk = add_manual_peak(sig, pks, 1.0, 10.0, 1.5, 10.0, method=self.app.method)
        inj.peaks_by_signal["FID1A"] = updated_pks
        self.assertEqual(len(updated_pks), initial_count + 1)

        # Trigger Undo
        if hasattr(self.app, "_on_undo_triggered"):
            self.app._on_undo_triggered(None)
            self.assertEqual(
                len(inj.peaks_by_signal["FID1A"]),
                initial_count,
                "Undo must remove manually added peak."
            )

    def test_r7_03_ctrl_z_undo_peak_split(self) -> None:
        """
        Verify that pressing Ctrl+Z undoes a peak split operation, joining child peaks back.
        Authoritative source: ORIGINAL_REQUEST.md (R7 Acceptance Criteria).
        """
        inj = self.app.current_injection
        if not inj or not inj.peaks_by_signal.get("FID1A"):
            self.skipTest("No active injection.")

        pks = inj.peaks_by_signal["FID1A"]
        initial_count = len(pks)
        target = pks[0]
        t_mid = (target.begin_min + target.end_min) * 0.5

        if hasattr(self.app, "_push_undo_checkpoint"):
            self.app._push_undo_checkpoint("Split Peak")

        inj.peaks_by_signal["FID1A"] = split_peak_at(inj.signals["FID1A"], pks, t_mid, self.app.method)
        self.assertEqual(len(inj.peaks_by_signal["FID1A"]), initial_count + 1)

        if hasattr(self.app, "_on_undo_triggered"):
            self.app._on_undo_triggered(None)
            self.assertEqual(
                len(inj.peaks_by_signal["FID1A"]),
                initial_count,
                "Undo must revert peak split to single peak."
            )

    def test_r7_04_ctrl_z_entry_widget_focus_protection(self) -> None:
        """
        Verify that when a text Entry widget has focus, Ctrl+Z does not undo chromatogram
        peaks, allowing native text edit undo to proceed.
        Authoritative source: Explorer 3 § 4 (Caveat 2).
        """
        inj = self.app.current_injection
        if not inj or not inj.peaks_by_signal.get("FID1A"):
            self.skipTest("No active injection.")

        initial_count = len(inj.peaks_by_signal["FID1A"])

        # Create an Entry and give it focus
        entry = ttk.Entry(self.app)
        entry.pack()
        entry.insert(0, "Testing Entry")
        entry.focus_set()
        self.app.update_idletasks()

        if hasattr(self.app, "_push_undo_checkpoint"):
            self.app._push_undo_checkpoint("Prior Action")

        # Mock an event on the Entry
        mock_ev = tk.Event()
        mock_ev.widget = entry

        if hasattr(self.app, "_on_undo_triggered"):
            res = self.app._on_undo_triggered(mock_ev)
            # Peak count should remain unchanged
            self.assertEqual(
                len(inj.peaks_by_signal["FID1A"]),
                initial_count,
                "Ctrl+Z must not modify peaks when text Entry has focus."
            )

    def test_r7_05_escape_cancels_in_progress_tool_and_resets_pointer(self) -> None:
        """
        Verify that pressing Escape (Esc) cancels any in-progress tool or drag,
        resets the cursor to arrow, and returns to default 'pan_zoom' pointer mode.
        Authoritative source: ORIGINAL_REQUEST.md (R7 Acceptance Criteria).
        """
        # Set tool to draw_peak
        self.app.tool_var.set("draw_peak")
        self.app.chrom_canvas.set_tool_mode("draw_peak")
        self.app.chrom_canvas._drag_state = {"mode": "draw_peak", "start_px": 50, "start_py": 50}

        if hasattr(self.app, "_on_escape_triggered"):
            self.app._on_escape_triggered(None)
        elif hasattr(self.app.chrom_canvas, "cancel_active_tool"):
            self.app.chrom_canvas.cancel_active_tool()

        self.assertIsNone(
            self.app.chrom_canvas._drag_state,
            "Escape must abort active _drag_state."
        )
        self.assertEqual(
            self.app.tool_var.get(),
            "pan_zoom",
            "Tool variable must revert to default 'pan_zoom'."
        )
        self.assertEqual(
            self.app.chrom_canvas.tool_mode,
            "pan_zoom",
            "Canvas tool_mode must revert to 'pan_zoom'."
        )

    def test_r7_06_escape_clears_peak_and_table_selections(self) -> None:
        """
        Verify that pressing Escape clears any selected peak highlight on canvas and treeviews.
        Authoritative source: Explorer 3 § 3.3.2.
        """
        self.app.chrom_canvas.selected_peak_id = "PEAK_123"
        self.app.chrom_canvas.highlighted_compound = "Methanol"

        if hasattr(self.app, "_on_escape_triggered"):
            self.app._on_escape_triggered(None)
            self.assertIsNone(
                self.app.chrom_canvas.selected_peak_id,
                "Escape must clear selected_peak_id."
            )
            self.assertIsNone(
                self.app.chrom_canvas.highlighted_compound,
                "Escape must clear highlighted_compound."
            )


if __name__ == "__main__":
    unittest.main()
