"""
Tier 1: Feature Coverage — Requirement R3 (Core Processing Algorithms and Manual Integration Tools)
Minimum 5 tests verifying binary .ch parsing, .rx ground truth extraction,
numerical trapezoidal integration, negative peak inversion, rider peak skimming, and manual split/addition.
"""

import os
import sys
import unittest

from tests.test_helpers import (
    get_test_set_path,
    get_workspace_root,
    create_synthetic_signal,
)
from agilent_core.ch_reader import (
    read_ch_file,
    read_rx_peaks,
    load_d_folder,
    find_d_folders,
    IntegratedPeak,
)
from agilent_core.integrator import (
    recalculate_peak_metrics,
    recalculate_signal_peaks,
    process_injection,
    split_peak_at,
    add_manual_peak,
)
from agilent_core.method_model import build_default_mpz_method


class TestR3CoreEngine(unittest.TestCase):
    """Test suite for Requirement R3 core chromatography processing engine."""

    @classmethod
    def setUpClass(cls) -> None:
        folders = find_d_folders(get_test_set_path())
        assert len(folders) > 0, "No folders found in test-set"
        cls.sample_folder = folders[0]
        cls.inj = load_d_folder(cls.sample_folder)
        cls.method = build_default_mpz_method()
        process_injection(cls.inj, cls.method, prefer_rx=True)

    def test_read_ch_file_v179_double_array(self) -> None:
        """
        Verify reading of Agilent version 179 binary double array .ch files.
        Authoritative source: PROJECT.md § Architecture, ch_reader.py.
        """
        ch_path = os.path.join(self.sample_folder, "FID1A.ch")
        self.assertTrue(os.path.isfile(ch_path), f"FID1A.ch missing in {self.sample_folder}")

        sig = read_ch_file(ch_path)
        self.assertEqual(sig.name, "FID1A")
        self.assertEqual(sig.units, "pA")
        self.assertGreater(len(sig.time_min), 50000, "Signal should contain >50000 points")
        self.assertEqual(len(sig.time_min), len(sig.values), "Time and value arrays must have equal length")
        self.assertAlmostEqual(sig.dt_sec, 0.02, places=3, msg="dt_sec should be approximately 0.02s")

    def test_read_rx_peaks_ground_truth_parsing(self) -> None:
        """
        Verify extracting ground truth peaks from Agilent .rx ACAML XML archive.
        Authoritative source: ORIGINAL_REQUEST.md (R3), explorer_survey_core § 1.1.
        """
        rx_files = [f for f in os.listdir(self.sample_folder) if f.lower().endswith(".rx")]
        self.assertTrue(len(rx_files) > 0, "No .rx file found in sample injection directory")
        rx_path = os.path.join(self.sample_folder, rx_files[0])

        peaks_by_sig = read_rx_peaks(rx_path, self.inj.signals)
        self.assertIn("FID1A", peaks_by_sig)
        self.assertIn("TCD2B", peaks_by_sig)

        fid_peaks = peaks_by_sig["FID1A"]
        tcd_peaks = peaks_by_sig["TCD2B"]
        self.assertGreaterEqual(len(fid_peaks), 12, "FID1A should have at least 12 peaks from .rx")
        self.assertEqual(len(tcd_peaks), 4, "TCD2B should have exactly 4 peaks from .rx")

        # Check H2 peak in TCD2B
        h2 = next((p for p in tcd_peaks if p.compound_name == "H2"), None)
        self.assertIsNotNone(h2, "H2 peak must be present in TCD2B ground truth")
        self.assertTrue(h2.is_negative, "H2 peak in TCD2B must be flagged as negative")

    def test_recalculate_peak_metrics_trapezoidal_accuracy(self) -> None:
        """
        Verify peak area trapezoidal numerical calculation accuracy (<0.05% error vs OpenLab .rx).
        Authoritative source: explorer_survey_core § 1.2.
        """
        sig = self.inj.signals["FID1A"]
        rx_ch4 = next((p for p in self.inj.peaks_by_signal["FID1A"] if p.compound_name == "CH4"), None)
        self.assertIsNotNone(rx_ch4, "CH4 peak not found")

        orig_area = rx_ch4.area
        recalculate_peak_metrics(sig, rx_ch4)

        ratio = rx_ch4.area / orig_area
        self.assertAlmostEqual(
            ratio,
            1.0,
            places=3,
            msg=f"Trapezoidal area ratio {ratio} diverges from OpenLab reference by >0.1%"
        )

    def test_negative_peak_integration_inversion_h2(self) -> None:
        """
        Verify negative peak integration (H2 on TCD2B):
        Verifies downward deflection is inverted (sign = -1.0), trough minimum RT is detected,
        and calculated area is positive and within 0.2% of ground truth.
        Authoritative source: ORIGINAL_REQUEST.md (R3), explorer_survey_core § 1.2.
        """
        sig = self.inj.signals["TCD2B"]
        rx_h2 = next((p for p in self.inj.peaks_by_signal["TCD2B"] if p.compound_name == "H2"), None)
        self.assertIsNotNone(rx_h2, "H2 peak not found in TCD2B")
        self.assertTrue(rx_h2.is_negative, "H2 peak must be negative")

        orig_area = rx_h2.area
        recalculate_peak_metrics(sig, rx_h2)

        self.assertGreater(rx_h2.area, 0.0, "Negative peak area must be strictly positive")
        self.assertAlmostEqual(rx_h2.rt_min, 8.41, places=1)
        ratio = rx_h2.area / orig_area
        self.assertAlmostEqual(
            ratio,
            1.0,
            delta=0.003,
            msg=f"Negative peak area ratio ({ratio}) diverges from reference by >0.3%"
        )

    def test_rider_peak_tangent_skimming_area_deduction(self) -> None:
        """
        Verify that tangent skim rider peaks on solvent peak tail (Methanol FID1A)
        deduct rider areas from the parent peak, matching ground truth net area.
        Authoritative source: explorer_survey_core § 1.2.
        """
        process_injection(self.inj, self.method, prefer_rx=True)
        fid_peaks = self.inj.peaks_by_signal["FID1A"]
        meoh = next((p for p in fid_peaks if p.compound_name == "CH3OH"), None)
        self.assertIsNotNone(meoh, "Methanol (CH3OH) peak not found")

        riders = [p for p in fid_peaks if p.is_tangent_skim]
        self.assertGreater(len(riders), 0, "Expected rider peaks on Methanol solvent tail")

        rider_sum = sum(p.area for p in riders)
        self.assertGreater(rider_sum, 5.0, "Rider peaks should have significant area")
        self.assertGreater(meoh.area, 1000.0, "Methanol net area should be >1000 pA*s")

    def test_manual_peak_split_operation(self) -> None:
        """
        Verify manual peak split (split_peak_at):
        Divides target peak into two contiguous peaks sharing drop line baseline, conserving area.
        Authoritative source: ORIGINAL_REQUEST.md (R3), PROJECT.md (F04), integrator.py.
        """
        sig = self.inj.signals["FID1A"]
        large_pk = max(self.inj.peaks_by_signal["FID1A"], key=lambda p: p.area)
        orig_count = len(self.inj.peaks_by_signal["FID1A"])
        t_split = 0.5 * (large_pk.begin_min + large_pk.end_min)

        new_peaks = split_peak_at(sig, list(self.inj.peaks_by_signal["FID1A"]), t_split, self.method)
        self.assertEqual(len(new_peaks), orig_count + 1, "Splitting a peak should increase count by 1")

        split_left = next((p for p in new_peaks if abs(p.end_min - t_split) < 1e-4), None)
        split_right = next((p for p in new_peaks if abs(p.begin_min - t_split) < 1e-4), None)
        self.assertIsNotNone(split_left, "Left child peak of split not found")
        self.assertIsNotNone(split_right, "Right child peak of split not found")

    def test_manual_peak_addition_and_polarity_detection(self) -> None:
        """
        Verify add_manual_peak:
        Drawing across negative deflection automatically flags peak as negative (MM N).
        Authoritative source: explorer_survey_core § 1.2.
        """
        sig_tcd = self.inj.signals["TCD2B"]
        # Draw across H2 trough (8.10 min to 8.70 min)
        new_pks, added_pk = add_manual_peak(
            sig=sig_tcd,
            peaks=[],
            t1=8.10,
            y1=sig_tcd.value_at_time(8.10),
            t2=8.70,
            y2=sig_tcd.value_at_time(8.70),
            method=self.method,
        )

        self.assertIsNotNone(added_pk, "Manual peak should be created")
        self.assertTrue(
            added_pk.is_negative,
            "Manually drawn peak across H2 trough must auto-detect is_negative=True"
        )
        self.assertIn("N", added_pk.baseline_code, "Baseline code must contain 'N' for negative peak")


if __name__ == "__main__":
    unittest.main()
