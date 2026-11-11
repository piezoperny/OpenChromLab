#!/usr/bin/env python3
"""
Master E2E Test Runner for Agilent OpenLab CDS Desktop Substitute Application.
Discovers and executes 4-tier test harness across Requirements R1–R4:
- Tier 1: Feature Coverage (R1–R4)
- Tier 2: Boundary & Corner Cases
- Tier 3: Cross-Feature Combinations & Workflows
- Tier 4: Real-World Scenarios (11-injection dataset + MPZ_Reaction_Summary.xlsx parity)

Usage:
    py -3 tests/run_e2e_tests.py
    py -3 tests/run_e2e_tests.py --tier 1
    py -3 tests/run_e2e_tests.py -v
    py -3 tests/run_e2e_tests.py --allow-pending
"""

import argparse
import datetime
import os
import sys
import time
import unittest
from typing import Dict, List, Optional, Tuple

# Ensure workspace root is always at sys.path[0] and os.getcwd()
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)
os.chdir(WORKSPACE_ROOT)


class StructuredTierResult(unittest.TestResult):
    """Custom TestResult that captures structured per-tier test outcomes."""

    def __init__(self, verbose: bool = False):
        super().__init__()
        self.verbose = verbose
        self.test_records: List[Tuple[str, str, Optional[str]]] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        if self.verbose:
            test_id = test.id().split(".")[-1]
            sys.stdout.write(f"    • {test_id} ... ")
            sys.stdout.flush()

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        test_id = test.id().split(".")[-1]
        self.test_records.append((test.id(), "PASS", None))
        if self.verbose:
            print("[PASS]")

    def addFailure(self, test: unittest.TestCase, err) -> None:
        super().addFailure(test, err)
        test_id = test.id().split(".")[-1]
        msg = self._exc_info_to_string(err, test)
        self.test_records.append((test.id(), "FAIL", msg))
        if self.verbose:
            print("[FAIL]")

    def addError(self, test: unittest.TestCase, err) -> None:
        super().addError(test, err)
        test_id = test.id().split(".")[-1]
        msg = self._exc_info_to_string(err, test)
        self.test_records.append((test.id(), "ERROR", msg))
        if self.verbose:
            print("[ERROR]")

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self.test_records.append((test.id(), "SKIP", reason))
        if self.verbose:
            print(f"[SKIP: {reason}]")


def run_test_module(module_name: str, verbose: bool = False) -> StructuredTierResult:
    """Load and execute all test cases in a given module."""
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromName(module_name)
    result = StructuredTierResult(verbose=verbose)
    suite.run(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Agilent OpenLab CDS E2E Test Harness")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Run only the specified tier (1-4)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print verbose execution details")
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Exit with 0 even if pending milestone features fail",
    )
    args = parser.parse_args()

    start_time = time.time()
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=" * 80)
    print("OPENCHROMLAB DATA ANALYSIS SYSTEM — 4-TIER E2E TEST RUNNER")
    print(f"Timestamp: {now_str} | Workspace: {WORKSPACE_ROOT}")
    print("=" * 80)

    tier_modules = {
        1: [
            ("Tier 1: Feature Coverage — R1 Layout Resilience", "tests.tier1_features.test_r1_layout"),
            ("Tier 1: Feature Coverage — R2 Mouse Navigation", "tests.tier1_features.test_r2_navigation"),
            ("Tier 1: Feature Coverage — R3 Core Engine & Math", "tests.tier1_features.test_r3_core_engine"),
            ("Tier 1: Feature Coverage — R4 Batch & Single-Sheet Export", "tests.tier1_features.test_r4_batch_export"),
            ("Tier 1: OpenChromLab — R1 Renaming & Backward Compatibility", "tests.tier1_features.test_openchromlab_r1_renaming"),
            ("Tier 1: OpenChromLab — R2 Channel Display Selection", "tests.tier1_features.test_openchromlab_r2_channel_selection"),
            ("Tier 1: OpenChromLab — R3 Axis Pan & Scale Navigation", "tests.tier1_features.test_openchromlab_r3_axis_navigation"),
            ("Tier 1: OpenChromLab — R4 Dark Theme Option", "tests.tier1_features.test_openchromlab_r4_theme"),
            ("Tier 1: OpenChromLab — R5 Method Creation & Modification", "tests.tier1_features.test_openchromlab_r5_method_editor"),
            ("Tier 1: OpenChromLab — R6 Context Actions & Hit-Testing", "tests.tier1_features.test_openchromlab_r6_context_actions"),
            ("Tier 1: OpenChromLab — R7 Shortcuts (Undo Ctrl+Z & Deselect Esc)", "tests.tier1_features.test_openchromlab_r7_shortcuts"),
            ("Tier 1: OpenChromLab — R8 Method Custom Zoom Presets", "tests.tier1_features.test_openchromlab_r8_zoom_presets"),
            ("Tier 1: OpenChromLab — R9 Launcher Script & Application Icon", "tests.tier1_features.test_openchromlab_r9_launcher_icon"),
            ("Tier 1: OpenChromLab — R10 Curve Line Width & Timed Events", "tests.tier1_features.test_openchromlab_r10_curve_events"),
            ("Tier 1: OpenChromLab — Upgrade Features F1-F12 (60 FPS, Dark Theme & 5-Frame ICO)", "tests.tier1_features.test_upgrade_features"),
            ("Tier 1: OpenChromLab — Workspace, Navigation & Shortcut Enhancements", "tests.tier1_features.test_workspace_navigation_enhancements"),
        ],
        2: [
            ("Tier 2: Baseline Boundary & Corner Cases", "tests.tier2_boundaries.test_boundaries"),
            ("Tier 2: OpenChromLab Boundary & Stress Cases", "tests.tier2_boundaries.test_openchromlab_boundaries"),
        ],
        3: [
            ("Tier 3: Baseline Cross-Feature Workflows", "tests.tier3_combinations.test_workflows"),
            ("Tier 3: OpenChromLab Cross-Feature Combinations", "tests.tier3_combinations.test_openchromlab_combinations"),
        ],
        4: [
            ("Tier 4: Baseline 11-Injection Parity Verification", "tests.tier4_real_world.test_real_dataset"),
            ("Tier 4: OpenChromLab Complete Analyst Workflow", "tests.tier4_real_world.test_openchromlab_analyst_workflow"),
        ],
    }

    selected_tiers = [args.tier] if args.tier else [1, 2, 3, 4]

    tier_stats: Dict[int, Dict[str, int]] = {}
    all_failures: List[Tuple[str, str, str]] = []

    for tier_num in selected_tiers:
        tier_stats[tier_num] = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        modules = tier_modules[tier_num]

        print(f"\n--- EXECUTING TIER {tier_num} ---")
        for desc, mod_name in modules:
            print(f"Running suite: {desc} ({mod_name})")
            res = run_test_module(mod_name, verbose=args.verbose)

            n_run = res.testsRun
            n_fail = len(res.failures)
            n_err = len(res.errors)
            n_skip = len(res.skipped)
            n_pass = n_run - (n_fail + n_err + n_skip)

            tier_stats[tier_num]["total"] += n_run
            tier_stats[tier_num]["passed"] += n_pass
            tier_stats[tier_num]["failed"] += n_fail
            tier_stats[tier_num]["errors"] += n_err
            tier_stats[tier_num]["skipped"] += n_skip

            for test, msg in res.failures:
                all_failures.append((f"Tier {tier_num}", test.id(), msg))
            for test, msg in res.errors:
                all_failures.append((f"Tier {tier_num}", test.id(), msg))

            status_tag = "[PASS]" if (n_fail == 0 and n_err == 0) else "[ISSUES DETECTED]"
            print(f"  Result: {n_pass}/{n_run} passed ({n_fail} failed, {n_err} errors) {status_tag}")

    elapsed = time.time() - start_time

    # Print Summary Table
    print("\n" + "=" * 80)
    print("E2E TEST EXECUTION SUMMARY")
    print("=" * 80)
    print(f"{'Tier Name':<45} {'Total':>7} {'Passed':>8} {'Failed':>8} {'Errors':>8} {'Rate':>8}")
    print("-" * 80)

    grand_total = 0
    grand_passed = 0
    grand_failed = 0
    grand_errors = 0

    tier_names = {
        1: "Tier 1: Feature Coverage (R1-R4)",
        2: "Tier 2: Boundary & Corner Cases",
        3: "Tier 3: Cross-Feature Workflows",
        4: "Tier 4: Real-World Scenarios",
    }

    for tier_num in selected_tiers:
        st = tier_stats[tier_num]
        tot = st["total"]
        pas = st["passed"]
        fl = st["failed"]
        er = st["errors"]
        rate_str = f"{(pas / tot * 100):.1f}%" if tot > 0 else "0.0%"

        grand_total += tot
        grand_passed += pas
        grand_failed += fl
        grand_errors += er

        print(f"{tier_names[tier_num]:<45} {tot:>7} {pas:>8} {fl:>8} {er:>8} {rate_str:>8}")

    print("-" * 80)
    grand_rate = f"{(grand_passed / grand_total * 100):.1f}%" if grand_total > 0 else "0.0%"
    print(f"{'TOTAL':<45} {grand_total:>7} {grand_passed:>8} {grand_failed:>8} {grand_errors:>8} {grand_rate:>8}")
    print("=" * 80)
    print(f"Total Duration: {elapsed:.2f} seconds")

    if all_failures:
        print("\n" + "!" * 80)
        print("FAILURE & DEFECT BREAKDOWN (FOR MILESTONE ESCALATION)")
        print("!" * 80)
        for t_label, test_id, traceback_msg in all_failures:
            print(f"\n[{t_label}] {test_id}:")
            # Print last 6 lines of traceback
            lines = [l for l in traceback_msg.strip().split("\n") if l.strip()]
            summary_snippet = "\n".join(lines[-4:])
            print(f"{summary_snippet}")

    all_passed = (grand_failed == 0 and grand_errors == 0)
    if all_passed:
        print("\n>>> ALL TESTS PASSED SUCCESSFULLY (Exit Code 0) <<<")
        return 0
    else:
        print(f"\n>>> TEST SUITE COMPLETED WITH {grand_failed} FAILURE(S) AND {grand_errors} ERROR(S) <<<")
        if args.allow_pending:
            print("Note: --allow-pending was specified; exiting with code 0.")
            return 0
        return 1


if __name__ == "__main__":
    sys.exit(main())
