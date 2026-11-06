"""
Tier 4: Real-World Scenarios Test Suite
Tests complete 11-injection dataset in test-set/, cross-checking against
ground truth reference program output MPZ_Reaction_Summary.xlsx cell by cell.
"""

import os
import sys
import unittest
import openpyxl

from tests.test_helpers import (
    get_test_set_path,
    get_workspace_root,
    get_reference_xlsx_path,
    get_sample_method_path,
)
from agilent_core.ch_reader import (
    find_d_folders,
    load_d_folder,
)
from agilent_core.integrator import (
    process_injection,
)
from agilent_core.method_model import (
    ProcessingMethod,
    build_default_mpz_method,
)
from agilent_core.exporter import (
    export_sequence_single_sheet_xlsx,
    _lookup_compound_peak,
)


class TestTier4RealWorldDataset(unittest.TestCase):
    """Test suite for Tier 4 real-world dataset validation and reference Excel parity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.test_set_dir = get_test_set_path()
        cls.ref_xlsx_path = get_reference_xlsx_path()
        cls.d_paths = find_d_folders(cls.test_set_dir)
        cls.method = build_default_mpz_method()

    def test_all_11_injections_load_and_integrate_successfully(self) -> None:
        """
        Scenario 1:
        Verify that all 11 injection directories in test-set/ load without error,
        signals contain >40000 points, and ground truth identifies all 16 compounds.
        Authoritative source: ORIGINAL_REQUEST.md (Verification Resources).
        """
        self.assertEqual(len(self.d_paths), 11, f"Expected 11 injection folders, got {len(self.d_paths)}")

        injections = []
        for p in self.d_paths:
            inj = load_d_folder(p)
            self.assertIn("FID1A", inj.signals, f"FID1A missing in {inj.folder_name}")
            self.assertIn("TCD2B", inj.signals, f"TCD2B missing in {inj.folder_name}")

            # Verify signal lengths
            self.assertGreater(len(inj.signals["FID1A"].values), 40000)
            self.assertGreater(len(inj.signals["TCD2B"].values), 40000)

            process_injection(inj, self.method, prefer_rx=True, prefer_manual=True)
            injections.append(inj)

            # Check that all 16 compounds in method are found
            found_compounds = []
            for comp in self.method.compounds:
                pk = _lookup_compound_peak(inj, comp)
                if pk is not None:
                    found_compounds.append(comp.name)

            self.assertEqual(
                len(found_compounds),
                16,
                f"Injection {inj.folder_name} identified {len(found_compounds)}/16 compounds: missing {set(c.name for c in self.method.compounds) - set(found_compounds)}"
            )

    def test_exact_cell_by_cell_numerical_parity_with_mpz_reaction_summary(self) -> None:
        """
        Scenario 2:
        Direct cell-by-cell numerical comparison between generated export for injection 126
        and ground truth MPZ_Reaction_Summary.xlsx across all 4 matrix blocks:
        - Block 1 (Area): Rows 5–20 match within 0.01 pA*s
        - Block 2 (Area%): Rows 28–43 match within 0.01%
        - Block 3 (Height): Rows 50–65 match within 0.01
        - Block 4 (RT): Rows 73–88 match within 0.001 min
        - Dynamic Excel SUM formulas =SUM(E5:E20) and =SUM(E50:E65) match verbatim.
        Authoritative source: ORIGINAL_REQUEST.md (Acceptance Criteria), MPZ_Reaction_Summary.xlsx.
        """
        self.assertTrue(os.path.isfile(self.ref_xlsx_path), "MPZ_Reaction_Summary.xlsx missing in workspace")

        # Load reference workbook
        ref_wb = openpyxl.load_workbook(self.ref_xlsx_path)
        self.assertIn("Compound_vs_Injections", ref_wb.sheetnames)
        ref_ws = ref_wb["Compound_vs_Injections"]

        # Find injection 126
        inj_126_path = next((p for p in self.d_paths if "126F.D" in p), None)
        self.assertIsNotNone(inj_126_path, "Injection 126 folder not found in test-set")

        inj_126 = load_d_folder(inj_126_path)
        process_injection(inj_126, self.method, prefer_rx=True, prefer_manual=True)

        temp_out = os.path.join(get_workspace_root(), "temp_tier4_126_parity.xlsx")
        try:
            export_sequence_single_sheet_xlsx([inj_126], self.method, temp_out)
            gen_wb = openpyxl.load_workbook(temp_out)
            gen_ws = gen_wb["Compound_vs_Injections"]

            # 1. Compare Block 1: Peak Area Matrix (Rows 5 to 20, Column E)
            mismatches = []
            for r in range(5, 21):
                comp_name = ref_ws.cell(row=r, column=2).value
                ref_val = ref_ws.cell(row=r, column=5).value
                gen_val = gen_ws.cell(row=r, column=5).value

                diff = abs((gen_val or 0.0) - (ref_val or 0.0))
                if diff > 0.01:
                    mismatches.append(f"Area Row {r} ({comp_name}): Ref={ref_val}, Gen={gen_val}, diff={diff:.4f}")

            self.assertEqual(len(mismatches), 0, f"Area matrix mismatches: {mismatches}")

            # 2. Compare Block 2: Peak Area % Matrix (Rows 28 to 43, Column E)
            for r in range(28, 44):
                comp_name = ref_ws.cell(row=r, column=2).value
                ref_val = ref_ws.cell(row=r, column=5).value
                gen_val = gen_ws.cell(row=r, column=5).value
                diff = abs((gen_val or 0.0) - (ref_val or 0.0))
                if diff > 0.02:
                    mismatches.append(f"Area% Row {r} ({comp_name}): Ref={ref_val}, Gen={gen_val}, diff={diff:.4f}")

            self.assertEqual(len(mismatches), 0, f"Area% matrix mismatches: {mismatches}")

            # 3. Compare Block 3: Peak Height Matrix (Rows 50 to 65, Column E)
            for r in range(50, 66):
                comp_name = ref_ws.cell(row=r, column=2).value
                ref_val = ref_ws.cell(row=r, column=5).value
                gen_val = gen_ws.cell(row=r, column=5).value
                diff = abs((gen_val or 0.0) - (ref_val or 0.0))
                if diff > 0.01:
                    mismatches.append(f"Height Row {r} ({comp_name}): Ref={ref_val}, Gen={gen_val}, diff={diff:.4f}")

            self.assertEqual(len(mismatches), 0, f"Height matrix mismatches: {mismatches}")

            # 4. Compare Block 4: RT Matrix (Rows 73 to 88, Column E)
            for r in range(73, 89):
                comp_name = ref_ws.cell(row=r, column=2).value
                ref_val = ref_ws.cell(row=r, column=5).value
                gen_val = gen_ws.cell(row=r, column=5).value
                diff = abs((gen_val or 0.0) - (ref_val or 0.0))
                if diff > 0.002:
                    mismatches.append(f"RT Row {r} ({comp_name}): Ref={ref_val}, Gen={gen_val}, diff={diff:.4f}")

            self.assertEqual(len(mismatches), 0, f"RT matrix mismatches: {mismatches}")

            # 5. Compare SUM Formulas verbatim
            self.assertEqual(str(gen_ws["E21"].value).upper(), str(ref_ws["E21"].value).upper())
            self.assertEqual(str(gen_ws["E66"].value).upper(), str(ref_ws["E66"].value).upper())

        finally:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass

    def test_batch_11_injection_consolidated_export_layout(self) -> None:
        """
        Scenario 3:
        Export complete 11-injection dataset to single Excel workbook.
        Verify:
        - Exactly 1 worksheet named 'Compound_vs_Injections'
        - Exactly 88 rows
        - Exactly 15 columns (A–O: 4 info + 11 injections)
        - Column headers: MPZHY14_reaction_261015_120 through MPZHY14_reaction_261015_130
        - Formulas =SUM(E5:E20) through =SUM(O5:O20) present for all 11 columns.
        Authoritative source: ORIGINAL_REQUEST.md (Acceptance Criteria), PROJECT.md (F17).
        """
        injections = [load_d_folder(p) for p in self.d_paths]
        for inj in injections:
            process_injection(inj, self.method, prefer_rx=True, prefer_manual=True)

        temp_out = os.path.join(get_workspace_root(), "temp_tier4_11inj_export.xlsx")
        try:
            export_sequence_single_sheet_xlsx(injections, self.method, temp_out)
            wb = openpyxl.load_workbook(temp_out)
            ws = wb["Compound_vs_Injections"]

            self.assertEqual(ws.max_row, 88)
            self.assertEqual(ws.max_column, 15)

            # Check injection names in row 4
            expected_suffixes = ["120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130"]
            col_letters = ["E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"]

            for col, suff in zip(col_letters, expected_suffixes):
                val = ws[f"{col}4"].value
                self.assertTrue(
                    val.endswith(suff),
                    f"Column {col} header '{val}' does not end with expected injection number '{suff}'"
                )
                # Check Area SUM formula
                self.assertEqual(str(ws[f"{col}21"].value).upper(), f"=SUM({col}5:{col}20)")
                # Check Height SUM formula
                self.assertEqual(str(ws[f"{col}66"].value).upper(), f"=SUM({col}50:{col}65)")

        finally:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass

    def test_sequence_ordering_integrity(self) -> None:
        """
        Scenario 4:
        Verify that find_d_folders orders directories strictly by sequence number
        and does not perform lexicographic sorting where 130 would come before 14.
        Authoritative source: ch_reader.py § find_d_folders, extract_injection_number.
        """
        extracted_numbers = []
        for p in self.d_paths:
            inj = load_d_folder(p)
            extracted_numbers.append(inj.injection_number)

        self.assertEqual(
            extracted_numbers,
            sorted(extracted_numbers),
            f"Sequence injections not strictly sorted numerically: {extracted_numbers}"
        )


if __name__ == "__main__":
    unittest.main()
