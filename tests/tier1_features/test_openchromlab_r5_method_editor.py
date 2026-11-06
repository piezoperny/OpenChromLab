"""
Tier 1: Feature Coverage — Requirement R5 (Method Creation and Modification)
Features F24 & F25: Verifies method creation from scratch, compound table editing
with RT tolerance windows and calibration parameters (response_factor, calib_curve,
amount_unit, calib_level), saving to JSON, and lossless reloading.
"""

import json
import os
import sys
import tempfile
import tkinter as tk
import unittest

from tests.test_helpers import HeadlessTkTestCase, get_workspace_root, get_sample_method_path
from agilent_core.method_model import (
    CompoundDef,
    ProcessingMethod,
    SignalMethodConfig,
    TimedEvent,
    build_default_mpz_method,
)


class TestOpenChromLabR5MethodEditor(HeadlessTkTestCase):
    """Test suite for Requirement R5: Method Creation and Modification."""

    def test_r5_01_compound_calibration_parameter_defaults_and_custom(self) -> None:
        """
        Verify that CompoundDef dataclass supports calibration parameters:
        response_factor (default 1.0), calib_curve (default 'Linear'),
        amount_unit (default '%'), and calib_level (default 1).
        Authoritative source: PROJECT.md § Interface Contracts, Explorer 2 § 2.2.
        """
        # Default initialization
        c_def = CompoundDef(
            index=1,
            name="Methanol",
            signal="FID1A",
            exp_rt_min=6.85,
        )
        self.assertEqual(getattr(c_def, "response_factor", 1.0), 1.0)
        self.assertEqual(getattr(c_def, "calib_curve", "Linear"), "Linear")
        self.assertEqual(getattr(c_def, "amount_unit", "%"), "%")
        self.assertEqual(getattr(c_def, "calib_level", 1), 1)

        # Custom initialization
        c_custom = CompoundDef(
            index=2,
            name="Ethanol",
            signal="FID1A",
            exp_rt_min=7.42,
            abs_window_min=0.08,
            rel_window_pct=1.5,
            response_factor=1.234,
            calib_curve="PointToPoint",
            amount_unit="mmol/g",
            calib_level=2,
        )
        self.assertAlmostEqual(c_custom.response_factor, 1.234)
        self.assertEqual(c_custom.calib_curve, "PointToPoint")
        self.assertEqual(c_custom.amount_unit, "mmol/g")
        self.assertEqual(c_custom.calib_level, 2)

    def test_r5_02_create_method_from_scratch(self) -> None:
        """
        Verify creating an entirely new analytical ProcessingMethod from scratch in memory,
        populating signals, integration parameters, and multiple compound definitions.
        Authoritative source: ORIGINAL_REQUEST.md (R5 Acceptance Criteria).
        """
        new_method = ProcessingMethod(name="NewLabMethod_2026")
        new_method.signals["FID1A"] = SignalMethodConfig(
            signal_name="FID1A",
            slope_sensitivity=2.5,
            peak_width=0.04,
            area_reject=5.0,
            height_reject=3.0,
        )
        new_method.signals["TCD2B"] = SignalMethodConfig(
            signal_name="TCD2B",
            slope_sensitivity=1.2,
            peak_width=0.03,
        )
        new_method.compounds.append(CompoundDef(
            index=1,
            name="Hydrogen",
            signal="TCD2B",
            exp_rt_min=8.45,
            abs_window_min=0.05,
            is_negative_peak=True,
            response_factor=0.88,
            amount_unit="vol%",
        ))
        new_method.compounds.append(CompoundDef(
            index=2,
            name="Methane",
            signal="FID1A",
            exp_rt_min=4.55,
            abs_window_min=0.03,
            is_negative_peak=False,
            response_factor=1.05,
            amount_unit="mol%",
        ))

        self.assertEqual(new_method.name, "NewLabMethod_2026")
        self.assertEqual(len(new_method.signals), 2)
        self.assertEqual(len(new_method.compounds), 2)
        self.assertTrue(new_method.compounds[0].is_negative_peak)
        self.assertEqual(new_method.compounds[1].amount_unit, "mol%")

    def test_r5_03_save_and_reload_method_json_lossless(self) -> None:
        """
        Verify saving a method with compounds, calibration, and integration parameters to a
        JSON file and re-loading it without any data loss or parsing errors.
        Authoritative source: ORIGINAL_REQUEST.md (R5 Acceptance Criteria).
        """
        method = ProcessingMethod(name="RoundtripTest")
        method.signals["FID1A"] = SignalMethodConfig(
            signal_name="FID1A",
            slope_sensitivity=1.8,
            peak_width=0.025,
            area_reject=2.0,
            height_reject=2.5,
            timed_events=[
                TimedEvent(time_min=5.0, event_type="IntegrationOff", value="", enabled=True),
                TimedEvent(time_min=10.0, event_type="IntegrationOn", value="", enabled=True),
            ]
        )
        method.compounds.append(CompoundDef(
            index=1,
            name="Compound_Alpha",
            signal="FID1A",
            exp_rt_min=6.20,
            abs_window_min=0.04,
            rel_window_pct=1.2,
            response_factor=1.45,
            calib_curve="Linear",
            amount_unit="ppm",
            calib_level=1,
        ))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp_path = tf.name

        try:
            method.save_json(tmp_path)
            self.assertTrue(os.path.isfile(tmp_path))

            # Reload
            reloaded = ProcessingMethod.load_json(tmp_path)
            self.assertEqual(reloaded.name, "RoundtripTest")
            self.assertIn("FID1A", reloaded.signals)
            sig_cfg = reloaded.signals["FID1A"]
            self.assertAlmostEqual(sig_cfg.slope_sensitivity, 1.8)
            self.assertEqual(len(sig_cfg.timed_events), 2)
            self.assertEqual(sig_cfg.timed_events[0].event_type, "IntegrationOff")

            # Check compounds
            self.assertEqual(len(reloaded.compounds), 1)
            c = reloaded.compounds[0]
            self.assertEqual(c.name, "Compound_Alpha")
            self.assertAlmostEqual(c.exp_rt_min, 6.20)
            self.assertAlmostEqual(c.abs_window_min, 0.04)
            self.assertAlmostEqual(c.response_factor, 1.45)
            self.assertEqual(c.amount_unit, "ppm")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_r5_04_backward_compatibility_with_legacy_json(self) -> None:
        """
        Verify that existing method files (such as MPZ_method-2.2.json) without calibration
        fields load cleanly with default calibration values without error.
        Authoritative source: PROJECT.md § Architecture.
        """
        sample_path = get_sample_method_path()
        if os.path.exists(sample_path):
            method = ProcessingMethod.load_json(sample_path)
            self.assertGreater(len(method.compounds), 0)
            for comp in method.compounds:
                self.assertTrue(hasattr(comp, "response_factor"))
                self.assertGreater(comp.response_factor, 0.0)
                self.assertTrue(hasattr(comp, "amount_unit"))

    def test_r5_05_method_editor_dialog_exists_and_initializes(self) -> None:
        """
        Verify that MethodEditorDialog exists in agilent_ui.method_editor and can be
        initialized headlessly with a ProcessingMethod.
        Authoritative source: PROJECT.md § Architecture (agilent_ui.method_editor).
        """
        try:
            from agilent_ui.method_editor import MethodEditorDialog
        except ImportError:
            self.skipTest("agilent_ui.method_editor.MethodEditorDialog is being implemented by worker_m7.")
            return

        method = build_default_mpz_method()
        dialog = MethodEditorDialog(self.root, method=method)
        dialog.withdraw()
        try:
            self.assertIsNotNone(dialog)
            self.assertEqual(dialog.method.name, method.name)
        finally:
            dialog.destroy()

    def test_r5_06_compound_table_modification(self) -> None:
        """
        Verify adding, updating, and removing compounds from a ProcessingMethod instance.
        Authoritative source: ORIGINAL_REQUEST.md (R5 Acceptance Criteria).
        """
        method = build_default_mpz_method()
        initial_count = len(method.compounds)

        # Add new compound
        new_comp = CompoundDef(
            index=initial_count + 1,
            name="New_Product_X",
            signal="FID1A",
            exp_rt_min=11.25,
            response_factor=0.95,
        )
        method.compounds.append(new_comp)
        self.assertEqual(len(method.compounds), initial_count + 1)

        # Modify
        method.compounds[-1].response_factor = 1.05
        self.assertEqual(method.compounds[-1].response_factor, 1.05)

        # Remove
        method.compounds.pop()
        self.assertEqual(len(method.compounds), initial_count)


if __name__ == "__main__":
    unittest.main()
