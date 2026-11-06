"""
Tier 2: Boundary & Corner Cases Test Suite
Tests application robustness against empty data, 0 points, extreme RT bounds,
NaN/Inf inputs, negative peaks, single injection, missing channels, and malformed inputs.
"""

import math
import os
import sys
import tempfile
import unittest

from tests.test_helpers import (
    get_test_set_path,
    get_workspace_root,
    create_synthetic_signal,
    create_synthetic_injection,
)
from agilent_core.ch_reader import (
    ChromatogramSignal,
    IntegratedPeak,
    InjectionData,
    load_d_folder,
    find_d_folders,
)
from agilent_core.integrator import (
    recalculate_peak_metrics,
    split_peak_at,
    process_injection,
    save_manual_overrides,
)
from agilent_core.method_model import (
    ProcessingMethod,
    CompoundDef,
    build_default_mpz_method,
)
from agilent_core.exporter import export_sequence_single_sheet_xlsx


class TestTier2Boundaries(unittest.TestCase):
    """Test suite for Tier 2 boundary conditions and corner cases."""

    def test_empty_signal_handling(self) -> None:
        """
        Verify that ChromatogramSignal with empty time_min and values
        returns safe defaults (0 or 0.0) without raising IndexError or UnboundLocalError.
        Authoritative source: PROJECT.md (F03), explorer_survey_core § 1.4.
        """
        empty_sig = ChromatogramSignal(
            name="EMPTY",
            description="Empty Signal",
            units="pA",
            sample_name="None",
            acq_date="",
            time_min=[],
            values=[],
            dt_sec=0.02,
        )

        idx = empty_sig.index_at_time(5.0)
        self.assertEqual(idx, 0, f"Empty signal index_at_time should return 0, got {idx}")

        val = empty_sig.value_at_time(5.0)
        self.assertEqual(val, 0.0, f"Empty signal value_at_time should return 0.0, got {val}")

    def test_single_point_signal(self) -> None:
        """
        Verify that ChromatogramSignal with exactly 1 point safely returns that value.
        Authoritative source: PROJECT.md (F03).
        """
        single_sig = ChromatogramSignal(
            name="SINGLE",
            description="Single Point Signal",
            units="pA",
            sample_name="Single",
            acq_date="",
            time_min=[5.0],
            values=[42.5],
            dt_sec=0.02,
        )

        idx = single_sig.index_at_time(10.0)
        self.assertEqual(idx, 0)
        val = single_sig.value_at_time(10.0)
        self.assertEqual(val, 42.5)

    def test_nan_and_inf_resilience(self) -> None:
        """
        Verify that index_at_time and value_at_time handle float('nan'), float('inf'),
        and float('-inf') without crashing with ValueError or OverflowError.
        Authoritative source: PROJECT.md (F03), explorer_survey_core § 1.4.
        """
        sig = create_synthetic_signal("FID1A", t_start=0.0, t_end=10.0, dt_s=0.02, baseline=12.0)

        for bad_val in (float("nan"), float("inf"), float("-inf")):
            # index_at_time must not raise
            try:
                idx = sig.index_at_time(bad_val)
                self.assertIsInstance(idx, int)
                self.assertGreaterEqual(idx, 0)
                self.assertLess(idx, len(sig.time_min))
            except Exception as exc:
                self.fail(f"index_at_time raised {type(exc).__name__} on input {bad_val}")

            # value_at_time must not raise
            try:
                val = sig.value_at_time(bad_val)
                self.assertIsInstance(val, float)
            except Exception as exc:
                self.fail(f"value_at_time raised {type(exc).__name__} on input {bad_val}")

    def test_inverted_peak_bounds_normalized(self) -> None:
        """
        Verify that peak with begin_min > end_min is automatically normalized or safely handled.
        Authoritative source: explorer_survey_core § 5.2.
        """
        sig = create_synthetic_signal("FID1A", t_start=0.0, t_end=10.0, dt_s=0.02, baseline=10.0)
        pk_inv = IntegratedPeak(
            peak_id="inv1",
            signal_name="FID1A",
            signal_description="FID1 A",
            rt_min=5.0,
            begin_min=5.5,  # Inverted: begin > end!
            end_min=4.5,
            baseline_start_y=10.0,
            baseline_end_y=10.0,
            area=0.0,
            height=0.0,
        )

        recalculate_peak_metrics(sig, pk_inv)
        # begin_min should now be <= end_min
        self.assertLessEqual(
            pk_inv.begin_min,
            pk_inv.end_min,
            "Inverted peak bounds must be normalized so begin_min <= end_min"
        )

    def test_split_peak_outside_boundaries(self) -> None:
        """
        Verify that split_peak_at called with t_split outside any peak boundary
        returns peak list unchanged without crash.
        Authoritative source: explorer_survey_core § 5.2.
        """
        sig = create_synthetic_signal("FID1A", t_start=0.0, t_end=10.0)
        method = build_default_mpz_method()
        pk = IntegratedPeak(
            peak_id="p1",
            signal_name="FID1A",
            signal_description="FID1 A",
            rt_min=5.0,
            begin_min=4.8,
            end_min=5.2,
            baseline_start_y=10.0,
            baseline_end_y=10.0,
            area=20.0,
            height=5.0,
        )

        # Split at 10.0 min (far outside peak bounds [4.8, 5.2])
        pks = split_peak_at(sig, [pk], 10.0, method)
        self.assertEqual(len(pks), 1, "Split peak outside bounds should not alter peak list")
        self.assertEqual(pks[0].peak_id, "p1")

    def test_extreme_retention_times(self) -> None:
        """
        Verify that index_at_time and value_at_time clamp extreme RT inputs (-1000m, +10000m)
        to the first and last array indices without index out of range errors.
        Authoritative source: PROJECT.md (F03).
        """
        sig = create_synthetic_signal("FID1A", t_start=0.0, t_end=20.0, dt_s=0.02)
        n = len(sig.time_min)

        idx_low = sig.index_at_time(-1000.0)
        self.assertEqual(idx_low, 0)

        idx_high = sig.index_at_time(10000.0)
        self.assertEqual(idx_high, n - 1)

        val_low = sig.value_at_time(-1000.0)
        self.assertEqual(val_low, sig.values[0])

        val_high = sig.value_at_time(10000.0)
        self.assertEqual(val_high, sig.values[-1])

    def test_missing_detector_channels(self) -> None:
        """
        Verify that InjectionData missing one of the standard channels (e.g. only FID1A,
        no TCD2B) can be processed and exported without unhandled KeyError.
        Authoritative source: ORIGINAL_REQUEST.md (Acceptance Criteria), PROJECT.md (F03).
        """
        sig_fid = create_synthetic_signal("FID1A")
        inj_fid_only = create_synthetic_injection(
            folder_name="FID_Only_Sample.D",
            signals={"FID1A": sig_fid},
            peaks_by_signal={"FID1A": []},
        )
        method = build_default_mpz_method()

        # Should not crash on process_injection
        try:
            process_injection(inj_fid_only, method, prefer_rx=False)
        except Exception as exc:
            self.fail(f"process_injection failed on missing TCD2B channel: {exc}")

        # Should not crash on Excel export
        temp_out = os.path.join(get_workspace_root(), "temp_fid_only_export.xlsx")
        try:
            export_sequence_single_sheet_xlsx([inj_fid_only], method, temp_out)
            self.assertTrue(os.path.isfile(temp_out))
        except Exception as exc:
            self.fail(f"export_sequence_single_sheet_xlsx failed on missing channel: {exc}")
        finally:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass

    def test_single_injection_sequence_export(self) -> None:
        """
        Verify that exporting a sequence of exactly 1 injection produces
        a valid Excel sheet with exactly 1 injection column (Column E) and 88 rows.
        Authoritative source: ORIGINAL_REQUEST.md (Acceptance Criteria), explorer_survey_batch § 1.3.
        """
        folders = find_d_folders(get_test_set_path())
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()
        process_injection(inj, method, prefer_rx=True)

        temp_out = os.path.join(get_workspace_root(), "temp_single_inj_export.xlsx")
        try:
            export_sequence_single_sheet_xlsx([inj], method, temp_out)
            import openpyxl

            wb = openpyxl.load_workbook(temp_out)
            ws = wb["Compound_vs_Injections"]
            self.assertEqual(ws.max_row, 88)
            # 4 info columns + 1 injection column = 5 columns (A-E)
            self.assertEqual(ws.max_column, 5)
            self.assertEqual(ws["E4"].value, inj.sample_name)
            self.assertEqual(str(ws["E21"].value).upper(), "=SUM(E5:E20)")
        finally:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass

    def test_malformed_json_method_resilience(self) -> None:
        """
        Verify that ProcessingMethod.load_json handles missing fields,
        unexpected fields, or malformed schema gracefully with defaults.
        Authoritative source: PROJECT.md (F03), explorer_survey_core § 1.4.
        """
        malformed_json_content = """
        {
            "name": "Malformed_Method",
            "compounds": [
                {
                    "name": "Minimal_Compound",
                    "signal": "FID1A",
                    "exp_rt_min": 5.0
                },
                {
                    "name": "Extra_Keys_Compound",
                    "signal": "TCD2B",
                    "exp_rt_min": 8.0,
                    "unexpected_unknown_key": "some_value"
                }
            ]
        }
        """
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write(malformed_json_content)
            temp_path = tf.name

        try:
            method = ProcessingMethod.load_json(temp_path)
            self.assertEqual(method.name, "Malformed_Method")
            self.assertEqual(len(method.compounds), 2)
            self.assertEqual(method.compounds[0].name, "Minimal_Compound")
            self.assertEqual(method.compounds[1].name, "Extra_Keys_Compound")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_export_permission_error_handling(self) -> None:
        """
        Verify that export_sequence_single_sheet_xlsx or save_manual_overrides handles
        PermissionError gracefully (e.g. file locked by Excel or read-only directory).
        Authoritative source: PROJECT.md (F06), explorer_survey_batch § 2.4.
        """
        folders = find_d_folders(get_test_set_path())
        inj = load_d_folder(folders[0])
        method = build_default_mpz_method()

        # Test writing to an invalid / protected path or locked handle
        temp_locked = os.path.join(get_workspace_root(), "temp_locked.xlsx")
        # Create and hold an exclusive file handle to simulate Excel file lock
        with open(temp_locked, "w") as locked_handle:
            # Attempting to export to the locked file must catch or raise descriptive PermissionError
            try:
                export_sequence_single_sheet_xlsx([inj], method, temp_locked)
            except PermissionError as exc:
                # PermissionError properly caught and identified
                self.assertIn("Permission denied", str(exc))
            except Exception as exc:
                self.fail(f"Expected PermissionError on locked file, got: {type(exc).__name__}: {exc}")

        if os.path.exists(temp_locked):
            try:
                os.remove(temp_locked)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
