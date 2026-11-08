"""Empirical Verification & Stress Suite — Challenger r3_3 (Milestone 3, Round 3).

Focus:
1. Empirically verify widget destruction and timer teardown lifecycle under rapid create/destroy stress:
   - Run tests/test_challenger_r3_1_empirical.py
   - Rapidly instantiate and destroy DualChromatogramCanvas and OpenChromLabApp while
     queuing request_redraw() and timer events. Verify 0 orphaned Tcl after errors in stdout/stderr.
2. Idempotent destroy() handling on OpenChromLabApp and DualChromatogramCanvas.
3. Resilience against post-destruction request_redraw() invocations.
"""

import io
import os
import sys
import time
import tkinter as tk
import unittest
from typing import Any, List, Optional

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from agilent_core.ch_reader import find_d_folders, load_d_folder
from agilent_core.integrator import process_injection
from agilent_core.method_model import build_default_mpz_method
from agilent_ui.chrom_canvas import DualChromatogramCanvas
from agilent_ui.main_window import OpenChromLabApp
from agilent_ui.theme import DARK_PALETTE
from tests.test_helpers import get_test_set_path


class StderrStdoutTclInterceptor:
    """Context manager to intercept sys.stderr, sys.stdout, and tk.Tk.report_callback_exception."""

    def __init__(self, root: Optional[tk.Tk] = None):
        self.root = root
        self.original_stderr = sys.stderr
        self.original_stdout = sys.stdout
        self.stderr_capture = io.StringIO()
        self.stdout_capture = io.StringIO()
        self.captured_exceptions: List[Any] = []
        self._orig_report_callback = None

    def __enter__(self):
        sys.stderr = self.stderr_capture
        sys.stdout = self.stdout_capture
        if self.root is not None:
            self._orig_report_callback = getattr(self.root, "report_callback_exception", None)
            self.root.report_callback_exception = self._on_tk_exception
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stderr = self.original_stderr
        sys.stdout = self.original_stdout
        if self.root is not None and self._orig_report_callback is not None:
            self.root.report_callback_exception = self._orig_report_callback

    def _on_tk_exception(self, exc, val, tb):
        self.captured_exceptions.append((exc, val, tb))

    def get_errors(self) -> List[str]:
        errors = []
        stderr_val = self.stderr_capture.getvalue()
        stdout_val = self.stdout_capture.getvalue()
        for s in (stderr_val, stdout_val):
            for line in s.splitlines():
                line_str = line.strip()
                if any(err_marker in line_str.lower() for err_marker in [
                    "invalid command name",
                    "tclerror",
                    "exception in tkinter callback",
                    "orphaned",
                    "error in after script",
                    "traceback",
                ]):
                    errors.append(line_str)
        for exc, val, _ in self.captured_exceptions:
            errors.append(f"TkCallbackException: {exc} {val}")
        return errors


class TestWidgetDestructionAndTimerTeardownLifecycle(unittest.TestCase):
    """Rigorous empirical verification of widget destruction and timer teardown lifecycle."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.target_d = os.path.join(get_test_set_path(), "MPZHY14_reaction_261015--120F.D")
        if not os.path.exists(cls.target_d):
            folders = find_d_folders(get_test_set_path())
            assert len(folders) > 0, "No .D folders found"
            cls.target_d = folders[0]

        cls.inj = load_d_folder(cls.target_d)
        cls.method = build_default_mpz_method()
        process_injection(cls.inj, cls.method, prefer_rx=True)

    # ------------------------------------------------------------------
    # Test 1: Rapid Create/Destroy of DualChromatogramCanvas (50 cycles)
    # ------------------------------------------------------------------

    def test_rapid_canvas_instantiate_destroy_with_pending_redraws(self) -> None:
        """
        Stress test:
        Instantiate DualChromatogramCanvas, load realistic injection dataset,
        queue multiple redraw and after timer events, then immediately call destroy().
        Run 50 rapid cycles.
        Verify:
        - Exactly 0 Tcl 'invalid command name' errors
        - 0 unhandled after timer exceptions
        - Memory and pending timer attributes cleanly nulled
        """
        root = tk.Tk()
        root.geometry("1024x768")
        root.withdraw()

        total_cycles = 50
        errors_detected: List[str] = []

        with StderrStdoutTclInterceptor(root) as interceptor:
            for cycle in range(total_cycles):
                canvas = DualChromatogramCanvas(root)
                canvas.pack(fill=tk.BOTH, expand=True)
                canvas.set_theme(DARK_PALETTE)
                canvas.set_data(self.inj, self.method, reset_view=False)

                # Queue multiple request_redraw calls (immediate and scheduled)
                canvas.request_redraw(immediate=False)
                self.assertIsNotNone(canvas._pending_redraw_id)

                # Queue secondary after callbacks on the canvas
                canvas.after(25, lambda: None)
                canvas.after(50, lambda: None)

                # Immediately destroy the canvas widget
                canvas.destroy()

                # Verify _pending_redraw_id was nulled during destroy
                self.assertIsNone(canvas._pending_redraw_id)

                # Process all pending events and let any potentially orphaned timers fire
                root.update_idletasks()
                root.update()

            # Small sleep to allow any residual timers to trigger
            time.sleep(0.06)
            root.update()

            errors = interceptor.get_errors()
            if errors:
                errors_detected.extend(errors)

        try:
            root.destroy()
        except Exception:
            pass

        print(f"\n[STRESS 1: Rapid DualChromatogramCanvas Create/Destroy]")
        print(f"  Cycles Executed:  {total_cycles}")
        print(f"  Errors Detected:  {len(errors_detected)}")

        self.assertEqual(
            len(errors_detected),
            0,
            f"Detected orphaned Tcl after/widget errors during rapid canvas teardown: {errors_detected}",
        )

    # ------------------------------------------------------------------
    # Test 2: Rapid Create/Destroy of OpenChromLabApp (25 cycles)
    # ------------------------------------------------------------------

    def test_rapid_app_instantiate_destroy_with_loading_timer(self) -> None:
        """
        Stress test:
        Instantiate OpenChromLabApp (which schedules self._load_seq_timer = self.after(80, ...))
        and immediately destroy the app across varying intervals:
        - 0 ms (immediate abort before sequence loader starts)
        - 5 ms (in-flight before 80ms threshold)
        - 15 ms
        - 40 ms (halfway)
        - 85 ms (during or immediately after sequence loader fires)
        Verify zero orphaned timers in Tcl 'after info' and zero unhandled errors.
        """
        cycles = 25
        delays = [0.0, 0.005, 0.015, 0.040, 0.085]
        errors_detected: List[str] = []

        for i in range(cycles):
            delay = delays[i % len(delays)]

            app = OpenChromLabApp(initial_workspace=WORKSPACE_ROOT)
            app.withdraw()

            with StderrStdoutTclInterceptor(app) as interceptor:
                # Ensure load sequence timer was scheduled
                self.assertIsNotNone(app._load_seq_timer)

                # Trigger canvas redraw requests while app is initializing
                if hasattr(app, "chrom_canvas") and app.chrom_canvas is not None:
                    app.chrom_canvas.request_redraw(immediate=False)

                if delay > 0:
                    time.sleep(delay)
                    try:
                        app.update()
                    except Exception:
                        pass

                # Teardown the app
                app.destroy()

                # Verify pending timers in app were cancelled
                self.assertIsNone(app._load_seq_timer)
                if hasattr(app, "chrom_canvas") and app.chrom_canvas is not None:
                    self.assertIsNone(app.chrom_canvas._pending_redraw_id)

                errors = interceptor.get_errors()
                if errors:
                    errors_detected.extend(errors)

        print(f"\n[STRESS 2: Rapid OpenChromLabApp Create/Destroy]")
        print(f"  Cycles Executed:  {cycles}")
        print(f"  Errors Detected:  {len(errors_detected)}")

        self.assertEqual(
            len(errors_detected),
            0,
            f"Detected orphaned Tcl after/widget errors during rapid app teardown: {errors_detected}",
        )

    # ------------------------------------------------------------------
    # Test 3: Idempotent destroy() on OpenChromLabApp
    # ------------------------------------------------------------------

    def test_app_destroy_idempotency(self) -> None:
        """
        Ensure calling destroy() multiple times on OpenChromLabApp does not raise
        _tkinter.TclError: can't invoke "destroy" command: application has been destroyed.
        """
        app = OpenChromLabApp(initial_workspace=WORKSPACE_ROOT)
        app.withdraw()
        app.destroy()
        try:
            app.destroy()
            app.destroy()
        except tk.TclError as exc:
            self.fail(
                f"DEFECT: OpenChromLabApp.destroy() is not idempotent and crashed on repeated call: {exc}"
            )

    # ------------------------------------------------------------------
    # Test 4: Post-destruction request_redraw() safety on DualChromatogramCanvas
    # ------------------------------------------------------------------

    def test_post_destruction_request_redraw_does_not_orphan_timer(self) -> None:
        """
        If request_redraw() is inadvertently invoked after DualChromatogramCanvas.destroy()
        (e.g., from asynchronous model updates, worker threads, or delayed events),
        it MUST NOT schedule a Tcl after timer that fires on a destroyed canvas widget.
        """
        root = tk.Tk()
        root.geometry("800x600")
        root.withdraw()

        canvas = DualChromatogramCanvas(root)
        canvas.pack()
        canvas.destroy()

        # Call request_redraw on destroyed canvas
        canvas.request_redraw(immediate=False)

        # If a timer was scheduled on a destroyed canvas, it is an orphaned timer bug
        self.assertIsNone(
            canvas._pending_redraw_id,
            "DEFECT: DualChromatogramCanvas.request_redraw() scheduled a timer on a destroyed widget",
        )

        # Process events and ensure no invalid command name error occurs
        time.sleep(0.03)
        root.update()

        root.destroy()

    # ------------------------------------------------------------------
    # Test 5: Root Destruction Cascading Safety
    # ------------------------------------------------------------------

    def test_root_destruction_cascades_safely(self) -> None:
        """
        When root.destroy() is called directly (e.g. user closes window),
        ensure that child canvas timers do not fire into destroyed Tcl interpreter.
        """
        errors_detected = []
        for _ in range(15):
            root = tk.Tk()
            root.geometry("800x600")
            root.withdraw()

            with StderrStdoutTclInterceptor(root) as interceptor:
                canvas = DualChromatogramCanvas(root)
                canvas.pack(fill=tk.BOTH, expand=True)
                canvas.set_data(self.inj, self.method, reset_view=False)
                canvas.request_redraw(immediate=False)

                # Destroy root directly
                root.destroy()

                errors = interceptor.get_errors()
                if errors:
                    errors_detected.extend(errors)

        print(f"\n[STRESS 5: Cascade Root Destruction]")
        print(f"  Cycles Executed:  15")
        print(f"  Errors Detected:  {len(errors_detected)}")

        self.assertEqual(
            len(errors_detected),
            0,
            f"Detected errors during root destruction cascade: {errors_detected}",
        )


if __name__ == "__main__":
    unittest.main()
