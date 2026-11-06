"""
Tier 1: Feature Coverage — Requirement R4 (Batch Analysis and Single-Sheet Multi-Injection Export)
Minimum 5 tests verifying sequence discovery, polarity compound matching,
batch sequence loading, single-sheet Excel schema, and dynamic SUM formulas.
"""

import os
import sys
import unittest
import openpyxl

from tests.test_helpers import (
    get_test_set_path,
    get_workspace_root,
    create_synthetic_signal,
    create_synthetic_injection,
)
from agilent_core.ch_reader import (
    find_d_folders,
    load_d_folder,
    IntegratedPeak,
)
from agilent_core.integrator import (
    identify_peaks_for_signal,
    process_injection,
)
from agilent_core.method_model import build_default_mpz_method, CompoundDef
from agilent_core.exporter import export_sequence_single_sheet_xlsx, _lookup_compound_peak


class TestR4BatchExport(unittest.TestCase):
    """Test suite for Requirement R4 batch processing and consolidated Excel export."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.method = build_default_mpz_method()
        cls.test_set_dir = get_test_set_path()

    def test_zero_config_sequence_discovery(self) -> None:
        """
        Verify that find_d_folders discovers .D directories when passed direct folder
        or when launched from workspace root (probing test-set/ or data-set/).
        Authoritative source: PROJECT.md (F01), Interface Contract § ch_reader.
        """
        # Direct folder check
        direct_folders = find_d_folders(self.test_set_dir)
        self.assertEqual(len(direct_folders), 11, f"Expected 11 .D folders in test-set, got {len(direct_folders)}")

        # Root folder zero-config discovery check
        root_folders = find_d_folders(get_workspace_root())
        self.assertGreaterEqual(
            len(root_folders),
            11,
            f"Zero-config discovery from workspace root should probe test-set/ and find 11 folders, got {len(root_folders)}"
        )

    def test_polarity_aware_compound_identification(self) -> None:
        """
        Verify that compound identification strictly enforces polarity:
        Negative compounds (H2, is_negative_peak=True) match ONLY negative peaks (is_negative=True),
        preventing misassignment to positive noise or overlapping Argon peaks.
        Authoritative source: ORIGINAL_REQUEST.md (R4), PROJECT.md (F02), explorer_survey_core § 1.4.
        """
        method = build_default_mpz_method()

        # Create two synthetic peaks at RT 8.41 min (H2 window): one positive, one negative
        pos_peak = IntegratedPeak(
            peak_id="pk_pos",
            signal_name="TCD2B",
            signal_description="TCD2 B",
            rt_min=8.415,
            begin_min=8.20,
            end_min=8.60,
            baseline_start_y=38.0,
            baseline_end_y=38.0,
            area=50.0,
            height=10.0,
            is_negative=False,  # Positive peak!
        )
        neg_peak = IntegratedPeak(
            peak_id="pk_neg",
            signal_name="TCD2B",
            signal_description="TCD2 B",
            rt_min=8.415,
            begin_min=8.20,
            end_min=8.60,
            baseline_start_y=38.0,
            baseline_end_y=38.0,
            area=146.0,
            height=22.0,
            is_negative=True,  # Negative peak!
        )

        # Test A: If only pos_peak exists, H2 must NOT match it
        identify_peaks_for_signal("TCD2B", [pos_peak], method)
        self.assertNotEqual(
            pos_peak.compound_name,
            "H2",
            "Positive peak must NOT be identified as negative compound H2"
        )

        # Test B: If neg_peak exists, H2 MUST match it
        identify_peaks_for_signal("TCD2B", [neg_peak], method)
        self.assertEqual(
            neg_peak.compound_name,
            "H2",
            "Negative peak must be identified as negative compound H2"
        )

    def test_batch_sequence_loading_and_ordering(self) -> None:
        """
        Verify that multi-injection sequence loading sorts injections in ascending
        numerical injection sequence order (120 -> 130).
        Authoritative source: PROJECT.md § Architecture, ch_reader.py.
        """
        folders = find_d_folders(self.test_set_dir)
        self.assertEqual(len(folders), 11)

        injections = [load_d_folder(f) for f in folders]
        inj_numbers = [inj.injection_number for inj in injections]

        # Injections in test-set are 120, 121, ..., 130
        expected_numbers = list(range(120, 131))
        self.assertEqual(
            inj_numbers,
            expected_numbers,
            f"Injections not in ascending numerical sequence order: {inj_numbers}"
        )

    def test_single_sheet_multi_injection_excel_schema(self) -> None:
        """
        Verify that export_sequence_single_sheet_xlsx produces a single worksheet
        named 'Compound_vs_Injections' with 88 rows and injection columns E..O.
        Authoritative source: ORIGINAL_REQUEST.md (R4), PROJECT.md (F17), explorer_survey_batch § 1.3.
        """
        folders = find_d_folders(self.test_set_dir)
        injections = [load_d_folder(f) for f in folders]
        for inj in injections:
            process_injection(inj, self.method, prefer_rx=True)

        temp_export = os.path.join(get_workspace_root(), "temp_tier1_r4_export.xlsx")
        try:
            export_sequence_single_sheet_xlsx(injections, self.method, temp_export)
            self.assertTrue(os.path.isfile(temp_export), "Exported Excel file was not created")

            wb = openpyxl.load_workbook(temp_export)
            # Must contain only one sheet named Compound_vs_Injections
            self.assertIn("Compound_vs_Injections", wb.sheetnames)
            ws = wb["Compound_vs_Injections"]

            # 88 rows: 4 blocks of (header + 16 compounds + total/gap)
            self.assertEqual(ws.max_row, 88, f"Expected 88 rows, got {ws.max_row}")
            # 15 columns: A-D (info) + E-O (11 injections)
            self.assertEqual(ws.max_column, 15, f"Expected 15 columns (4 info + 11 injections), got {ws.max_column}")

            # Verify first and last injection header
            self.assertEqual(ws["E4"].value, injections[0].sample_name)
            self.assertEqual(ws["O4"].value, injections[-1].sample_name)
        finally:
            if os.path.exists(temp_export):
                try:
                    os.remove(temp_export)
                except Exception:
                    pass

    def test_excel_dynamic_sum_formulas(self) -> None:
        """
        Verify that exported Excel sheet writes valid dynamic Excel =SUM(...) formulas
        for each injection column in the Total rows (Row 21 for Area, Row 66 for Height).
        Authoritative source: explorer_survey_batch § 1.3, MPZ_Reaction_Summary.xlsx.
        """
        folders = find_d_folders(self.test_set_dir)
        injections = [load_d_folder(f) for f in folders]
        for inj in injections:
            process_injection(inj, self.method, prefer_rx=True)

        temp_export = os.path.join(get_workspace_root(), "temp_tier1_r4_formulas.xlsx")
        try:
            export_sequence_single_sheet_xlsx(injections, self.method, temp_export)
            wb = openpyxl.load_workbook(temp_export)
            ws = wb["Compound_vs_Injections"]

            # Row 21: Area Total row
            self.assertEqual(ws["B21"].value, "Total Identified Area")
            # Columns E through O should have =SUM(E5:E20) ... =SUM(O5:O20)
            col_letters = ["E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"]
            for col in col_letters:
                cell_val = str(ws[f"{col}21"].value)
                expected_formula = f"=SUM({col}5:{col}20)"
                self.assertEqual(
                    cell_val.upper(),
                    expected_formula,
                    f"Cell {col}21 formula mismatch: expected {expected_formula}, got {cell_val}"
                )

            # Row 66: Height Total row
            for col in col_letters:
                cell_val = str(ws[f"{col}66"].value)
                expected_formula = f"=SUM({col}50:{col}65)"
                self.assertEqual(
                    cell_val.upper(),
                    expected_formula,
                    f"Cell {col}66 formula mismatch: expected {expected_formula}, got {cell_val}"
                )
        finally:
            if os.path.exists(temp_export):
                try:
                    os.remove(temp_export)
                except Exception:
                    pass

    def test_excel_export_cell_values_and_headers(self) -> None:
        """
        Verify that compound names, retention times, and info columns match method definitions.
        Authoritative source: explorer_survey_batch § 1.3.
        """
        temp_export = os.path.join(get_workspace_root(), "temp_tier1_r4_headers.xlsx")
        folders = find_d_folders(self.test_set_dir)
        inj = load_d_folder(folders[0])
        process_injection(inj, self.method, prefer_rx=True)

        try:
            export_sequence_single_sheet_xlsx([inj], self.method, temp_export)
            wb = openpyxl.load_workbook(temp_export)
            ws = wb["Compound_vs_Injections"]

            # Check Area block title
            self.assertIn("PEAK AREA MATRIX", str(ws["A1"].value))
            # Check info headers in row 4
            self.assertEqual(ws["A4"].value, "#")
            self.assertEqual(ws["B4"].value, "Compound")
            self.assertEqual(ws["C4"].value, "Signal")
            self.assertEqual(ws["D4"].value, "Exp. RT (min)")

            # Check 16 compounds in rows 5 to 20
            for idx, comp in enumerate(self.method.compounds, start=5):
                self.assertEqual(ws[f"B{idx}"].value, comp.name)
                self.assertEqual(ws[f"C{idx}"].value, comp.signal)
                self.assertAlmostEqual(float(ws[f"D{idx}"].value), comp.exp_rt_min, places=3)
        finally:
            if os.path.exists(temp_export):
                try:
                    os.remove(temp_export)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
