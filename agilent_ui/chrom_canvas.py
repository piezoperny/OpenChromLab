"""
High-FPS Dual-Signal Interactive Chromatogram Canvas (Tkinter)
Replicates the Agilent OpenLab CDS v2.7 stacked FID1A + TCD2B viewer
with synchronized X-axis (Retention Time), independent Y-axis zoom,
and interactive Manual Integration tools (Drag Anchors, Draw Peak, Split Peak).
"""

from collections import defaultdict
from enum import Enum
import math
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple

from agilent_core.ch_reader import ChromatogramSignal, InjectionData, IntegratedPeak
from agilent_core.integrator import (
    add_manual_peak,
     split_peak_at,
    update_peak_anchors,
)
from agilent_core.method_model import CompoundDef, ProcessingMethod
from agilent_ui.theme import ThemePalette, LIGHT_PALETTE, DARK_PALETTE


class HitType(Enum):
    NONE = "none"
    ANCHOR = "anchor"
    SHARED_EXTREME = "shared_extreme"
    PEAK_BODY = "peak_body"


class DualChromatogramCanvas(tk.Frame):
    """
    Interactive dual-stacked chromatogram plot widget for FID1A (top) and TCD2B (bottom).
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_peak_selected: Optional[Callable[[Optional[IntegratedPeak]], None]] = None,
        on_peaks_modified: Optional[Callable[[str], None]] = None,
        on_context_menu: Optional[Callable[[tk.Event, Any, dict], None]] = None,
    ) -> None:
        self.theme: ThemePalette = DARK_PALETTE
        super().__init__(parent, bg=self.theme.canvas_bg)
        self.on_peak_selected = on_peak_selected
        self.on_peaks_modified = on_peaks_modified
        self.on_context_menu_callback = on_context_menu

        self.injection: Optional[InjectionData] = None
        self.method: Optional[ProcessingMethod] = None

        # View ranges
        self.x_range: Tuple[float, float] = (3.5, 16.5)  # Default active window (min)
        self.y_ranges: Dict[str, Tuple[float, float]] = {
            "FID1A": (8.5, 30.0),
            "TCD2B": (10.0, 300.0),
        }

        # Channel display selection: "both", "FID1A", "TCD2B"
        self.channel_mode: str = "both"

        # Curve rendering line width (Feature F22 / R10)
        self.trace_line_width: float = 2.0

        # Display toggles
        self.show_compound_labels = tk.BooleanVar(value=True)
        self.show_rt_windows = tk.BooleanVar(value=True)
        self.show_timed_events = tk.BooleanVar(value=True)
        self.show_baselines = tk.BooleanVar(value=True)
        self.snap_anchors_to_trace = tk.BooleanVar(value=True)

        # Interaction mode: 'pan_zoom', 'drag_anchor', 'draw_peak', 'split_peak'
        self.tool_mode: str = "pan_zoom"
        self.selected_peak_id: Optional[str] = None
        self.highlighted_compound: Optional[CompoundDef] = None

        # Drag / hover state
        self._drag_state: Optional[dict] = None
        self._hover_anchor: Optional[Tuple[str, str, str]] = None  # (sig_name, peak_id, 'start'|'end')
        self._cursor_pos: Optional[Tuple[int, int]] = None
        self._trace_cache: Dict[str, dict] = {}
        self._last_cfg_size: Tuple[int, int] = (0, 0)
        self._pending_redraw_id: Optional[str] = None
        self._is_destroyed: bool = False

        # Layout margins (F10: margin_mid >= 46, margin_bottom >= 46 to eliminate FID1A tick / TCD2B title collisions)
        self.margin_left = 76
        self.margin_right = 24
        self.margin_top = 28
        self.margin_mid = 52
        self.margin_bottom = 48

        self.canvas = tk.Canvas(
            self,
            bg=self.theme.canvas_bg,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
            cursor="arrow",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bindings
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_left_down)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Double-Button-1>", self._on_double_click_reset)
        self.canvas.bind("<Double-Button-3>", self._on_double_click_reset)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<ButtonPress-3>", self._on_right_down)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_up)

    def _on_canvas_configure(self, event: tk.Event) -> None:
        sz = (event.width, event.height)
        if sz != self._last_cfg_size:
            self._last_cfg_size = sz
            self.redraw()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_channel_mode(self, mode: str) -> None:
        """
        Set channel display selection: 'both', 'FID1A' (or 'fid'), 'TCD2B' (or 'tcd').
        Clears active drag state and redraws canvas.
        """
        m = str(mode).strip().lower()
        if m in ("fid", "fid1a"):
            self.channel_mode = "FID1A"
        elif m in ("tcd", "tcd2b"):
            self.channel_mode = "TCD2B"
        else:
            self.channel_mode = "both"
        self._drag_state = None
        self.redraw()

    def set_theme(self, palette: ThemePalette) -> None:
        """
        Update canvas and plot theme palette (light / dark) and trigger redraw.
        """
        self.theme = palette
        self.configure(bg=palette.canvas_bg)
        self.canvas.configure(
            bg=palette.canvas_bg,
            highlightbackground=palette.panel_border,
        )
        self.redraw()

    def set_data(
        self,
        injection: Optional[InjectionData],
        method: Optional[ProcessingMethod],
        reset_view: bool = False,
    ) -> None:
        self.injection = injection
        self.method = method
        self._trace_cache.clear()
        if reset_view and injection is not None:
            self.zoom_active_region()
        else:
            self.redraw()

    def set_tool_mode(self, mode: str) -> None:
        self.tool_mode = mode
        cursors = {
            "pan_zoom": "arrow",
            "drag_anchor": "hand2",
            "draw_peak": "crosshair",
            "split_peak": "sb_h_double_arrow",
        }
        self.canvas.configure(cursor=cursors.get(mode, "arrow"))
        self.redraw()

    def select_peak(self, peak_id: Optional[str], zoom_to: bool = False) -> None:
        self.selected_peak_id = peak_id
        if zoom_to and peak_id and self.injection:
            for sname, pks in self.injection.peaks_by_signal.items():
                for pk in pks:
                    if pk.peak_id == peak_id:
                        pad_x = max(0.45, (pk.end_min - pk.begin_min) * 3.0)
                        self.x_range = (max(0.0, pk.rt_min - pad_x), min(40.0, pk.rt_min + pad_x))
                        self._autoscale_y_for_signal(sname, self.x_range[0], self.x_range[1], focus_peak=pk)
                        break
        self.redraw()

    def highlight_compound_window(self, comp: Optional[CompoundDef], zoom_to: bool = False) -> None:
        self.highlighted_compound = comp
        if comp and zoom_to:
            w0, w1 = comp.window_range
            pad = max(0.5, (w1 - w0) * 2.5)
            self.x_range = (max(0.0, comp.exp_rt_min - pad), min(40.0, comp.exp_rt_min + pad))
            self._autoscale_y_for_signal(comp.signal, self.x_range[0], self.x_range[1])
        self.redraw()

    def zoom_full_range(self) -> None:
        if not self.injection or not self.injection.signals:
            return
        max_t = max((s.time_min[-1] for s in self.injection.signals.values() if s.time_min), default=40.0)
        self.x_range = (0.0, max_t)
        for sname in self.injection.signals:
            self._autoscale_y_for_signal(sname, 0.0, max_t)
        self.redraw()

    def zoom_active_region(self) -> None:
        """Zoom to the main reaction analysis window (3.5 - 16.5 min) with nicely scaled Y axes."""
        self.x_range = (3.5, 16.5)
        if self.injection:
            for sname, sig in self.injection.signals.items():
                if sname == "FID1A":
                    # Show hydrocarbons & alcohols clearly without letting the 385 pA MeOH peak dwarf everything
                    self.y_ranges["FID1A"] = (9.2, 24.0)
                elif sname == "TCD2B":
                    self.y_ranges["TCD2B"] = (10.0, 310.0)
                else:
                    self._autoscale_y_for_signal(sname, 3.5, 16.5)
        self.redraw()

    def autoscale_visible_y(self) -> None:
        if not self.injection:
            return
        for sname in self.injection.signals:
            self._autoscale_y_for_signal(sname, self.x_range[0], self.x_range[1])
        self.redraw()

    # ------------------------------------------------------------------
    # Coordinate Transforms & Helpers
    # ------------------------------------------------------------------

    def _get_panel_rects(self) -> Dict[str, Tuple[int, int, int, int]]:
        """Return (x0, y0, x1, y1) pixel bounding boxes for each signal plot panel."""
        w = max(self.canvas.winfo_width(), 300)
        h = max(self.canvas.winfo_height(), 240)
        x0 = self.margin_left
        x1 = max(x0 + 50, w - self.margin_right)

        if self.channel_mode == "FID1A":
            avail_h = max(100, h - self.margin_top - self.margin_bottom)
            return {"FID1A": (x0, self.margin_top, x1, self.margin_top + avail_h)}
        elif self.channel_mode == "TCD2B":
            avail_h = max(100, h - self.margin_top - self.margin_bottom)
            return {"TCD2B": (x0, self.margin_top, x1, self.margin_top + avail_h)}
        else:
            avail_h = max(100, h - self.margin_top - self.margin_bottom - self.margin_mid)
            h_top = avail_h // 2
            h_bot = avail_h - h_top

            y0_top = self.margin_top
            y1_top = y0_top + h_top
            y0_bot = y1_top + self.margin_mid
            y1_bot = y0_bot + h_bot

            return {
                "FID1A": (x0, y0_top, x1, y1_top),
                "TCD2B": (x0, y0_bot, x1, y1_bot),
            }

    def _hit_test_zone(self, px: int, py: int) -> Tuple[str, Optional[str]]:
        """
        Identifies spatial interaction zone at canvas coordinates (px, py).
        Returns (zone, sname) where zone is 'y_axis', 'x_axis', 'plot_body', or 'outside'.
        """
        rects = self._get_panel_rects()
        if not rects:
            return "outside", None

        panel_keys = list(rects.keys())
        bottom_sname = panel_keys[-1]
        bx0, by0, bx1, by1 = rects[bottom_sname]

        # 1. Global bottom X-axis gutter (ticks + Retention Time title)
        if bx0 <= px <= bx1 + 10 and by1 - 6 <= py <= by1 + self.margin_bottom + 20:
            return "x_axis", bottom_sname

        # 2. Check each panel
        for sname, (x0, y0, x1, y1) in rects.items():
            if y0 <= py <= y1:
                if px < x0 + 4:
                    return "y_axis", sname
                elif px <= x1 + 2:
                    if sname != bottom_sname and py >= y1 - 6:
                        return "x_axis", sname
                    return "plot_body", sname
                else:
                    return "outside", None
            elif sname != bottom_sname and (x0 <= px <= x1) and (y1 - 6 <= py <= y1 + 25):
                return "x_axis", sname

        # 3. Y-axis margin tolerance
        for sname, (x0, y0, x1, y1) in rects.items():
            if px < x0 + 4 and (y0 - 15 <= py <= y1 + 15):
                return "y_axis", sname

        return "outside", None

    def hit_test_integration_element(
        self,
        px: int,
        py: int,
        sname: Optional[str] = None,
        sig: Optional[ChromatogramSignal] = None,
        peaks: Optional[List[IntegratedPeak]] = None,
        rect: Optional[Tuple[int, int, int, int]] = None,
    ) -> Tuple[HitType, dict]:
        """
        Detects clicked integration elements: baseline anchors, shared split extremes,
        or peak bodies (inside curve-to-baseline polygon envelope).
        """
        rects = self._get_panel_rects()
        if sname is None:
            sname = self._panel_at_xy(px, py)
        if not sname or sname not in rects:
            for sn, r in rects.items():
                if r[0] - 10 <= px <= r[2] + 10 and r[1] - 10 <= py <= r[3] + 10:
                    sname = sn
                    break
        if not sname or sname not in rects:
            return HitType.NONE, {}

        if rect is None:
            rect = rects[sname]
        if sig is None:
            if not self.injection or sname not in self.injection.signals:
                return HitType.NONE, {}
            sig = self.injection.signals[sname]
        if peaks is None:
            if not self.injection:
                return HitType.NONE, {}
            peaks = self.injection.peaks_by_signal.get(sname, [])

        t_click, y_click = self._px_to_data(sname, px, py, rect)

        # 1. Check Baseline Anchor Points (11 px radius)
        for pk in peaks:
            for kind, t_a, y_a in (
                ("start", pk.begin_min, pk.baseline_start_y),
                ("end", pk.end_min, pk.baseline_end_y),
            ):
                px_a, py_a = self._data_to_px(sname, t_a, y_a, rect)
                if math.hypot(px - px_a, py - py_a) <= 11.0:
                    if kind == "end":
                        adj = next((p for p in peaks if abs(p.begin_min - pk.end_min) < 0.05), None)
                        if adj:
                            return HitType.SHARED_EXTREME, {
                                "left_peak": pk,
                                "right_peak": adj,
                                "t_split": pk.end_min,
                                "anchor_kind": "shared",
                                "peak": pk,
                                "kind": kind,
                            }
                    elif kind == "start":
                        adj = next((p for p in peaks if abs(p.end_min - pk.begin_min) < 0.05), None)
                        if adj:
                            return HitType.SHARED_EXTREME, {
                                "left_peak": adj,
                                "right_peak": pk,
                                "t_split": pk.begin_min,
                                "anchor_kind": "shared",
                                "peak": pk,
                                "kind": kind,
                            }
                    return HitType.ANCHOR, {
                        "peak": pk,
                        "kind": kind,
                        "t_anc": t_a,
                        "y_anc": y_a,
                    }

        # 2. Check Shared Peak Drop Line (Split Peaks like H2 / Argon)
        sorted_peaks = sorted(peaks, key=lambda p: p.begin_min)
        for i in range(len(sorted_peaks) - 1):
            p1 = sorted_peaks[i]
            p2 = sorted_peaks[i + 1]
            if abs(p1.end_min - p2.begin_min) < 0.05:
                t_split = p1.end_min
                px_split, py_base = self._data_to_px(sname, t_split, p1.baseline_end_y, rect)
                y_curve = sig.value_at_time(t_split)
                _, py_curve = self._data_to_px(sname, t_split, y_curve, rect)
                y_top = min(py_base, py_curve)
                y_bot = max(py_base, py_curve)
                if abs(px - px_split) <= 8 and (y_top - 8) <= py <= (y_bot + 8):
                    return HitType.SHARED_EXTREME, {
                        "left_peak": p1,
                        "right_peak": p2,
                        "t_split": t_split,
                        "anchor_kind": "drop_line",
                        "peak": p1,
                    }

        # 3. Check Peak Body (Inside curve-to-baseline polygon envelope)
        candidates = [p for p in peaks if p.begin_min <= t_click <= p.end_min]
        if candidates:
            pk = min(candidates, key=lambda p: p.end_min - p.begin_min)
            y_sig = sig.value_at_time(t_click)
            y_base = pk.baseline_y_at(t_click)
            _, py_sig = self._data_to_px(sname, t_click, y_sig, rect)
            _, py_base = self._data_to_px(sname, t_click, y_base, rect)
            y_min_env = min(py_sig, py_base) - 8
            y_max_env = max(py_sig, py_base) + 8
            if y_min_env <= py <= y_max_env:
                return HitType.PEAK_BODY, {"peak": pk, "t_click": t_click}

        # 4. Fallback proximity to peak apex (within 24 px)
        best_pk = None
        best_dist = 24.0
        for pk in peaks:
            px_rt, py_rt = self._data_to_px(sname, pk.rt_min, sig.value_at_time(pk.rt_min), rect)
            d = math.hypot(px - px_rt, py - py_rt)
            if d < best_dist:
                best_dist = d
                best_pk = pk
        if best_pk is not None:
            return HitType.PEAK_BODY, {"peak": best_pk, "t_click": best_pk.rt_min}

        return HitType.NONE, {}

    _hit_test_integration_element = hit_test_integration_element

    def _panel_at_xy(self, px: int, py: int) -> Optional[str]:
        for sname, (x0, y0, x1, y1) in self._get_panel_rects().items():
            if y0 <= py <= y1:
                return sname
        return None

    def _data_to_px(self, sname: str, t_val: float, y_val: float, rect: Tuple[int, int, int, int]) -> Tuple[float, float]:
        x0, y0, x1, y1 = rect
        tx0, tx1 = self.x_range
        ty0, ty1 = self.y_ranges.get(sname, (0.0, 100.0))
        dx = max(tx1 - tx0, 1e-9)
        dy = max(ty1 - ty0, 1e-9)
        px = x0 + (t_val - tx0) / dx * (x1 - x0)
        py = y1 - (y_val - ty0) / dy * (y1 - y0)
        return px, py

    def _px_to_data(self, sname: str, px: float, py: float, rect: Tuple[int, int, int, int]) -> Tuple[float, float]:
        x0, y0, x1, y1 = rect
        tx0, tx1 = self.x_range
        ty0, ty1 = self.y_ranges.get(sname, (0.0, 100.0))
        w = max(x1 - x0, 1)
        h = max(y1 - y0, 1)
        t_val = tx0 + (px - x0) / w * (tx1 - tx0)
        y_val = ty0 + (y1 - py) / h * (ty1 - ty0)
        return t_val, y_val

    def _autoscale_y_for_signal(
        self,
        sname: str,
        t_min: float,
        t_max: float,
        focus_peak: Optional[IntegratedPeak] = None,
    ) -> None:
        if not self.injection or sname not in self.injection.signals:
            return
        sig = self.injection.signals[sname]
        i0 = sig.index_at_time(t_min)
        i1 = sig.index_at_time(t_max)
        if i1 <= i0:
            return
        ymin, ymax = sig.min_max_in_range(i0, i1)
        if focus_peak is not None:
            p_y0 = min(focus_peak.baseline_start_y, focus_peak.baseline_end_y, ymin)
            if focus_peak.is_negative:
                p_y1 = max(focus_peak.baseline_start_y, focus_peak.baseline_end_y) + focus_peak.height * 0.4
                p_y0 = ymin - focus_peak.height * 0.25
            else:
                p_y1 = max(focus_peak.baseline_start_y, focus_peak.baseline_end_y) + focus_peak.height * 1.35
            ymin, ymax = p_y0, p_y1

        span = max(ymax - ymin, 0.5)
        self.y_ranges[sname] = (ymin - 0.08 * span, ymax + 0.14 * span)

    def _nice_ticks(self, v0: float, v1: float, target_count: int = 7) -> List[float]:
        span = v1 - v0
        if span <= 1e-9:
            return [v0]
        raw_step = span / max(target_count, 2)
        mag = 10.0 ** math.floor(math.log10(raw_step))
        residual = raw_step / mag
        if residual > 5.0:
            step = 10.0 * mag
        elif residual > 2.0:
            step = 5.0 * mag
        elif residual > 1.0:
            step = 2.0 * mag
        else:
            step = mag
        first = math.ceil(v0 / step) * step
        ticks: List[float] = []
        cur = first
        while cur <= v1 + 1e-9 and len(ticks) < 30:
            ticks.append(round(cur, 6))
            cur += step
        return ticks

    # ------------------------------------------------------------------
    # Rendering & Lightweight Tagged Overlays
    # ------------------------------------------------------------------

    def request_redraw(self, immediate: bool = False) -> None:
        """
        Request canvas redraw. If immediate=False, coalesces multiple rapid calls
        into a smooth 60 FPS animation frame (~16 ms) to eliminate lag on high-frequency mouse drag.
        """
        if getattr(self, "_is_destroyed", False):
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        if immediate:
            if self._pending_redraw_id is not None:
                try:
                    self.after_cancel(self._pending_redraw_id)
                except Exception:
                    pass
                self._pending_redraw_id = None
            self.redraw()
            return

        if self._pending_redraw_id is None:
            self._pending_redraw_id = self.after(16, self._execute_scheduled_redraw)

    def _execute_scheduled_redraw(self) -> None:
        self._pending_redraw_id = None
        if getattr(self, "_is_destroyed", False):
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.redraw()

    def destroy(self) -> None:
        """Clean up pending timer callbacks before widget destruction."""
        self._is_destroyed = True
        if getattr(self, "_pending_redraw_id", None) is not None:
            try:
                self.after_cancel(self._pending_redraw_id)
            except Exception:
                pass
            self._pending_redraw_id = None
        try:
            super().destroy()
        except Exception:
            pass

    def redraw(self) -> None:
        if getattr(self, "_is_destroyed", False):
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        if self._pending_redraw_id is not None:
            try:
                self.after_cancel(self._pending_redraw_id)
            except Exception:
                pass
            self._pending_redraw_id = None

        c = self.canvas
        c.delete("all")

        rects = self._get_panel_rects()
        for sname, rect in rects.items():
            self._draw_signal_panel(sname, rect, rects)

        self._update_drag_overlay(rects=rects)
        self._update_cursor_overlay(rects=rects)

    def _update_drag_overlay(self, rects: Optional[Dict[str, Tuple[int, int, int, int]]] = None) -> None:
        """Fast (~0.5 ms) update of transient box-zoom or draw-peak rubberband overlay."""
        c = self.canvas
        c.delete("overlay_interactive")
        if not self._drag_state or self._drag_state.get("mode") not in ("zoom_box", "draw_peak"):
            return
        if rects is None:
            rects = self._get_panel_rects()
        sname = self._drag_state["sname"]
        rect = rects.get(sname)
        if not rect:
            return
        x0_d, y0_d = self._drag_state["start_px"]
        x1_d, y1_d = self._drag_state["cur_px"]
        if self._drag_state["mode"] == "zoom_box":
            c.create_rectangle(
                x0_d, y0_d, x1_d, y1_d,
                outline=self.theme.zoom_box_line, dash=(4, 2), width=1.5,
                tags=("overlay_interactive",),
            )
        elif self._drag_state["mode"] == "draw_peak":
            # If Shift is held, draw a perfectly horizontal baseline line
            if self._drag_state.get("shift_constrained"):
                y1_d = y0_d
            c.create_line(
                x0_d, y0_d, x1_d, y1_d,
                fill=self.theme.baseline_selected, width=2, dash=(4, 2),
                tags=("overlay_interactive",),
            )
            c.create_oval(
                x0_d - 4, y0_d - 4, x0_d + 4, y0_d + 4,
                outline=self.theme.baseline_selected, fill=self.theme.canvas_bg, width=2,
                tags=("overlay_interactive",),
            )
            c.create_oval(
                x1_d - 4, y1_d - 4, x1_d + 4, y1_d + 4,
                outline=self.theme.baseline_selected, fill=self.theme.canvas_bg, width=2,
                tags=("overlay_interactive",),
            )

    def _update_cursor_overlay(self, rects: Optional[Dict[str, Tuple[int, int, int, int]]] = None) -> None:
        """Fast (~0.5 ms) update of split-peak cursor preview line without c.delete('all')."""
        c = self.canvas
        c.delete("overlay_cursor")
        if self.tool_mode != "split_peak" or not self._cursor_pos:
            return
        if rects is None:
            rects = self._get_panel_rects()
        mx, my = self._cursor_pos
        sname = self._panel_at_xy(mx, my)
        if sname and sname in rects:
            rx0, ry0, rx1, ry1 = rects[sname]
            if rx0 <= mx <= rx1:
                c.create_line(
                    mx, ry0, mx, ry1,
                    fill=self.theme.baseline_selected, dash=(3, 3), width=1.5,
                    tags=("overlay_cursor",),
                )
                t_cur, _ = self._px_to_data(sname, mx, my, rects[sname])
                c.create_text(
                    mx + 6, ry0 + 14,
                    text=f"Split @ {t_cur:.3f} min",
                    anchor="w",
                    font=("Segoe UI", 8, "bold"),
                    fill=self.theme.baseline_selected,
                    tags=("overlay_cursor",),
                )

    def _update_anchor_hover_item(
        self,
        anc: Optional[Tuple[str, str, str]],
        is_hovered: bool,
        rects: Optional[Dict[str, Tuple[int, int, int, int]]] = None,
    ) -> None:
        """Update a single anchor handle oval in-place via tag without redrawing the canvas."""
        if anc is None or not self.injection:
            return
        sname, pk_id, end_kind = anc
        tag = f"anchor_{sname}_{pk_id}_{end_kind}"
        c = self.canvas
        items = c.find_withtag(tag)
        if not items:
            return
        if rects is None:
            rects = self._get_panel_rects()
        rect = rects.get(sname)
        if not rect:
            return
        pks = self.injection.peaks_by_signal.get(sname, [])
        pk = next((p for p in pks if p.peak_id == pk_id), None)
        if not pk:
            return
        t_anc = pk.begin_min if end_kind == "start" else pk.end_min
        y_anc = pk.baseline_start_y if end_kind == "start" else pk.baseline_end_y
        px_a, py_a = self._data_to_px(sname, t_anc, y_anc, rect)
        is_sel = (pk.peak_id == self.selected_peak_id)
        r = 5 if (is_hovered or is_sel or self.tool_mode == "drag_anchor") else 3
        fill_c = self.theme.baseline_selected if is_hovered else (self.theme.anchor_selected if is_sel else self.theme.anchor_fill)
        out_c = self.theme.baseline_selected if (is_hovered or is_sel) else self.theme.anchor_outline
        for item_id in items:
            c.coords(item_id, px_a - r, py_a - r, px_a + r, py_a + r)
            c.itemconfigure(item_id, fill=fill_c, outline=out_c)

    def _draw_signal_panel(
        self,
        sname: str,
        rect: Tuple[int, int, int, int],
        all_rects: Optional[Dict[str, Tuple[int, int, int, int]]] = None,
    ) -> None:
        c = self.canvas
        x0, y0, x1, y1 = rect
        pw = max(1, x1 - x0)
        ph = max(1, y1 - y0)

        # Panel background & border
        c.create_rectangle(x0, y0, x1, y1, fill=self.theme.panel_bg, outline=self.theme.panel_border, width=1)

        sig: Optional[ChromatogramSignal] = None
        if self.injection and sname in self.injection.signals:
            sig = self.injection.signals[sname]

        tx0, tx1 = self.x_range
        ty0, ty1 = self.y_ranges.get(sname, (0.0, 100.0))

        # 1a. Subtle Compound RT Window Column Bands in Dark Mode (drawn behind grid lines)
        if self.show_rt_windows.get() and self.method and self.theme.name == "dark":
            band_fill = getattr(self.theme, "rt_window_band_fill", "#152232")
            for comp in self.method.compounds:
                if comp.signal.upper() != sname.upper():
                    continue
                w0, w1 = comp.window_range
                if w1 < tx0 or w0 > tx1:
                    continue
                is_hi = (self.highlighted_compound is not None and self.highlighted_compound.name == comp.name)
                if not is_hi:
                    px0, _ = self._data_to_px(sname, max(tx0, w0), ty0, rect)
                    px1, _ = self._data_to_px(sname, min(tx1, w1), ty0, rect)
                    if px1 - px0 >= 1.0:
                        c.create_rectangle(
                            px0, y0 + 1, px1, y1 - 1,
                            fill=band_fill, outline="",
                            tags=("rt_window_band", f"rt_band_{sname}"),
                        )

        # Grid & X-axis ticks
        x_ticks = self._nice_ticks(tx0, tx1, target_count=max(4, pw // 110))
        for xt in x_ticks:
            px, _ = self._data_to_px(sname, xt, ty0, rect)
            if x0 <= px <= x1:
                c.create_line(px, y0, px, y1, fill=self.theme.grid_line, width=1)
                c.create_line(px, y1, px, y1 + 4, fill=self.theme.axis_tick, width=1)
                c.create_text(
                    px, y1 + 6,
                    text=f"{xt:g}",
                    anchor="n",
                    font=("Segoe UI", 8),
                    fill=self.theme.axis_text,
                )

        # Grid & Y-axis ticks
        y_ticks = self._nice_ticks(ty0, ty1, target_count=max(3, ph // 45))
        for yt in y_ticks:
            _, py = self._data_to_px(sname, tx0, yt, rect)
            if y0 <= py <= y1:
                c.create_line(x0, py, x1, py, fill=self.theme.grid_line, width=1)
                c.create_line(x0 - 4, py, x0, py, fill=self.theme.axis_tick, width=1)
                c.create_text(
                    x0 - 6, py,
                    text=f"{yt:g}",
                    anchor="e",
                    font=("Segoe UI", 8),
                    fill=self.theme.axis_text,
                )

        # Panel header title (like OpenLab: "MPZHY14_reaction_261015--126F.D - FID1 A, Front Signal")
        title_prefix = f"{self.injection.folder_name}  —  " if self.injection else ""
        sig_desc = sig.description if sig else sname
        unit_label = f"Response [{sig.units}]" if (sig and sig.units) else "Response [pA]"
        c.create_text(
            x0 + 6, y0 - 14,
            text=f"{title_prefix}{sig_desc}   ({unit_label})",
            anchor="w",
            font=("Segoe UI", 9, "bold"),
            fill=self.theme.panel_title,
        )

        # Vertical rotated Y-axis title on left margin ("Response [pA]") matching UPGRADE
        y_title_x = max(14, x0 - 52)
        y_title_y = (y0 + y1) * 0.5
        try:
            c.create_text(
                y_title_x,
                y_title_y,
                text=unit_label,
                anchor="center",
                angle=90,
                font=("Segoe UI", 8, "bold"),
                fill=self.theme.axis_title,
                tags=("y_axis_title",),
            )
        except tk.TclError:
            c.create_text(
                y_title_x,
                y_title_y,
                text="pA" if "pA" in unit_label else "Resp",
                anchor="center",
                font=("Segoe UI", 8, "bold"),
                fill=self.theme.axis_title,
                tags=("y_axis_title",),
            )

        rects = all_rects if all_rects is not None else self._get_panel_rects()
        is_bottom_panel = (sname == list(rects.keys())[-1])
        if is_bottom_panel:
            c.create_text(
                (x0 + x1) * 0.5, y1 + 24,
                text="Retention Time [min]",
                anchor="n",
                font=("Segoe UI", 8, "bold"),
                fill=self.theme.axis_title,
            )

        if sig is None or not sig.time_min:
            c.create_text(
                (x0 + x1) * 0.5, (y0 + y1) * 0.5 - 12,
                text=f"No {sname} signal loaded",
                font=("Segoe UI", 11, "bold"),
                fill=self.theme.label_unnamed,
            )
            c.create_text(
                (x0 + x1) * 0.5, (y0 + y1) * 0.5 + 12,
                text="Use '📂 Open .D / Sequence' or File Menu to load chromatography data",
                font=("Segoe UI", 9, "italic"),
                fill=self.theme.axis_tick,
            )
            return

        # 1b. Draw Compound Identification RT Windows (vertical dashed boundary lines)
        if self.show_rt_windows.get() and self.method:
            for comp in self.method.compounds:
                if comp.signal.upper() != sname.upper():
                    continue
                w0, w1 = comp.window_range
                if w1 < tx0 or w0 > tx1:
                    continue
                px0, _ = self._data_to_px(sname, max(tx0, w0), ty0, rect)
                px1, _ = self._data_to_px(sname, min(tx1, w1), ty0, rect)
                is_hi = (self.highlighted_compound is not None and self.highlighted_compound.name == comp.name)
                if is_hi:
                    c.create_rectangle(
                        px0, y0 + 1, px1, y1 - 1,
                        fill=self.theme.rt_window_hi_fill, outline=self.theme.rt_window_hi_line, dash=(3, 2), width=1.5
                    )
                else:
                    if tx0 <= w0 <= tx1:
                        c.create_line(px0, y0, px0, y1, fill=self.theme.rt_window_line, dash=(2, 4), width=1)
                    if tx0 <= w1 <= tx1:
                        c.create_line(px1, y0, px1, y1, fill=self.theme.rt_window_line, dash=(2, 4), width=1)

        # 2. Draw Chromatogram Trace (with soft under-curve fill & glow)
        self._draw_chromatogram_trace(sig, rect)

        # 3. Draw Integrated Peaks (shaded area for selected peak + baselines + drop lines)
        peaks = self.injection.peaks_by_signal.get(sname, []) if self.injection else []
        if self.show_baselines.get():
            for pk in peaks:
                if pk.end_min < tx0 or pk.begin_min > tx1:
                    continue
                is_sel = (pk.peak_id == self.selected_peak_id)
                self._draw_peak_baseline_and_fill(sig, pk, rect, is_sel)

        # 4. Draw Timed Integration Events (Integration ON/OFF pill badges, BaselineNow)
        if self.show_timed_events.get() and self.method and sname in self.method.signals:
            sig_cfg = self.method.signals[sname]
            pill_boxes: List[Tuple[float, float]] = []
            for ev in sig_cfg.timed_events:
                if not ev.enabled or not (tx0 <= ev.time_min <= tx1):
                    continue
                px, _ = self._data_to_px(sname, ev.time_min, ty0, rect)
                if ev.event_type == "IntegrationOn":
                    c.create_line(px, y0, px, y1, fill=self.theme.timed_event_on, dash=(4, 3), width=1)
                    pill_w, pill_h = 46.0, 14.0
                    bx0 = max(x0 + 2.0, min(x1 - pill_w - 2.0, px + 2.0))
                    bx1 = bx0 + pill_w
                    row_tier = 0
                    for ox0, ox1 in pill_boxes:
                        if not (bx1 < ox0 - 2 or bx0 > ox1 + 2):
                            row_tier += 1
                    pill_boxes.append((bx0, bx1))
                    by1 = y1 - 3.0 - row_tier * (pill_h + 2.0)
                    by0 = by1 - pill_h
                    pill_bg = getattr(self.theme, "event_on_pill_bg", "#132E28")
                    pill_bd = getattr(self.theme, "event_on_pill_border", self.theme.timed_event_on)
                    c.create_rectangle(
                        bx0, by0, bx1, by1,
                        fill=pill_bg, outline=pill_bd, width=1,
                        tags=("timed_event_badge",),
                    )
                    c.create_text(
                        (bx0 + bx1) * 0.5, (by0 + by1) * 0.5,
                        text="[ Int ON",
                        anchor="center",
                        font=("Segoe UI", 7, "bold"),
                        fill=self.theme.timed_event_on,
                    )
                elif ev.event_type == "IntegrationOff":
                    c.create_line(px, y0, px, y1, fill=self.theme.timed_event_off, dash=(4, 3), width=1)
                    pill_w, pill_h = 48.0, 14.0
                    bx1 = min(x1 - 2.0, max(x0 + pill_w + 2.0, px - 2.0))
                    bx0 = bx1 - pill_w
                    row_tier = 0
                    for ox0, ox1 in pill_boxes:
                        if not (bx1 < ox0 - 2 or bx0 > ox1 + 2):
                            row_tier += 1
                    pill_boxes.append((bx0, bx1))
                    by1 = y1 - 3.0 - row_tier * (pill_h + 2.0)
                    by0 = by1 - pill_h
                    pill_bg = getattr(self.theme, "event_off_pill_bg", "#311B22")
                    pill_bd = getattr(self.theme, "event_off_pill_border", self.theme.timed_event_off)
                    c.create_rectangle(
                        bx0, by0, bx1, by1,
                        fill=pill_bg, outline=pill_bd, width=1,
                        tags=("timed_event_badge",),
                    )
                    c.create_text(
                        (bx0 + bx1) * 0.5, (by0 + by1) * 0.5,
                        text="Int OFF ]",
                        anchor="center",
                        font=("Segoe UI", 7, "bold"),
                        fill=self.theme.timed_event_off,
                    )
                elif ev.event_type == "BaselineNow":
                    c.create_line(px, y0, px, y1, fill=self.theme.timed_event_bl, dash=(2, 3), width=1)
                    c.create_text(px, y1 - 22, text="▼BL", anchor="center", font=("Segoe UI", 7), fill=self.theme.timed_event_bl)

        # 5. Draw Peak Labels & Anchor Handles on top of trace
        self._draw_peak_labels_and_handles(sig, peaks, rect)

    def _draw_chromatogram_trace(self, sig: ChromatogramSignal, rect: Tuple[int, int, int, int]) -> None:
        c = self.canvas
        x0, y0, x1, y1 = rect
        tx0, tx1 = self.x_range
        ty0, ty1 = self.y_ranges.get(sig.name, (0.0, 100.0))

        t_arr = sig.time_min
        y_arr = sig.values
        if not t_arr or not y_arr:
            return

        # Clamp visible time window to the signal's actual time domain (fixes out-of-bounds stretching bug)
        vis_t0 = max(tx0, t_arr[0])
        vis_t1 = min(tx1, t_arr[-1])
        if vis_t1 <= vis_t0:
            return

        i0 = sig.index_at_time(vis_t0)
        i1 = sig.index_at_time(vis_t1)
        if i1 <= i0:
            return

        n_vis = i1 - i0 + 1
        pw = max(1, x1 - x0)
        dx = max(tx1 - tx0, 1e-9)
        dy = max(ty1 - ty0, 1e-9)
        ph = y1 - y0
        scale_y = ph / dy

        px_start_f = x0 + (t_arr[i0] - tx0) / dx * pw
        px_end_f = x0 + (t_arr[i1] - tx0) / dx * pw
        px_start = max(x0, min(x1, int(round(px_start_f))))
        px_end = max(x0, min(x1, int(round(px_end_f))))
        vis_pw = max(1, px_end - px_start)

        cache_key = (id(y_arr), len(y_arr), tx0, tx1, x0, x1, i0, i1, vis_pw)
        cached = self._trace_cache.get(sig.name)
        if cached is not None and cached.get("key") == cache_key:
            mode_c = cached["mode"]
            data_c = cached["data"]
        else:
            scale_x = pw / dx
            if n_vis <= vis_pw * 2:
                mode_c = "raw"
                raw_pts: List[Tuple[float, float]] = [
                    (x0 + (t_arr[idx] - tx0) * scale_x, y_arr[idx])
                    for idx in range(i0, i1 + 1)
                ]
                data_c = raw_pts
            else:
                mode_c = "env"
                # High-fidelity 1:1 pixel envelope (up to visible width, max 1200)
                n_buckets = min(vis_pw, 1200)
                env = sig.get_decimated_envelope(i0, i1, n_buckets)
                env_pts: List[Tuple[float, float, float, float, bool]] = []
                for (vmin, vmax, imin, imax) in env:
                    px_min = max(float(x0), min(float(x1), x0 + (t_arr[imin] - tx0) * scale_x))
                    px_max = max(float(x0), min(float(x1), x0 + (t_arr[imax] - tx0) * scale_x))
                    env_pts.append((px_min, px_max, vmin, vmax, imin <= imax))
                data_c = env_pts
            self._trace_cache[sig.name] = {"key": cache_key, "mode": mode_c, "data": data_c}

        coords: List[float] = []

        if mode_c == "raw":
            raw_list = data_c
            for k, (px, y_v) in enumerate(raw_list):
                py = max(float(y0), min(float(y1), y1 - (y_v - ty0) * scale_y))
                if len(coords) >= 4 and abs(py - coords[-1]) <= 0.30 and abs(coords[-1] - coords[-3]) <= 0.30:
                    coords[-2] = px
                    coords[-1] = py
                else:
                    coords.extend((px, py))
        else:
            env_list = data_c
            # Always anchor exact first visible sample
            y_first = y_arr[i0]
            py_f = max(float(y0), min(float(y1), y1 - (y_first - ty0) * scale_y))
            px_f = max(float(x0), min(float(x1), px_start_f))
            coords.extend((px_f, py_f))

            for (px_min, px_max, vmin, vmax, min_first) in env_list:
                py_min_val = max(float(y0), min(float(y1), y1 - (vmin - ty0) * scale_y))
                py_max_val = max(float(y0), min(float(y1), y1 - (vmax - ty0) * scale_y))

                if abs(py_min_val - py_max_val) <= 0.75:
                    px_mid = 0.5 * (px_min + px_max)
                    py_mid = 0.5 * (py_min_val + py_max_val)
                    if len(coords) >= 4 and abs(py_mid - coords[-1]) <= 0.35 and abs(coords[-1] - coords[-3]) <= 0.35:
                        coords[-2] = px_mid
                        coords[-1] = py_mid
                    else:
                        coords.extend((px_mid, py_mid))
                else:
                    if min_first:
                        coords.extend((px_min, py_min_val, px_max, py_max_val))
                    else:
                        coords.extend((px_max, py_max_val, px_min, py_min_val))

            # Always anchor exact last visible sample
            y_last = y_arr[i1]
            py_l = max(float(y0), min(float(y1), y1 - (y_last - ty0) * scale_y))
            px_l = max(float(x0), min(float(x1), px_end_f))
            if abs(px_l - coords[-2]) > 0.2 or abs(py_l - coords[-1]) > 0.2:
                coords.extend((px_l, py_l))

        if len(coords) >= 4:
            base_y = float(y1 - 1)
            poly_coords = [coords[0], base_y, *coords, coords[-2], base_y]
            c.create_polygon(
                *poly_coords,
                fill="",
                outline="",
                tags=("trace_under_fill", f"trace_fill_{sig.name}"),
            )

            trace_color = self.theme.trace_fid if sig.name == "FID1A" else self.theme.trace_tcd
            c.create_line(
                *coords,
                fill=trace_color,
                width=self.trace_line_width,
                joinstyle="round",
                capstyle="round",
                tags=("chromatogram_glow", f"glow_{sig.name}"),
            )

            c.create_line(
                *coords,
                fill=trace_color,
                width=self.trace_line_width,
                joinstyle="round",
                capstyle="round",
                tags=("chromatogram_trace", f"trace_{sig.name}"),
            )

    def _draw_peak_baseline_and_fill(
        self,
        sig: ChromatogramSignal,
        pk: IntegratedPeak,
        rect: Tuple[int, int, int, int],
        is_selected: bool,
    ) -> None:
        c = self.canvas
        x0, y0, x1, y1 = rect

        px_b, py_b = self._data_to_px(sig.name, pk.begin_min, pk.baseline_start_y, rect)
        px_e, py_e = self._data_to_px(sig.name, pk.end_min, pk.baseline_end_y, rect)

        # Clip baseline segment horizontally to panel
        if is_selected:
            # Draw shaded polygon between curve and baseline
            i_b = sig.index_at_time(pk.begin_min)
            i_e = sig.index_at_time(pk.end_min)
            step = max(1, (i_e - i_b) // 80)
            poly_pts: List[float] = [
                max(x0, min(x1, px_b)),
                max(y0, min(y1, py_b)),
            ]
            for idx in range(i_b, i_e + 1, step):
                px_i, py_i = self._data_to_px(sig.name, sig.time_min[idx], sig.values[idx], rect)
                poly_pts.extend((max(x0, min(x1, px_i)), max(y0, min(y1, py_i))))
            poly_pts.extend((max(x0, min(x1, px_e)), max(y0, min(y1, py_e))))
            if len(poly_pts) >= 6:
                fill_color = self.theme.shaded_neg_fill if pk.is_negative else self.theme.shaded_pos_fill
                c.create_polygon(*poly_pts, fill=fill_color, outline="")

        # Baseline line
        line_color = self.theme.baseline_selected if is_selected else (self.theme.baseline_negative if pk.is_negative else self.theme.baseline_normal)
        line_w = 2.0 if is_selected else 1.2
        if x0 <= px_b <= x1 or x0 <= px_e <= x1 or (px_b < x0 and px_e > x1):
            c.create_line(
                max(x0, min(x1, px_b)),
                max(y0, min(y1, py_b)),
                max(x0, min(x1, px_e)),
                max(y0, min(y1, py_e)),
                fill=line_color,
                width=line_w,
            )

        # Drop lines from signal curve to baseline at begin & end
        y_sig_b = sig.value_at_time(pk.begin_min)
        y_sig_e = sig.value_at_time(pk.end_min)
        _, py_sig_b = self._data_to_px(sig.name, pk.begin_min, y_sig_b, rect)
        _, py_sig_e = self._data_to_px(sig.name, pk.end_min, y_sig_e, rect)

        if x0 <= px_b <= x1:
            c.create_line(
                px_b, max(y0, min(y1, py_b)),
                px_b, max(y0, min(y1, py_sig_b)),
                fill=self.theme.peak_drop_line, width=1
            )
        if x0 <= px_e <= x1:
            c.create_line(
                px_e, max(y0, min(y1, py_e)),
                px_e, max(y0, min(y1, py_sig_e)),
                fill=self.theme.peak_drop_line, width=1
            )

    def _draw_peak_labels_and_handles(
        self,
        sig: ChromatogramSignal,
        peaks: List[IntegratedPeak],
        rect: Tuple[int, int, int, int],
    ) -> None:
        c = self.canvas
        x0, y0, x1, y1 = rect

        for pk in peaks:
            is_sel = (pk.peak_id == self.selected_peak_id)

            # Draw draggable anchor circles with per-anchor tags for O(1) hover updates
            for end_kind, t_anc, y_anc in (
                ("start", pk.begin_min, pk.baseline_start_y),
                ("end", pk.end_min, pk.baseline_end_y),
            ):
                px_a, py_a = self._data_to_px(sig.name, t_anc, y_anc, rect)
                if x0 <= px_a <= x1 and y0 <= py_a <= y1:
                    is_hov = (self._hover_anchor == (sig.name, pk.peak_id, end_kind))
                    r = 5 if (is_hov or is_sel or self.tool_mode == "drag_anchor") else 3
                    fill_c = self.theme.baseline_selected if is_hov else (self.theme.anchor_selected if is_sel else self.theme.anchor_fill)
                    out_c = self.theme.baseline_selected if (is_hov or is_sel) else self.theme.anchor_outline
                    c.create_oval(
                        px_a - r, py_a - r, px_a + r, py_a + r,
                        fill=fill_c, outline=out_c, width=1.5,
                        tags=("anchor_handle", f"anchor_{sig.name}_{pk.peak_id}_{end_kind}"),
                    )

        if not self.show_compound_labels.get():
            return

        # Fast Drag Optimization: During active panning / x-axis dragging across large screens,
        # skip label placement to maintain silky 60 FPS navigation. Labels immediately reappear on mouse release.
        if self._drag_state is not None and self._drag_state.get("mode") in ("pan", "x_axis_pan", "y_axis_pan", "x_axis_scale", "y_amplitude"):
            return

        vis_peaks = [pk for pk in peaks if self.x_range[0] <= pk.rt_min <= self.x_range[1]]
        if not vis_peaks:
            return

        # Level of Detail (LOD): When completely zoomed out (span > 20 min),
        # only render peak labels for identified compounds or peaks with significant area (> 0.5%)
        # or selected peak. This keeps redraw latency under 3 ms even when zoomed out!
        span = self.x_range[1] - self.x_range[0]
        if span > 20.0:
            total_sig_area = sum(p.area for p in peaks) if peaks else 0.0
            area_thresh = 0.005 * total_sig_area if total_sig_area > 0 else 0.5
            vis_peaks = [
                pk for pk in vis_peaks
                if pk.compound_name or (pk.peak_id == self.selected_peak_id) or (pk.area >= area_thresh)
            ]
            if not vis_peaks:
                return

        # Prioritize selected peak, named compounds, and larger peaks for ideal label placement
        sorted_peaks = sorted(
            vis_peaks,
            key=lambda p: (
                p.peak_id == self.selected_peak_id,
                bool(p.compound_name),
                p.area,
            ),
            reverse=True,
        )

        bin_size = 60
        spatial_grid = defaultdict(list)
        is_dragging = (self._drag_state is not None)

        for pk in sorted_peaks:
            is_sel = (pk.peak_id == self.selected_peak_id)
            y_apex = sig.value_at_time(pk.rt_min)
            px_rt, py_rt = self._data_to_px(sig.name, pk.rt_min, y_apex, rect)

            # Draw apex marker (neat apex dot matching UPGRADE spec)
            if py_rt < y0:
                # Peak apex is clipped off top (off-scale peak like MeOH)
                c.create_polygon(
                    px_rt, y0 + 2,
                    px_rt - 4, y0 + 8,
                    px_rt + 4, y0 + 8,
                    fill=self.theme.apex_marker, outline=""
                )
                py_apex_draw = y0 + 10.0
                is_off_top = True
            elif py_rt > y1:
                # Negative peak apex clipped off bottom
                c.create_polygon(
                    px_rt, y1 - 2,
                    px_rt - 4, y1 - 8,
                    px_rt + 4, y1 - 8,
                    fill=self.theme.apex_marker, outline=""
                )
                py_apex_draw = y1 - 10.0
                is_off_top = False
            else:
                c.create_oval(
                    px_rt - 2.5, py_rt - 2.5, px_rt + 2.5, py_rt + 2.5,
                    fill=self.theme.apex_marker, outline="",
                    tags=("apex_marker",),
                )
                py_apex_draw = py_rt
                is_off_top = False

            if pk.compound_name:
                lbl_text = f"{pk.compound_name}\n{pk.rt_min:.3f}"
                lbl_color = self.theme.label_selected if is_sel else self.theme.label_compound
                lbl_font = ("Segoe UI", 8, "bold")
                char_w = 6.5
                line_h = 13.0
            else:
                lbl_text = f"{pk.rt_min:.3f}"
                lbl_color = self.theme.label_selected if is_sel else self.theme.label_unnamed
                lbl_font = ("Segoe UI", 7)
                char_w = 5.5
                line_h = 11.0

            lines = lbl_text.split("\n")
            max_len = max(len(l) for l in lines)
            est_w = max_len * char_w + 4.0
            est_h = len(lines) * line_h + 2.0
            half_w = est_w * 0.5

            if is_dragging:
                # Fast Drag Mode: Bypass the 70-candidate collision loop to guarantee 60+ FPS responsiveness
                if not pk.is_negative:
                    cy = max(y0 + est_h + 2.0, py_apex_draw - 4.0)
                else:
                    cy = min(y1 - 2.0, py_apex_draw + est_h + 4.0)
                cx = max(x0 + half_w + 4.0, min(x1 - half_w - 4.0, px_rt))
                c.create_text(
                    cx, cy,
                    text=lbl_text,
                    anchor="s",
                    justify="center",
                    font=lbl_font,
                    fill=lbl_color,
                )
                continue

            # Multi-tier candidate search space with horizontal staggering
            x_shifts = [0.0, -half_w * 0.6, half_w * 0.6, -half_w * 1.2, half_w * 1.2]
            candidates = []

            if not pk.is_negative:
                if is_off_top:
                    # Off-scale peak: space is DOWNWARD from top ceiling (up to 10 tiers)
                    for tier in range(10):
                        cy = y0 + 12.0 + est_h + tier * (est_h + 3.0)
                        if cy <= y1 - 4:
                            for dx in x_shifts:
                                candidates.append((px_rt + dx, cy))
                else:
                    # Normal peak: upward tiers first, then downward tiers
                    for tier in range(8):
                        cy = py_apex_draw - 4.0 - tier * (est_h + 3.0)
                        if cy - est_h >= y0 + 2:
                            for dx in x_shifts:
                                candidates.append((px_rt + dx, cy))
                    for tier in range(6):
                        cy = py_apex_draw + est_h + 8.0 + tier * (est_h + 3.0)
                        if cy <= y1 - 4:
                            for dx in x_shifts:
                                candidates.append((px_rt + dx, cy))
            else:
                if py_rt > y1:
                    # Off-scale negative peak: space is UPWARD from bottom floor (up to 10 tiers)
                    for tier in range(10):
                        cy = y1 - 12.0 - tier * (est_h + 3.0)
                        if cy - est_h >= y0 + 2:
                            for dx in x_shifts:
                                candidates.append((px_rt + dx, cy))
                else:
                    # Normal negative peak: downward tiers first, then upward tiers
                    for tier in range(8):
                        cy = py_apex_draw + est_h + 6.0 + tier * (est_h + 3.0)
                        if cy <= y1 - 4:
                            for dx in x_shifts:
                                candidates.append((px_rt + dx, cy))
                    for tier in range(6):
                        cy = py_apex_draw - 4.0 - tier * (est_h + 3.0)
                        if cy - est_h >= y0 + 2:
                            for dx in x_shifts:
                                candidates.append((px_rt + dx, cy))

            best_candidate = None
            for cx, cy in candidates:
                # Clamp horizontal position strictly inside panel bounds
                if cx - half_w < x0 + 4:
                    cx = x0 + 4 + half_w
                elif cx + half_w > x1 - 4:
                    cx = x1 - 4 - half_w

                bx0 = cx - half_w
                bx1 = cx + half_w
                by0 = cy - est_h
                by1 = cy

                if by0 < y0 + 2 or by1 > y1 - 2:
                    continue

                b_min = int(bx0 // bin_size)
                b_max = int(bx1 // bin_size)
                collides = False
                seen_boxes = set()

                for b in range(b_min, b_max + 1):
                    for box_tuple in spatial_grid[b]:
                        if box_tuple in seen_boxes:
                            continue
                        seen_boxes.add(box_tuple)
                        ox0, oy0, ox1, oy1 = box_tuple
                        if not (bx1 < ox0 - 1 or bx0 > ox1 + 1 or by1 < oy0 - 1 or by0 > oy1 + 1):
                            collides = True
                            break
                    if collides:
                        break

                if not collides:
                    best_candidate = (cx, cy, bx0, by0, bx1, by1)
                    break

            if best_candidate is not None:
                fin_cx, fin_cy, f_bx0, f_by0, f_bx1, f_by1 = best_candidate

                # Draw subtle leader line if label is significantly shifted from apex
                if math.hypot(fin_cx - px_rt, (fin_cy - est_h * 0.5) - py_apex_draw) > 16:
                    leader_target_y = fin_cy if not pk.is_negative else (fin_cy - est_h)
                    c.create_line(
                        px_rt, py_apex_draw,
                        fin_cx, leader_target_y,
                        fill=self.theme.leader_line, dash=(2, 2), width=1
                    )

                c.create_text(
                    fin_cx, fin_cy,
                    text=lbl_text,
                    anchor="s",
                    justify="center",
                    font=lbl_font,
                    fill=lbl_color,
                )
                f_box = (f_bx0, f_by0, f_bx1, f_by1)
                b_min = int(f_box[0] // bin_size)
                b_max = int(f_box[2] // bin_size)
                for b in range(b_min, b_max + 1):
                    spatial_grid[b].append(f_box)
            else:
                # Fallback suppression: DO NOT render overlapping text over candidates[0]
                pass

    # ------------------------------------------------------------------
    # Mouse & Manual Integration Event Handlers
    # ------------------------------------------------------------------

    def _find_nearest_anchor(self, mx: int, my: int, max_dist_px: float = 10.0) -> Optional[Tuple[str, str, str]]:
        """Return (sig_name, peak_id, 'start'|'end') if cursor is near a baseline anchor."""
        if not self.injection:
            return None
        rects = self._get_panel_rects()
        best = None
        best_d = max_dist_px
        for sname, rect in rects.items():
            x0, y0, x1, y1 = rect
            if not (x0 - 8 <= mx <= x1 + 8 and y0 - 8 <= my <= y1 + 8):
                continue
            for pk in self.injection.peaks_by_signal.get(sname, []):
                for kind, t_a, y_a in (
                    ("start", pk.begin_min, pk.baseline_start_y),
                    ("end", pk.end_min, pk.baseline_end_y),
                ):
                    px, py = self._data_to_px(sname, t_a, y_a, rect)
                    d = math.hypot(mx - px, my - py)
                    if d <= best_d:
                        best_d = d
                        best = (sname, pk.peak_id, kind)
        return best

    def _find_nearest_peak(self, mx: int, my: int) -> Optional[IntegratedPeak]:
        """Find peak clicked near its apex or baseline."""
        if not self.injection:
            return None
        rects = self._get_panel_rects()
        sname = self._panel_at_xy(mx, my)
        if not sname or sname not in self.injection.signals:
            return None
        rect = rects[sname]
        sig = self.injection.signals[sname]
        t_click, y_click = self._px_to_data(sname, mx, my, rect)

        # Check apex proximity in pixels first
        best_pk = None
        best_dist = 24.0
        for pk in self.injection.peaks_by_signal.get(sname, []):
            px_rt, py_rt = self._data_to_px(sname, pk.rt_min, sig.value_at_time(pk.rt_min), rect)
            d = math.hypot(mx - px_rt, my - py_rt)
            if d < best_dist:
                best_dist = d
                best_pk = pk
        if best_pk is not None:
            return best_pk

        # Otherwise check if click is horizontally inside a peak span
        containing = [
            pk
            for pk in self.injection.peaks_by_signal.get(sname, [])
            if pk.begin_min <= t_click <= pk.end_min
        ]
        if containing:
            return min(containing, key=lambda p: p.end_min - p.begin_min)
        return None

    def _on_mouse_move(self, event: tk.Event) -> None:
        self._cursor_pos = (event.x, event.y)
        prev_hov = self._hover_anchor
        self._hover_anchor = self._find_nearest_anchor(event.x, event.y)
        rects: Optional[Dict[str, Tuple[int, int, int, int]]] = None
        if self._hover_anchor != prev_hov:
            rects = self._get_panel_rects()
            self._update_anchor_hover_item(prev_hov, False, rects=rects)
            self._update_anchor_hover_item(self._hover_anchor, True, rects=rects)
        if self.tool_mode == "split_peak":
            if rects is None:
                rects = self._get_panel_rects()
            self._update_cursor_overlay(rects=rects)

    def _on_left_down(self, event: tk.Event) -> None:
        if not self.injection:
            return
        rects = self._get_panel_rects()
        if not rects:
            return

        # 1. Check if clicking an anchor handle (works in both 'drag_anchor' and 'pan_zoom' modes!)
        anc = self._find_nearest_anchor(event.x, event.y, max_dist_px=11.0)
        if anc is not None and self.tool_mode in ("drag_anchor", "pan_zoom"):
            a_sname, pk_id, kind = anc
            self.selected_peak_id = pk_id
            if self.on_peak_selected:
                pk_obj = next((p for p in self.injection.peaks_by_signal.get(a_sname, []) if p.peak_id == pk_id), None)
                self.on_peak_selected(pk_obj)
            self._drag_state = {
                "mode": "anchor",
                "sname": a_sname,
                "peak_id": pk_id,
                "kind": kind,
            }
            self.redraw()
            return

        # 2. Split peak mode
        if self.tool_mode == "split_peak":
            sname = self._panel_at_xy(event.x, event.y)
            if sname and sname in self.injection.signals:
                rect = rects[sname]
                t_split, _ = self._px_to_data(sname, event.x, event.y, rect)
                sig = self.injection.signals[sname]
                pks = self.injection.peaks_by_signal.get(sname, [])
                self.injection.peaks_by_signal[sname] = split_peak_at(sig, pks, t_split, self.method)
                self.injection.integration_source = "manual"
                if self.on_peaks_modified:
                    self.on_peaks_modified(f"Split peak on {sname} at {t_split:.3f} min")
                self.redraw()
            return

        # 3. Draw new peak mode
        if self.tool_mode == "draw_peak":
            sname = self._panel_at_xy(event.x, event.y)
            if sname and sname in self.injection.signals:
                rect = rects[sname]
                t0, y0 = self._px_to_data(sname, event.x, event.y, rect)
                if self.snap_anchors_to_trace.get():
                    y0 = self.injection.signals[sname].value_at_time(t0)
                px0, py0 = self._data_to_px(sname, t0, y0, rect)
                self._drag_state = {
                    "mode": "draw_peak",
                    "sname": sname,
                    "t0": t0,
                    "y0": y0,
                    "start_px": (px0, py0),
                    "cur_px": (event.x, event.y),
                }
                self._update_drag_overlay(rects=rects)
            return

        # 4. Standard Left-Click navigation modes (Feature F21 / R3):
        zone, zone_sname = self._hit_test_zone(event.x, event.y)

        # 4a. Y-Axis Gutter Pan (relative translation, constant scale)
        if zone == "y_axis":
            sname = zone_sname or self._panel_at_xy(event.x, event.y) or list(rects.keys())[0]
            self._drag_state = {
                "mode": "y_axis_pan",
                "sname": sname,
                "start_px": event.x,
                "start_py": event.y,
                "orig_y_range": self.y_ranges.get(sname, (0.0, 100.0)),
            }
            self.canvas.configure(cursor="sb_v_double_arrow")
            return

        # 4b. X-Axis Gutter Pan (relative translation, constant scale)
        if zone == "x_axis":
            sname = zone_sname or list(rects.keys())[-1]
            self._drag_state = {
                "mode": "x_axis_pan",
                "sname": sname,
                "start_px": event.x,
                "start_py": event.y,
                "orig_x_range": self.x_range,
            }
            self.canvas.configure(cursor="sb_h_double_arrow")
            return

        # 4c. Plot Body: Shift+Left-drag = 2D Pan; Direct Left-drag = Agilent Box Zoom (F07)
        sname = zone_sname or self._panel_at_xy(event.x, event.y)
        if not sname or sname not in self.injection.signals:
            return

        shift_pressed = bool(event.state & 0x0001)
        if shift_pressed:
            self._drag_state = {
                "mode": "pan",
                "sname": sname,
                "start_px": (event.x, event.y),
                "orig_x_range": self.x_range,
                "orig_y_range": self.y_ranges.get(sname, (0.0, 100.0)),
            }
        else:
            self._drag_state = {
                "mode": "zoom_box",
                "sname": sname,
                "start_px": (event.x, event.y),
                "cur_px": (event.x, event.y),
            }
            self._update_drag_overlay(rects=rects)

    def _on_left_drag(self, event: tk.Event) -> None:
        if not self._drag_state or not self.injection:
            return
        rects = self._get_panel_rects()
        mode = self._drag_state["mode"]
        sname = self._drag_state["sname"]
        rect = rects.get(sname)
        if not rect and mode != "x_axis_pan":
            return

        if mode == "anchor":
            sig = self.injection.signals[sname]
            pk_id = self._drag_state["peak_id"]
            kind = self._drag_state["kind"]
            t_new, y_new = self._px_to_data(sname, event.x, event.y, rect)
            t_new = max(sig.time_min[0], min(sig.time_min[-1], t_new))
            shift_pressed = bool(event.state & 0x0001)
            alt_pressed = bool(event.state & 0x20000)

            pks = self.injection.peaks_by_signal.get(sname, [])
            target_pk = next((p for p in pks if p.peak_id == pk_id), None)

            # If Shift is held, lock to horizontal baseline matching opposite anchor's Y
            if shift_pressed and target_pk is not None:
                if kind == "start":
                    y_new = target_pk.baseline_end_y
                else:
                    y_new = target_pk.baseline_start_y
            elif self.snap_anchors_to_trace.get() and not alt_pressed:
                y_new = sig.value_at_time(t_new)

            for pk in pks:
                if pk.peak_id == pk_id:
                    if kind == "start":
                        nb_t, nb_y = min(t_new, pk.end_min - 0.005), y_new
                        ne_t, ne_y = pk.end_min, pk.baseline_end_y
                    else:
                        nb_t, nb_y = pk.begin_min, pk.baseline_start_y
                        ne_t, ne_y = max(t_new, pk.begin_min + 0.005), y_new
                    update_peak_anchors(sig, pks, pk_id, nb_t, nb_y, ne_t, ne_y, self.method)
                    break
            self.request_redraw()

        elif mode == "zoom_box":
            cx = max(rect[0], min(rect[2], event.x))
            cy = max(rect[1], min(rect[3], event.y))
            self._drag_state["cur_px"] = (cx, cy)
            self._update_drag_overlay(rects=rects)

        elif mode == "draw_peak":
            shift_pressed = bool(event.state & 0x0001)
            self._drag_state["shift_constrained"] = shift_pressed
            cur_x = event.x
            cur_y = self._drag_state["start_px"][1] if shift_pressed else event.y
            self._drag_state["cur_px"] = (cur_x, cur_y)
            self._update_drag_overlay(rects=rects)

        elif mode == "pan":
            x0, y0, x1, y1 = rect
            sx, sy = self._drag_state["start_px"]
            ox0, ox1 = self._drag_state["orig_x_range"]
            oy0, oy1 = self._drag_state["orig_y_range"]
            dx_data = (event.x - sx) / max(1, x1 - x0) * (ox1 - ox0)
            dy_data = (event.y - sy) / max(1, y1 - y0) * (oy1 - oy0)
            self.x_range = (max(0.0, ox0 - dx_data), min(40.0, ox1 - dx_data))
            self.y_ranges[sname] = (oy0 + dy_data, oy1 + dy_data)
            self.request_redraw()

        elif mode == "y_axis_pan":
            x0, y0, x1, y1 = rect
            sy = self._drag_state["start_py"]
            oy0, oy1 = self._drag_state["orig_y_range"]
            orig_span = oy1 - oy0
            dy_data = (event.y - sy) / max(1, y1 - y0) * orig_span
            self.y_ranges[sname] = (oy0 + dy_data, oy1 + dy_data)
            self.request_redraw()

        elif mode == "x_axis_pan":
            pan_rect = rect or rects[list(rects.keys())[-1]]
            x0, y0, x1, y1 = pan_rect
            sx = self._drag_state["start_px"]
            ox0, ox1 = self._drag_state["orig_x_range"]
            orig_span = ox1 - ox0
            dx_data = (event.x - sx) / max(1, x1 - x0) * orig_span
            self.x_range = (ox0 - dx_data, ox1 - dx_data)
            self.request_redraw()

    def _on_left_up(self, event: tk.Event) -> None:
        if not self._drag_state or not self.injection:
            self._drag_state = None
            return
        mode = self._drag_state["mode"]
        sname = self._drag_state["sname"]
        rects = self._get_panel_rects()
        rect = rects.get(sname)

        if mode in ("y_axis_pan", "x_axis_pan"):
            cursors = {
                "pan_zoom": "arrow",
                "drag_anchor": "hand2",
                "draw_peak": "crosshair",
                "split_peak": "sb_h_double_arrow",
            }
            self.canvas.configure(cursor=cursors.get(self.tool_mode, "arrow"))
            self._drag_state = None
            self.request_redraw(immediate=True)
            return

        if mode == "anchor":
            self.injection.integration_source = "manual"
            if self.on_peaks_modified:
                self.on_peaks_modified(f"Adjusted baseline anchor on {sname}")

        elif mode == "draw_peak" and rect:
            t0 = self._drag_state["t0"]
            y0 = self._drag_state["y0"]
            shift_pressed = bool(event.state & 0x0001) or self._drag_state.get("shift_constrained", False)
            if shift_pressed:
                # Force perfect horizontal baseline (y1 = y0)
                t1, _ = self._px_to_data(sname, event.x, event.y, rect)
                y1 = y0
                snap_to_curve = False
            else:
                t1, y1 = self._px_to_data(sname, event.x, event.y, rect)
                snap_to_curve = self.snap_anchors_to_trace.get()

            sig = self.injection.signals[sname]
            pks = self.injection.peaks_by_signal.get(sname, [])
            updated, new_pk = add_manual_peak(
                sig, pks, t0, y0, t1, y1,
                method=self.method,
                snap_to_curve=snap_to_curve,
            )
            self.injection.peaks_by_signal[sname] = updated
            if new_pk is not None:
                self.selected_peak_id = new_pk.peak_id
                self.injection.integration_source = "manual"
                if self.on_peaks_modified:
                    self.on_peaks_modified(
                        f"Added manual {'negative ' if new_pk.is_negative else ''}peak @ {new_pk.rt_min:.3f} min (Area={new_pk.area:.3f})"
                    )
                if self.on_peak_selected:
                    self.on_peak_selected(new_pk)

        elif mode == "zoom_box" and rect:
            sx, sy = self._drag_state["start_px"]
            dx = abs(event.x - sx)
            dy = abs(event.y - sy)
            if dx <= 5 and dy <= 5:
                # Click without drag: select peak under cursor or deselect
                clicked_pk = self._find_nearest_peak(event.x, event.y)
                if clicked_pk is not None:
                    self.selected_peak_id = clicked_pk.peak_id
                    if self.on_peak_selected:
                        self.on_peak_selected(clicked_pk)
                else:
                    self.selected_peak_id = None
                    if self.on_peak_selected:
                        self.on_peak_selected(None)
            else:
                # Dragged box: zoom X and Y into selected box region (Feature F07)
                t_a, y_a = self._px_to_data(sname, sx, sy, rect)
                t_b, y_b = self._px_to_data(sname, event.x, event.y, rect)
                if dx >= 6:
                    t_min = min(t_a, t_b)
                    t_max = max(t_a, t_b)
                    max_t = max((s.time_min[-1] for s in self.injection.signals.values() if s.time_min), default=40.0)
                    t_min = max(0.0, t_min)
                    t_max = min(max_t, t_max)
                    if t_max - t_min >= 0.02:
                        self.x_range = (t_min, t_max)
                if dy >= 6:
                    y_min = min(y_a, y_b)
                    y_max = max(y_a, y_b)
                    if y_max - y_min >= 1e-6:
                        self.y_ranges[sname] = (y_min, y_max)

        self._drag_state = None
        self.request_redraw(immediate=True)

    def _on_right_down(self, event: tk.Event) -> None:
        if not self.injection:
            return
        rects = self._get_panel_rects()
        if not rects:
            return

        zone, zone_sname = self._hit_test_zone(event.x, event.y)

        # Right-drag on X-axis: adjust time scale (Feature F21 / R3)
        if zone == "x_axis":
            sname = zone_sname or list(rects.keys())[-1]
            self._drag_state = {
                "mode": "x_axis_scale",
                "sname": sname,
                "start_px": event.x,
                "start_py": event.y,
                "orig_x_range": self.x_range,
            }
            self.canvas.configure(cursor="sb_h_double_arrow")
            return

        # Right-drag on Y-axis gutter or Plot Body: dynamic vertical amplitude scaling (Feature F08 / R3)
        sname = zone_sname or self._panel_at_xy(event.x, event.y)
        if not sname or sname not in self.injection.signals:
            sname = list(rects.keys())[0]

        self._drag_state = {
            "mode": "y_amplitude",
            "sname": sname,
            "start_py": event.y,
            "start_px": event.x,
            "orig_y_range": self.y_ranges.get(sname, (0.0, 100.0)),
        }
        self.canvas.configure(cursor="sb_v_double_arrow")

    def _on_right_drag(self, event: tk.Event) -> None:
        if not self._drag_state:
            return
        mode = self._drag_state.get("mode")

        if mode == "x_axis_scale":
            start_px = self._drag_state["start_px"]
            dx = event.x - start_px
            factor = math.pow(2.0, -dx / 100.0)
            factor = max(0.01, min(100.0, factor))

            orig_x0, orig_x1 = self._drag_state["orig_x_range"]
            orig_span = orig_x1 - orig_x0
            new_span = max(0.05, orig_span * factor)
            self.x_range = (orig_x0, orig_x0 + new_span)
            self.request_redraw()

        elif mode == "y_amplitude":
            sname = self._drag_state["sname"]
            start_py = self._drag_state["start_py"]
            dy = start_py - event.y  # upward mouse motion = positive dy

            # Feature F08: Scaling factor 2.0 ** (-dy / 100.0)
            # dy > 0 (drag up) -> factor < 1 -> amplitude increases (taller peaks)
            # dy < 0 (drag down) -> factor > 1 -> amplitude decreases (shorter peaks)
            factor = math.pow(2.0, -dy / 100.0)
            factor = max(0.001, min(1000.0, factor))

            orig_y0, orig_y1 = self._drag_state["orig_y_range"]
            orig_span = orig_y1 - orig_y0
            new_span = max(0.001, orig_span * factor)

            # Anchored to baseline (orig_y0) without altering horizontal time range (self.x_range)
            self.y_ranges[sname] = (orig_y0, orig_y0 + new_span)
            self.request_redraw()

    def _on_right_up(self, event: tk.Event) -> None:
        if not self._drag_state:
            return
        start_px = self._drag_state.get("start_px", event.x)
        start_py = self._drag_state.get("start_py", event.y)
        dx = event.x - start_px
        dy = event.y - start_py
        dist = math.hypot(dx, dy)

        cursors = {
            "pan_zoom": "arrow",
            "drag_anchor": "hand2",
            "draw_peak": "crosshair",
            "split_peak": "sb_h_double_arrow",
        }
        self.canvas.configure(cursor=cursors.get(self.tool_mode, "arrow"))
        self._drag_state = None

        if dist <= 5:
            # Right-click tap without drag: dispatch context actions (Feature F27 / R6)
            self._handle_right_click_context(event)
        else:
            self.request_redraw(immediate=True)

    def _handle_right_click_context(self, event: tk.Event) -> None:
        """Dispatches right-click context menu event to registered callback or virtual event."""
        hit_type, hit_info = self.hit_test_integration_element(event.x, event.y)
        if self.on_context_menu_callback is not None:
            self.on_context_menu_callback(event, hit_type, hit_info)
        else:
            try:
                self.canvas.event_generate("<<CanvasContextMenu>>", x=event.x, y=event.y)
            except Exception:
                pass

    def _on_double_click_reset(self, event: Optional[tk.Event] = None) -> None:
        """Reset both time (X) and signal (Y) axes to default auto-scaled bounds (Feature F09)."""
        self._drag_state = None
        cursors = {
            "pan_zoom": "arrow",
            "drag_anchor": "hand2",
            "draw_peak": "crosshair",
            "split_peak": "sb_h_double_arrow",
        }
        self.canvas.configure(cursor=cursors.get(self.tool_mode, "arrow"))
        self.reset_view()

    def _on_double_click(self, event: tk.Event) -> None:
        """Backward compatibility alias for double click view reset."""
        self._on_double_click_reset(event)

    def reset_view(self) -> None:
        """Reset both time (X) and signal (Y) axes to default auto-scaled bounds."""
        if not self.injection or not self.injection.signals:
            self.x_range = (3.5, 16.5)
            self.redraw()
            return
        max_t = max((s.time_min[-1] for s in self.injection.signals.values() if s.time_min), default=40.0)
        if max_t >= 16.5:
            self.zoom_active_region()
        else:
            self.zoom_full_range()

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        rects = self._get_panel_rects()
        sname = self._panel_at_xy(event.x, event.y)
        if not sname or sname not in rects:
            return
        rect = rects[sname]
        factor = 0.82 if event.delta > 0 else 1.22

        shift_pressed = bool(event.state & 0x0001)
        on_y_axis = (event.x < rect[0])

        if shift_pressed or on_y_axis:
            # Zoom Y-axis of hovered panel independently
            _, y_center = self._px_to_data(sname, event.x, event.y, rect)
            y0, y1 = self.y_ranges.get(sname, (0.0, 100.0))
            ny0 = y_center - (y_center - y0) * factor
            ny1 = y_center + (y1 - y_center) * factor
            self.y_ranges[sname] = (ny0, ny1)
        else:
            # Zoom synchronized X-axis centered at cursor
            t_center, _ = self._px_to_data(sname, event.x, event.y, rect)
            x0, x1 = self.x_range
            nx0 = max(0.0, t_center - (t_center - x0) * factor)
            nx1 = min(40.0, t_center + (x1 - t_center) * factor)
            if nx1 - nx0 > 0.05:
                self.x_range = (nx0, nx1)
        self.request_redraw()
