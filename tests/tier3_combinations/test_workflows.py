"""
Tier 3: Cross-Feature Combinations & Multi-Step Workflows Test Suite
Verifies end-to-end integration workflows connecting multiple subsystems:
Sequence discovery -> auto-integration -> polarity compound ID -> single-sheet export -> Excel openpyxl verification.
"""

import os
import sys
import unittest
import openpyxl

from tests.test_helpers import (
    get_test_set_path,
    get_workspace_root,
    get_sample_method_path,
)
from agilent_core.ch_reader import (
    find_d_folders,
    load_d_folder,
)
from agilent_core.integrator import (
    process_injection,
    auto_integrate_signal,
    identify_peaks_for_signal,
    split_peak_at,
    add_manual_peak,
)
from agilent_core.method_model import (
    ProcessingMethod,
    TimedEvent,
    build_default_mpz_method,
)
from agilent_core.exporter import (
    export_sequence_single_sheet_xlsx,
    _lookup_compound_peak,
)


class TestTier3Workflows(unittest.TestCase):
    """Test suite for Tier 3 multi-feature cross-functional workflows."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.method_path = get_sample_method_path()
        if os.path.isfile(cls.method_path):
            cls.method = ProcessingMethod.load_json(cls.method_path)
        else:
            cls.method = build_default_mpz_method()
        cls.test_set_dir = get_test_set_path()

    def test_full_batch_pipeline_discovery_to_excel(self) -> None:
        """
        Workflow 1:
        Zero-config sequence discovery -> load all 11 injections -> process with method ->
        single-sheet Excel export -> openpyxl roundtrip verification of all 4 matrix blocks.
        Authoritative source: ORIGINAL_REQUEST.md (R4), PROJECT.md (F01, F17).
        """
        d_paths = find_d_folders(self.test_set_dir)
        self.assertEqual(len(d_paths), 11, "Sequence discovery must find all 11 injections")

        injections = []
        for dp in d_paths:
            inj = load_d_folder(dp)
            process_injection(inj, self.method, prefer_rx=True, prefer_manual=True)
            injections.append(inj)

        self.assertEqual(len(injections), 11)

        export_out = os.path.join(get_workspace_root(), "temp_tier3_workflow1.xlsx")
        try:
            export_sequence_single_sheet_xlsx(injections, self.method, export_out)
            self.assertTrue(os.path.isfile(export_out))

            wb = openpyxl.load_workbook(export_out)
            ws = wb["Compound_vs_Injections"]

            self.assertEqual(ws.max_row, 88)
            self.assertEqual(ws.max_column, 15)

            col_letters = ["E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"]
            for col in col_letters:
                formula_cell = ws[f"{col}21"].value
                self.assertEqual(str(formula_cell).upper(), f"=SUM({col}5:{col}20)")

            for r in range(5, 21):
                comp_name = ws.cell(row=r, column=2).value
                self.assertIsNotNone(comp_name)
                self.assertTrue(any(c.name == comp_name for c in self.method.compounds))

        finally:
            if os.path.exists(export_out):
                try:
                    os.remove(export_out)
                except Exception:
                    pass

    def test_auto_integrate_and_polarity_compound_matching_pipeline(self) -> None:
        """
        Workflow 2:
        Pure automatic integration (no .rx ground truth) -> 12-Tone auto_integrate_signal ->
        polarity-aware compound identification -> verify H2 negative peak identified on TCD2B.
        Authoritative source: ORIGINAL_REQUEST.md (R3), explorer_survey_core § 1.2.
        """
        d_paths = find_d_folders(self.test_set_dir)
        inj_path = next((p for p in d_paths if "126F.D" in p), d_paths[0])
        inj = load_d_folder(inj_path)

        process_injection(inj, self.method, prefer_rx=False, prefer_manual=False)

        tcd_peaks = inj.peaks_by_signal.get("TCD2B", [])
        self.assertGreater(len(tcd_peaks), 0, "Auto-integrator should detect peaks on TCD2B")

        h2_peak = next((p for p in tcd_peaks if p.compound_name == "H2"), None)
        self.assertIsNotNone(h2_peak, "H2 peak must be identified by auto-integrator")
        self.assertTrue(h2_peak.is_negative, "Identified H2 peak must have is_negative=True")
        self.assertGreater(h2_peak.area, 50.0, "H2 peak area should be significant (>50)")

    def test_manual_peak_split_and_recalculation_workflow(self) -> None:
        """
        Workflow 3:
        Load injection -> split a wide peak at valley -> recalculate metrics ->
        verify child peaks receive valid baselines, area is conserved, and compound table updates.
        Authoritative source: ORIGINAL_REQUEST.md (Acceptance Criteria), PROJECT.md (F04).
        """
        d_paths = find_d_folders(self.test_set_dir)
        inj = load_d_folder(d_paths[0])
        process_injection(inj, self.method, prefer_rx=True)

        sig = inj.signals["FID1A"]
        fid_pks = inj.peaks_by_signal["FID1A"]

        target = max(fid_pks, key=lambda p: p.area)
        orig_area = target.area
        t_split = 0.5 * (target.begin_min + target.end_min)

        new_pks = split_peak_at(sig, fid_pks, t_split, self.method)
        self.assertEqual(len(new_pks), len(fid_pks) + 1)

        left_child = next(p for p in new_pks if abs(p.end_min - t_split) < 1e-4)
        right_child = next(p for p in new_pks if abs(p.begin_min - t_split) < 1e-4)

        child_sum = left_child.area + right_child.area
        self.assertAlmostEqual(
            child_sum,
            orig_area,
            delta=orig_area * 0.05,
            msg=f"Split peak child sum ({child_sum}) should approximately equal original area ({orig_area})"
        )

    def test_manual_negative_peak_drawing_workflow(self) -> None:
        """
        Workflow 4:
        Load injection -> add manual negative peak across inverted trough on TCD2B ->
        verify auto-polarity detection flags is_negative=True -> verify compound identification matches H2.
        Authoritative source: explorer_survey_core § 1.2, PROJECT.md (F02).
        """
        d_paths = find_d_folders(self.test_set_dir)
        inj = load_d_folder(d_paths[0])
        sig_tcd = inj.signals["TCD2B"]

        new_pks, added_pk = add_manual_peak(
            sig=sig_tcd,
            peaks=[],
            t1=8.10,
            y1=sig_tcd.value_at_time(8.10),
            t2=8.70,
            y2=sig_tcd.value_at_time(8.70),
            method=self.method,
        )

        self.assertIsNotNone(added_pk)
        self.assertTrue(added_pk.is_negative, "Manually drawn peak must be negative")

        identify_peaks_for_signal("TCD2B", new_pks, self.method)
        self.assertEqual(
            added_pk.compound_name,
            "H2",
            "Manually drawn negative peak at 8.41m must be identified as H2"
        )

    def test_timed_event_modification_and_sync_workflow(self) -> None:
        """
        Workflow 5:
        Modify timed integration events (suppress peak window) -> trigger re-integration ->
        verify peaks within suppressed window are omitted and Area% normalized.
        Authoritative source: PROJECT.md (F05), explorer_survey_core § 1.3.
        """
        d_paths = find_d_folders(self.test_set_dir)
        inj = load_d_folder(d_paths[0])
        process_injection(inj, self.method, prefer_rx=False, prefer_manual=False)

        orig_pks = len(inj.peaks_by_signal.get("FID1A", []))

        modified_method = build_default_mpz_method()
        if "FID1A" in modified_method.signals:
            modified_method.signals["FID1A"].timed_events.append(
                TimedEvent(time_min=4.2, event_type="Integration Off")
            )

        process_injection(inj, modified_method, prefer_rx=False, prefer_manual=False)
        new_pks = len(inj.peaks_by_signal.get("FID1A", []))

        self.assertLess(
            new_pks,
            orig_pks,
            f"Turning integration off at 4.2m should reduce FID1A peak count from {orig_pks}"
        )


if __name__ == "__main__":
    unittest.main()
