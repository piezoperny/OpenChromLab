"""
Shared fixtures, synthetic signal generators, and headless Tkinter test helpers.
"""

import math
import os
import sys
import unittest
from typing import Dict, List, Optional, Tuple

# Ensure workspace root is always in sys.path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from agilent_core.ch_reader import ChromatogramSignal, InjectionData, IntegratedPeak
from agilent_core.method_model import (
    CompoundDef,
    ProcessingMethod,
    SignalMethodConfig,
    build_default_mpz_method,
)


def get_workspace_root() -> str:
    """Return the absolute path to the project workspace root."""
    return WORKSPACE_ROOT


def get_test_set_path() -> str:
    """Return the absolute path to the test-set directory."""
    return os.path.join(WORKSPACE_ROOT, "test-set")


def get_reference_xlsx_path() -> str:
    """Return the absolute path to MPZ_Reaction_Summary.xlsx."""
    test_set_path = os.path.join(WORKSPACE_ROOT, "test-set", "MPZ_Reaction_Summary.xlsx")
    if os.path.isfile(test_set_path):
        return test_set_path
    return os.path.join(WORKSPACE_ROOT, "MPZ_Reaction_Summary.xlsx")


def get_sample_method_path() -> str:
    """Return the absolute path to MPZ_method-2.2.json."""
    return os.path.join(WORKSPACE_ROOT, "MPZ_method-2.2.json")


def create_synthetic_signal(
    name: str = "FID1A",
    desc: str = "FID1 A, Front Signal",
    units: str = "pA",
    t_start: float = 0.0,
    t_end: float = 20.0,
    dt_s: float = 0.02,
    baseline: float = 10.0,
    peaks: Optional[List[Tuple[float, float, float, bool]]] = None,
) -> ChromatogramSignal:
    """
    Generate a deterministic synthetic ChromatogramSignal.

    peaks: list of (rt_min, height, width_fwhm_min, is_negative)
    Gaussian response:
        y(t) = baseline + sum( sign * height * exp(-4*ln(2) * ((t - rt)/fwhm)^2) )
    """
    if peaks is None:
        peaks = []

    dt_min = dt_s / 60.0
    n_points = int(math.ceil((t_end - t_start) / dt_min)) + 1
    times = [t_start + i * dt_min for i in range(n_points)]
    values: List[float] = []

    ln2_4 = 4.0 * math.log(2.0)

    for t in times:
        v = baseline
        for rt, h, fwhm, is_neg in peaks:
            sign = -1.0 if is_neg else 1.0
            if fwhm > 1e-6:
                diff = (t - rt) / fwhm
                # Clamp diff to avoid math underflow
                if abs(diff) < 5.0:
                    v += sign * h * math.exp(-ln2_4 * (diff * diff))
        values.append(v)

    return ChromatogramSignal(
        name=name,
        description=desc,
        units=units,
        sample_name="Synthetic_Sample",
        acq_date="01-Jan-26, 12:00:00",
        time_min=times,
        values=values,
        dt_sec=dt_s,
    )


def create_synthetic_injection(
    folder_name: str = "Synthetic_Sample_01.D",
    signals: Optional[Dict[str, ChromatogramSignal]] = None,
    peaks_by_signal: Optional[Dict[str, List[IntegratedPeak]]] = None,
) -> InjectionData:
    """Create a populated synthetic InjectionData object."""
    if signals is None:
        signals = {
            "FID1A": create_synthetic_signal("FID1A"),
            "TCD2B": create_synthetic_signal("TCD2B", units="25 uV"),
        }
    if peaks_by_signal is None:
        peaks_by_signal = {"FID1A": [], "TCD2B": []}

    return InjectionData(
        folder_path=os.path.join(WORKSPACE_ROOT, "test-set", folder_name),
        folder_name=folder_name,
        sample_name=folder_name.replace(".D", ""),
        injection_number=1,
        acq_date="20-Oct-26, 00:00:00",
        pmx_path=None,
        rx_path=None,
        signals=signals,
        peaks_by_signal=peaks_by_signal,
        integration_source="synthetic",
    )


class HeadlessTkTestCase(unittest.TestCase):
    """
    Base test case for Tkinter-dependent UI and canvas components.
    Creates a hidden root window (withdraw) and guarantees clean destruction.
    """

    def setUp(self) -> None:
        super().setUp()
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        try:
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        super().tearDown()
