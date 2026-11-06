"""
Chromatogram Integration Engine (Automatic + OpenLab .rx + Interactive Manual Integration)
and Compound Identification Engine.
"""

import json
import math
import os
import uuid
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from .ch_reader import ChromatogramSignal, InjectionData, IntegratedPeak, read_rx_peaks
from .method_model import CompoundDef, ProcessingMethod, SignalMethodConfig


MANUAL_OVERRIDES_FILENAME = "openlab_sub_manual.json"


def recalculate_peak_metrics(
    sig: ChromatogramSignal,
    peak: IntegratedPeak,
) -> IntegratedPeak:
    """
    Recalculate apex RT, gross area (response * seconds), height, and width
    for a single peak from its (begin_min, end_min, baseline_start_y, baseline_end_y).
    Includes full protection against empty signals, NaN/Inf, and inverted boundaries.
    """
    if not sig.time_min or not sig.values:
        peak.area = 0.0
        peak.height = 0.0
        peak.width_min = 0.0
        return peak

    t_min_limit = sig.time_min[0]
    t_max_limit = sig.time_min[-1]

    if not isinstance(peak.begin_min, (int, float)) or math.isnan(peak.begin_min) or math.isinf(peak.begin_min):
        peak.begin_min = t_min_limit
    if not isinstance(peak.end_min, (int, float)) or math.isnan(peak.end_min) or math.isinf(peak.end_min):
        peak.end_min = t_max_limit

    if peak.end_min < peak.begin_min:
        peak.begin_min, peak.end_min = peak.end_min, peak.begin_min
        peak.baseline_start_y, peak.baseline_end_y = peak.baseline_end_y, peak.baseline_start_y

    if not isinstance(peak.baseline_start_y, (int, float)) or math.isnan(peak.baseline_start_y) or math.isinf(peak.baseline_start_y):
        peak.baseline_start_y = sig.value_at_time(peak.begin_min)
    if not isinstance(peak.baseline_end_y, (int, float)) or math.isnan(peak.baseline_end_y) or math.isinf(peak.baseline_end_y):
        peak.baseline_end_y = sig.value_at_time(peak.end_min)

    n_pts = min(len(sig.time_min), len(sig.values))
    i_start = sig.index_at_time(peak.begin_min)
    i_end = sig.index_at_time(peak.end_min)

    if i_start < 0:
        i_start = 0
    if i_start >= n_pts:
        i_start = n_pts - 1
    if i_end < i_start:
        i_end = i_start
    if i_end <= i_start and n_pts > 1:
        i_end = min(n_pts - 1, i_start + 1)

    tb = peak.begin_min
    te = peak.end_min
    span = te - tb if abs(te - tb) > 1e-9 else 1e-9
    yb = peak.baseline_start_y
    ye = peak.baseline_end_y
    dt_s = sig.dt_sec if sig.dt_sec > 0 else (60.0 * (te - tb) / max(1, i_end - i_start))

    sign = -1.0 if peak.is_negative else 1.0

    best_h = -1e30
    best_rt = 0.5 * (tb + te)
    net_vals: List[float] = []

    for idx in range(i_start, min(n_pts, i_end + 1)):
        ti = sig.time_min[idx]
        yi = sig.values[idx]
        if not isinstance(yi, (int, float)) or math.isnan(yi) or math.isinf(yi):
            yi = 0.0
        base_y = yb + (ye - yb) * ((ti - tb) / span)
        diff = sign * (yi - base_y)
        net_vals.append(diff)
        if diff > best_h:
            best_h = diff
            best_rt = ti

    # Trapezoidal rule in seconds
    area = 0.0
    for k in range(len(net_vals) - 1):
        v0 = max(0.0, net_vals[k])
        v1 = max(0.0, net_vals[k + 1])
        area += 0.5 * (v0 + v1) * dt_s

    peak.rt_min = best_rt
    peak.area = max(0.0, area)
    peak.height = max(0.0, best_h if best_h != -1e30 else 0.0)
    peak.width_min = max(0.0, te - tb)
    return peak


def recalculate_signal_peaks(
    sig: ChromatogramSignal,
    peaks: List[IntegratedPeak],
    method: Optional[ProcessingMethod] = None,
) -> List[IntegratedPeak]:
    """
    Recalculate all peaks on a signal, subtract tangent-skimmed rider areas
    from any enclosing parent peak (e.g. rider peaks on CH3OH tail), update
    Area% and Height%, and run Compound Identification if method is provided.
    """
    for pk in peaks:
        recalculate_peak_metrics(sig, pk)

    # Sort by retention time
    peaks.sort(key=lambda p: p.rt_min)

    # Check for rider peaks enclosed inside a larger parent peak (e.g., CH3OH 6.758-8.562 min)
    for parent in peaks:
        if parent.is_tangent_skim or parent.is_negative:
            continue
        rider_area_sum = 0.0
        for child in peaks:
            if child is parent or child.is_negative:
                continue
            # A child peak is a rider on `parent` if its time span lies within `parent`
            if (
                child.begin_min >= parent.begin_min - 0.002
                and child.end_min <= parent.end_min + 0.002
                and (child.end_min - child.begin_min) < 0.75 * (parent.end_min - parent.begin_min)
            ):
                child.is_tangent_skim = True
                if not child.baseline_code.endswith("t"):
                    child.baseline_code = "MM t"
                rider_area_sum += child.area
        if rider_area_sum > 0.0 and parent.area > rider_area_sum:
            parent.area -= rider_area_sum

    total_area = sum(p.area for p in peaks)
    total_height = sum(p.height for p in peaks)

    for pk in peaks:
        pk.area_pct = (pk.area / total_area * 100.0) if total_area > 0 else 0.0
        pk.height_pct = (pk.height / total_height * 100.0) if total_height > 0 else 0.0

    if method is not None:
        identify_peaks_for_signal(sig.name, peaks, method)

    return peaks


def identify_peaks_for_signal(
    arg1,
    arg2,
    arg3,
) -> None:
    """
    Assign compound names to peaks using the Method Compound Table.
    Matches retention time window AND strictly checks polarity (pk.is_negative == comp.is_negative_peak).
    Supports both (signal_name, peaks, method) and (peaks, method, signal_name) calling signatures.
    """
    if isinstance(arg1, str):
        signal_name = arg1
        peaks = arg2
        method = arg3
    elif isinstance(arg1, list):
        peaks = arg1
        if isinstance(arg2, str):
            signal_name = arg2
            method = arg3
        else:
            method = arg2
            signal_name = arg3
    else:
        signal_name = str(arg1)
        peaks = arg2
        method = arg3

    if method is None or not hasattr(method, "compounds"):
        return

    for pk in peaks:
        pk.compound_name = ""
        pk.expected_rt = 0.0

    sig_compounds = [c for c in method.compounds if c.signal.upper() == signal_name.upper()]
    used_peaks = set()

    for comp in sig_compounds:
        w_min, w_max = comp.window_range
        candidates = [
            pk
            for pk in peaks
            if id(pk) not in used_peaks
            and w_min <= pk.rt_min <= w_max
            and (pk.is_negative == comp.is_negative_peak)
        ]
        if not candidates:
            continue
        if comp.peak_match.lower() == "largest":
            best = max(candidates, key=lambda p: p.area)
        else:
            # 'Closest' (default in MPZ_method-2.2)
            best = min(candidates, key=lambda p: abs(p.rt_min - comp.exp_rt_min))

        best.compound_name = comp.name
        best.expected_rt = comp.exp_rt_min
        used_peaks.add(id(best))


def _is_integration_enabled_at(t_min: float, timed_events: list) -> bool:
    """Evaluate TimedEvents table to determine if integration is ON at t_min."""
    if not timed_events:
        return True
    # Determine initial state before first IntegrationOn/Off event
    int_events = [
        e for e in timed_events
        if getattr(e, "enabled", True)
        and (getattr(e, "event_type", "") or "").replace(" ", "").replace("_", "").lower() in ("integrationon", "integrationoff")
    ]
    if not int_events:
        return True
    int_events.sort(key=lambda e: e.time_min)
    # If the first integration gate is IntegrationOn (e.g. at 4.0 min on FID1A),
    # then before 4.0 min integration is OFF. If first is IntegrationOff (e.g. 1.0 min on TCD2B),
    # then before 1.0 min it is ON.
    first_type = (getattr(int_events[0], "event_type", "") or "").replace(" ", "").replace("_", "").lower()
    state = (first_type == "integrationoff")
    for ev in int_events:
        if t_min >= ev.time_min:
            ev_type = (getattr(ev, "event_type", "") or "").replace(" ", "").replace("_", "").lower()
            state = (ev_type == "integrationon")
        else:
            break
    return state


def _is_negative_peak_enabled_at(t_min: float, timed_events: list) -> bool:
    """Evaluate TimedEvents table to determine if negative peak mode is ON at t_min."""
    if not timed_events:
        return False
    neg_events = [
        e for e in timed_events
        if getattr(e, "enabled", True)
        and (getattr(e, "event_type", "") or "").replace(" ", "").replace("_", "").lower() in ("negativepeakon", "negativepeakoff")
    ]
    if not neg_events:
        return False
    neg_events.sort(key=lambda e: e.time_min)
    state = False
    for ev in neg_events:
        if t_min >= ev.time_min:
            ev_type = (getattr(ev, "event_type", "") or "").replace(" ", "").replace("_", "").lower()
            state = (ev_type == "negativepeakon")
        else:
            break
    return state


def sync_timed_events_recalculation(
    sig: ChromatogramSignal,
    method: ProcessingMethod,
    peaks: Optional[List[IntegratedPeak]] = None,
) -> List[IntegratedPeak]:
    """
    Synchronously recalculate integration and peak metrics when timed events
    are added, edited, or removed in the processing method.
    """
    if peaks is None:
        return auto_integrate_signal(sig, method)
    cfg = method.signals.get(sig.name) if method and method.signals else None
    timed_events = cfg.timed_events if cfg else []

    # Filter out any non-manual peaks whose apex falls within an IntegrationOff window
    filtered: List[IntegratedPeak] = []
    for pk in peaks:
        if pk.is_manual or _is_integration_enabled_at(pk.rt_min, timed_events):
            filtered.append(pk)

    return recalculate_signal_peaks(sig, filtered, method)


def auto_integrate_signal(
    sig: ChromatogramSignal,
    method: ProcessingMethod,
) -> List[IntegratedPeak]:
    """
    Pure-Python ChemStation 12-Tone style integrator supporting:
    - Timed Integration ON/OFF gates and BaselineNow resets
    - Method-level ManualMethodEvents (including negative H2 peak on TCD2B)
    - Co-eluting peak valley drop splitting (unknown #1 / CH4 / C2H4 / C2H6, C3H6 / C3H8)
    - Rider peak tangent skimming on large solvent/reactant tails (e.g. C4H10 & unknown #2 on CH3OH)
    """
    cfg = method.signals.get(sig.name) if method and method.signals else None
    if cfg is None:
        cfg = SignalMethodConfig(signal_name=sig.name)
    if not sig.time_min or not sig.values:
        return []
    n = min(len(sig.time_min), len(sig.values))
    if n < 20:
        return []
    t = sig.time_min[:n]
    y = [
        val if isinstance(val, (int, float)) and not math.isnan(val) and not math.isinf(val) else 0.0
        for val in sig.values[:n]
    ]

    dt_min = sig.dt_sec / 60.0 if sig.dt_sec > 0 else (t[-1] - t[0]) / max(1, n - 1)
    # Smooth signal slightly for derivative / apex / valley finding
    half_w = max(2, int(round(0.008 / max(dt_min, 1e-5))))
    y_smooth = [0.0] * n
    for i in range(n):
        lo = max(0, i - half_w)
        hi = min(n - 1, i + half_w)
        # Fast local average
        y_smooth[i] = sum(y[lo : hi + 1]) / (hi - lo + 1)

    peaks: List[IntegratedPeak] = []
    covered_intervals: List[Tuple[float, float]] = []

    # 1. Apply any enabled ManualMethodEvents first (e.g. H2 negative peak 8.102-8.726 min on TCD2B)
    for m_ev in cfg.manual_method_events:
        if not m_ev.enabled or m_ev.end_min <= m_ev.begin_min:
            continue
        bs_y = sig.value_at_time(m_ev.begin_min)
        be_y = sig.value_at_time(m_ev.end_min)
        pk = IntegratedPeak(
            peak_id=str(uuid.uuid4())[:8],
            signal_name=sig.name,
            signal_description=sig.description,
            rt_min=0.5 * (m_ev.begin_min + m_ev.end_min),
            begin_min=m_ev.begin_min,
            end_min=m_ev.end_min,
            baseline_start_y=bs_y,
            baseline_end_y=be_y,
            area=0.0,
            height=0.0,
            baseline_code="MM N" if m_ev.is_negative else "MM m",
            is_negative=m_ev.is_negative,
            is_manual=True,
        )
        recalculate_peak_metrics(sig, pk)
        if pk.area > 0.05:
            peaks.append(pk)
            covered_intervals.append((m_ev.begin_min, m_ev.end_min))

    # 2. Find local maxima across active Integration ON windows
    # Collect BaselineNow timestamps
    baseline_resets = sorted(
        e.time_min
        for e in cfg.timed_events
        if getattr(e, "enabled", True)
        and (getattr(e, "event_type", "") or "").replace(" ", "").replace("_", "").lower() == "baselinenow"
    )

    # Scan for local maxima in y_smooth
    step_pts = max(3, int(round(cfg.peak_width * 0.35 / max(dt_min, 1e-5))))
    cand_indices: List[int] = []
    for i in range(step_pts, n - step_pts):
        ti = t[i]
        if not _is_integration_enabled_at(ti, cfg.timed_events):
            continue
        if any(a - 0.01 <= ti <= b + 0.01 for a, b in covered_intervals):
            continue
        yi = y_smooth[i]
        # Must be local maximum in +/- step_pts window
        if yi >= max(y_smooth[i - step_pts : i + step_pts + 1]) and (
            yi > y_smooth[i - step_pts] or yi > y_smooth[i + step_pts]
        ):
            if not cand_indices or (i - cand_indices[-1]) >= step_pts:
                cand_indices.append(i)
            elif yi > y_smooth[cand_indices[-1]]:
                cand_indices[-1] = i

    # For each candidate maximum, find left and right valleys/baseline feet
    raw_Touch_groups: List[Tuple[int, int, int]] = []  # (i_left, i_apex, i_right)
    max_search_pts = int(round(0.95 / max(dt_min, 1e-5)))

    for idx_pos, i_apex in enumerate(cand_indices):
        t_apex = t[i_apex]
        # Walk left to valley or flat baseline
        i_left = i_apex
        prev_apex = cand_indices[idx_pos - 1] if idx_pos > 0 else 0
        limit_left = max(0, i_apex - max_search_pts, prev_apex)
        # Also stop at any BaselineNow reset just to the left
        for br in baseline_resets:
            if br < t_apex:
                limit_left = max(limit_left, sig.index_at_time(br))

        min_y_left = y_smooth[i_apex]
        for j in range(i_apex - 1, limit_left - 1, -1):
            if y_smooth[j] <= min_y_left:
                min_y_left = y_smooth[j]
                i_left = j
            elif y_smooth[j] > min_y_left + max(0.015, 0.02 * (y_smooth[i_apex] - min_y_left)):
                # Started rising toward previous peak
                break
            # Check if slope is flat near baseline
            if (i_apex - j) > step_pts and abs(y_smooth[j] - y_smooth[max(0, j - step_pts)]) < 0.002 * cfg.slope_sensitivity:
                i_left = j
                break

        # Walk right to valley or flat baseline
        i_right = i_apex
        next_apex = cand_indices[idx_pos + 1] if idx_pos + 1 < len(cand_indices) else n - 1
        limit_right = min(n - 1, i_apex + int(round(1.7 / max(dt_min, 1e-5))), next_apex)
        for br in baseline_resets:
            if br > t_apex:
                limit_right = min(limit_right, sig.index_at_time(br))
                break

        min_y_right = y_smooth[i_apex]
        for j in range(i_apex + 1, limit_right + 1):
            if y_smooth[j] <= min_y_right:
                min_y_right = y_smooth[j]
                i_right = j
            elif y_smooth[j] > min_y_right + max(0.015, 0.02 * (y_smooth[i_apex] - min_y_right)):
                break
            if (j - i_apex) > step_pts * 2 and abs(y_smooth[min(n - 1, j + step_pts)] - y_smooth[j]) < 0.0015 * cfg.slope_sensitivity:
                i_right = j
                break

        if i_right - i_left < 3:
            continue

        # Check prominence relative to local chord (i_left -> i_right)
        t_l, t_r = t[i_left], t[i_right]
        y_l, y_r = y[i_left], y[i_right]
        chord_y = y_l + (y_r - y_l) * ((t_apex - t_l) / max(t_r - t_l, 1e-6))
        prominence = y[i_apex] - chord_y

        # Check if this peak falls inside an expected compound window
        in_compound_win = any(
            c.signal.upper() == sig.name.upper() and c.window_range[0] <= t_apex <= c.window_range[1]
            for c in method.compounds
        )
        min_prom = 0.08 if in_compound_win else max(0.18, cfg.height_reject * 0.2)
        if prominence >= min_prom:
            raw_Touch_groups.append((i_left, i_apex, i_right))

    # 3. Group touching peaks that share baseline valleys (e.g., 4.46-5.07 min or 5.53-5.83 min)
    # and identify rider peaks on the tail of a dominant peak (like CH3OH at 6.87 min)
    dominant_peaks: List[Tuple[int, int, int, float]] = []  # (i_l, i_apex, i_r, height)
    for i_l, i_a, i_r in raw_Touch_groups:
        h_est = y[i_a] - min(y[i_l], y[i_r])
        if h_est > 100.0:
            # Extend right baseline end of huge peak (like CH3OH) to where baseline recovers (~8.56 min)
            ext_limit = min(n - 1, i_a + int(round(1.8 / max(dt_min, 1e-5))))
            base_target = y[i_l] + 0.08
            best_r = i_r
            for j in range(i_a + step_pts, ext_limit):
                best_r = j
                if y_smooth[j] <= base_target:
                    break
            dominant_peaks.append((i_l, i_a, best_r, h_est))

    # Build final peak objects
    i = 0
    while i < len(raw_Touch_groups):
        i_l, i_a, i_r = raw_Touch_groups[i]
        t_a = t[i_a]

        # Check if this peak is one of the dominant peaks
        dom_match = [d for d in dominant_peaks if d[1] == i_a]
        if dom_match:
            d_l, d_a, d_r, _ = dom_match[0]
            pk = IntegratedPeak(
                peak_id=str(uuid.uuid4())[:8],
                signal_name=sig.name,
                signal_description=sig.description,
                rt_min=t[d_a],
                begin_min=t[d_l],
                end_min=t[d_r],
                baseline_start_y=y[d_l],
                baseline_end_y=y[d_r],
                area=0.0,
                height=0.0,
                baseline_code="BV R",
            )
            recalculate_peak_metrics(sig, pk)
            peaks.append(pk)
            i += 1
            continue

        # Check if this peak is a rider on the tail of a dominant peak
        enclosing_dom = [
            d for d in dominant_peaks if d[1] < i_a and i_r <= d[2] + 20
        ]
        if enclosing_dom:
            # Tangent skim on the tail of the dominant peak (local chord from i_l to i_r)
            pk = IntegratedPeak(
                peak_id=str(uuid.uuid4())[:8],
                signal_name=sig.name,
                signal_description=sig.description,
                rt_min=t_a,
                begin_min=t[i_l],
                end_min=t[i_r],
                baseline_start_y=y[i_l],
                baseline_end_y=y[i_r],
                area=0.0,
                height=0.0,
                baseline_code="MM t",
                is_tangent_skim=True,
            )
            recalculate_peak_metrics(sig, pk)
            if pk.area >= 0.25:
                peaks.append(pk)
            i += 1
            continue

        # Otherwise, check if consecutive peaks touch / co-elute to share a common group baseline
        group = [(i_l, i_a, i_r)]
        j = i + 1
        while j < len(raw_Touch_groups):
            nl, na, nr = raw_Touch_groups[j]
            # Stop if next peak is dominant or far away
            if any(d[1] == na for d in dominant_peaks):
                break
            if (t[nl] - t[group[-1][2]]) <= 0.035:
                # Snap shared valley
                shared_v = int(round(0.5 * (group[-1][2] + nl)))
                prev_l, prev_a, _ = group[-1]
                group[-1] = (prev_l, prev_a, shared_v)
                group.append((shared_v, na, nr))
                j += 1
            else:
                break

        g_start_idx = group[0][0]
        g_end_idx = group[-1][2]
        g_t0, g_t1 = t[g_start_idx], t[g_end_idx]
        g_y0, g_y1 = y[g_start_idx], y[g_end_idx]
        g_span = max(g_t1 - g_t0, 1e-9)

        for k_idx, ( p_l, p_a, p_r ) in enumerate(group):
            tb = t[p_l]
            te = t[p_r]
            yb = g_y0 + (g_y1 - g_y0) * ((tb - g_t0) / g_span)
            ye = g_y0 + (g_y1 - g_y0) * ((te - g_t0) / g_span)
            if len(group) == 1:
                bcode = "BB"
            elif k_idx == 0:
                bcode = "BV"
            elif k_idx == len(group) - 1:
                bcode = "VB"
            else:
                bcode = "VV"

            pk = IntegratedPeak(
                peak_id=str(uuid.uuid4())[:8],
                signal_name=sig.name,
                signal_description=sig.description,
                rt_min=t[p_a],
                begin_min=tb,
                end_min=te,
                baseline_start_y=yb,
                baseline_end_y=ye,
                area=0.0,
                height=0.0,
                baseline_code=bcode,
            )
            recalculate_peak_metrics(sig, pk)
            in_comp = any(
                c.signal.upper() == sig.name.upper() and c.window_range[0] <= pk.rt_min <= c.window_range[1]
                for c in method.compounds
            )
            if in_comp or (pk.area >= cfg.area_reject and pk.height >= cfg.height_reject):
                peaks.append(pk)

        i = j

    return recalculate_signal_peaks(sig, peaks, method)


def save_manual_overrides(inj: InjectionData) -> Optional[str]:
    """Save current peaks for all signals of an injection to a sidecar JSON file in the .D folder."""
    try:
        out_path = os.path.join(inj.folder_path, MANUAL_OVERRIDES_FILENAME)
        payload = {
            "folder_name": inj.folder_name,
            "sample_name": inj.sample_name,
            "integration_source": inj.integration_source,
            "signals": {
                sname: [asdict(pk) for pk in pk_list]
                for sname, pk_list in inj.peaks_by_signal.items()
            },
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return out_path
    except OSError as exc:
        print(f"Warning: could not write manual overrides to {inj.folder_path}: {exc}")
        return None


def load_manual_overrides(inj: InjectionData) -> bool:
    """Load saved manual peak overrides from the .D folder if present."""
    in_path = os.path.join(inj.folder_path, MANUAL_OVERRIDES_FILENAME)
    if not os.path.exists(in_path):
        return False
    try:
        with open(in_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sigs_data = data.get("signals", {})
        loaded: Dict[str, List[IntegratedPeak]] = {}
        for sname, pk_dicts in sigs_data.items():
            if sname in inj.signals:
                loaded[sname] = [IntegratedPeak(**d) for d in pk_dicts if isinstance(d, dict)]
        if loaded:
            inj.peaks_by_signal = loaded
            inj.integration_source = "manual"
            return True
    except Exception:
        pass
    return False


def process_injection(
    inj: InjectionData,
    method: ProcessingMethod,
    prefer_rx: bool = True,
    prefer_manual: bool = True,
) -> InjectionData:
    """
    Process an InjectionData instance using:
    1. Saved manual overrides (`openlab_sub_manual.json`) if `prefer_manual=True` and present
    2. OpenLab `.rx` processed results (`Base/InjectionACAML`) if `prefer_rx=True` and present
    3. Pure-Python ChemStation 12-Tone automatic integrator (`auto_integrate_signal`)
    """
    if not inj.signals:
        inj.peaks_by_signal = {}
        inj.integration_source = "auto"
        return inj

    if prefer_manual and load_manual_overrides(inj):
        for sname, sig in inj.signals.items():
            if sname in inj.peaks_by_signal:
                recalculate_signal_peaks(sig, inj.peaks_by_signal[sname], method)
        return inj

    if prefer_rx and inj.rx_path and os.path.exists(inj.rx_path):
        try:
            rx_peaks = read_rx_peaks(inj.rx_path, inj.signals)
            if any(len(v) > 0 for v in rx_peaks.values()):
                for sname, sig in inj.signals.items():
                    pks = rx_peaks.get(sname, [])
                    total_area = sum(p.area for p in pks)
                    total_height = sum(p.height for p in pks)
                    for p in pks:
                        if p.area_pct == 0.0 and total_area > 0:
                            p.area_pct = p.area / total_area * 100.0
                        if p.height_pct == 0.0 and total_height > 0:
                            p.height_pct = p.height / total_height * 100.0
                    identify_peaks_for_signal(sname, pks, method)
                    inj.peaks_by_signal[sname] = pks
                inj.integration_source = "rx"
                return inj
        except Exception as exc:
            print(f"Warning: could not read .rx ground truth for {inj.folder_name}: {exc}")

    # Fallback / pure automatic integration
    inj.peaks_by_signal = {}
    for sname, sig in inj.signals.items():
        inj.peaks_by_signal[sname] = auto_integrate_signal(sig, method)
    inj.integration_source = "auto"
    return inj


# ---------------------------------------------------------------------------
# Interactive Manual Integration Helpers (used by UI tools)
# ---------------------------------------------------------------------------

def update_peak_anchors(
    *args,
    **kwargs,
) -> List[IntegratedPeak]:
    """
    Update baseline start/end anchors for a peak and recalculate all metrics.
    When an anchor on a shared split drop line is moved, update both adjacent
    peaks simultaneously to prevent baseline decoupling (Feature F04).

    Supported signatures:
      1) (sig, peaks, peak_id, new_begin_min, new_bs_y, new_end_min, new_be_y, method=None)
      2) (signal, peak, new_left, new_right, signal_all_peaks=None, method=None)
    """
    if len(args) >= 2 and isinstance(args[1], list):
        sig: ChromatogramSignal = args[0]
        all_peaks: List[IntegratedPeak] = args[1]
        if len(args) > 2 and isinstance(args[2], IntegratedPeak):
            target_pk = args[2]
            peak_id = target_pk.peak_id
        else:
            peak_id: str = args[2] if len(args) > 2 else kwargs.get("peak_id")
            target_pk = next((p for p in all_peaks if str(p.peak_id) == str(peak_id)), None)
        new_begin_min: float = args[3] if len(args) > 3 else kwargs.get("new_begin_min", 0.0)
        new_bs_y: float = args[4] if len(args) > 4 else kwargs.get("new_bs_y", 0.0)
        new_end_min: float = args[5] if len(args) > 5 else kwargs.get("new_end_min", 0.0)
        new_be_y: float = args[6] if len(args) > 6 else kwargs.get("new_be_y", 0.0)
        method: Optional[ProcessingMethod] = args[7] if len(args) > 7 else kwargs.get("method")
    elif len(args) >= 2 and isinstance(args[1], IntegratedPeak):
        sig = args[0]
        target_pk = args[1]
        new_left: Tuple[float, float] = args[2]
        new_right: Tuple[float, float] = args[3]
        new_begin_min, new_bs_y = new_left
        new_end_min, new_be_y = new_right
        all_peaks = args[4] if len(args) > 4 else kwargs.get("signal_all_peaks")
        if all_peaks is None:
            all_peaks = [target_pk]
        method = args[5] if len(args) > 5 else kwargs.get("method")
    else:
        sig = kwargs.get("sig") or kwargs.get("signal")
        target_pk = kwargs.get("peak") or kwargs.get("target_pk")
        all_peaks = kwargs.get("peaks") or kwargs.get("signal_all_peaks") or kwargs.get("all_peaks")
        peak_id = kwargs.get("peak_id")
        if target_pk is None and peak_id is not None and all_peaks:
            target_pk = next((p for p in all_peaks if str(p.peak_id) == str(peak_id)), None)
        if "new_left" in kwargs and kwargs["new_left"] is not None:
            new_begin_min, new_bs_y = kwargs["new_left"]
        else:
            new_begin_min = kwargs.get("new_begin_min", 0.0)
            new_bs_y = kwargs.get("new_bs_y", 0.0)
        if "new_right" in kwargs and kwargs["new_right"] is not None:
            new_end_min, new_be_y = kwargs["new_right"]
        else:
            new_end_min = kwargs.get("new_end_min", 0.0)
            new_be_y = kwargs.get("new_be_y", 0.0)
        method = kwargs.get("method")
        if all_peaks is None and target_pk is not None:
            all_peaks = [target_pk]

    if not sig or not all_peaks or target_pk is None:
        return all_peaks if all_peaks is not None else []

    # Preserve old boundary anchors to detect shared split drop lines
    old_begin = target_pk.begin_min
    old_bs_y = target_pk.baseline_start_y
    old_end = target_pk.end_min
    old_be_y = target_pk.baseline_end_y

    t_min_0 = sig.time_min[0] if sig.time_min else 0.0
    t_max_0 = sig.time_min[-1] if sig.time_min else 40.0

    if not isinstance(new_begin_min, (int, float)) or math.isnan(new_begin_min) or math.isinf(new_begin_min):
        new_begin_min = old_begin
    if not isinstance(new_end_min, (int, float)) or math.isnan(new_end_min) or math.isinf(new_end_min):
        new_end_min = old_end

    clamped_begin = max(t_min_0, min(t_max_0, new_begin_min))
    clamped_end = max(t_min_0, min(t_max_0, new_end_min))

    if clamped_end < clamped_begin:
        clamped_begin, clamped_end = clamped_end, clamped_begin
        new_bs_y, new_be_y = new_be_y, new_bs_y

    begin_moved = (abs(clamped_begin - old_begin) > 1e-6 or abs(new_bs_y - old_bs_y) > 1e-6)
    end_moved = (abs(clamped_end - old_end) > 1e-6 or abs(new_be_y - old_be_y) > 1e-6)

    target_pk.begin_min = clamped_begin
    target_pk.end_min = clamped_end
    target_pk.baseline_start_y = new_bs_y
    target_pk.baseline_end_y = new_be_y
    target_pk.is_manual = True
    if not target_pk.baseline_code.startswith("M"):
        target_pk.baseline_code = "MM N" if target_pk.is_negative else ("MM t" if target_pk.is_tangent_skim else "MM m")

    # Synchronize shared-anchor split drop lines with adjacent peaks
    for other in all_peaks:
        if other is target_pk:
            continue
        # If target's left anchor moved and other's right anchor was shared
        if begin_moved and abs(other.end_min - old_begin) < 1e-4:
            other.end_min = clamped_begin
            other.baseline_end_y = new_bs_y
            other.is_manual = True
            if not other.baseline_code.startswith("M"):
                other.baseline_code = "MM N" if other.is_negative else ("MM t" if other.is_tangent_skim else "MM m")
        # If target's right anchor moved and other's left anchor was shared
        if end_moved and abs(other.begin_min - old_end) < 1e-4:
            other.begin_min = clamped_end
            other.baseline_start_y = new_be_y
            other.is_manual = True
            if not other.baseline_code.startswith("M"):
                other.baseline_code = "MM N" if other.is_negative else ("MM t" if other.is_tangent_skim else "MM m")

    return recalculate_signal_peaks(sig, all_peaks, method)


def add_manual_peak(
    sig: ChromatogramSignal,
    peaks: List[IntegratedPeak],
    t1: float,
    y1: float,
    t2: float,
    y2: float,
    method: Optional[ProcessingMethod] = None,
    snap_to_curve: bool = True,
) -> Tuple[List[IntegratedPeak], Optional[IntegratedPeak]]:
    """
    Draw a new manual peak between (t1, y1) and (t2, y2).
    Automatically detects whether the signal between t1 and t2 deflects above or below
    the drawn baseline (so drawing across H2 on TCD2B automatically integrates the negative peak!).
    """
    if not sig.time_min or not sig.values:
        return peaks, None

    if any(not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) for v in (t1, y1, t2, y2)):
        return peaks, None

    if t2 < t1:
        t1, t2 = t2, t1
        y1, y2 = y2, y1
    if (t2 - t1) < 0.005:
        return peaks, None

    if snap_to_curve:
        y1 = sig.value_at_time(t1)
        y2 = sig.value_at_time(t2)

    # Remove any existing non-parent peaks whose apex lies strictly inside [t1, t2]
    # unless the new peak is a small rider peak inside a huge parent peak
    new_span = t2 - t1
    filtered: List[IntegratedPeak] = []
    is_rider = False
    for pk in peaks:
        pk_span = pk.end_min - pk.begin_min
        if pk.begin_min <= t1 and t2 <= pk.end_min and pk_span > 1.8 * new_span:
            # Drawn peak is a rider inside `pk`
            is_rider = True
            filtered.append(pk)
        elif t1 <= pk.rt_min <= t2 and pk_span <= 1.5 * new_span:
            # Replace existing peak in this window
            continue
        else:
            filtered.append(pk)

    # Auto-detect positive vs negative deflection relative to baseline
    i1 = sig.index_at_time(t1)
    i2 = sig.index_at_time(t2)
    pos_sum = 0.0
    neg_sum = 0.0
    for idx in range(i1, i2 + 1):
        ti = sig.time_min[idx]
        yi = sig.values[idx]
        if not isinstance(yi, (int, float)) or math.isnan(yi) or math.isinf(yi):
            yi = 0.0
        by = y1 + (y2 - y1) * ((ti - t1) / new_span)
        diff = yi - by
        if diff >= 0:
            pos_sum += diff
        else:
            neg_sum += -diff

    is_neg = (neg_sum > pos_sum * 1.2)
    bcode = "MM N" if is_neg else ("MM t" if is_rider else "MM m")

    new_pk = IntegratedPeak(
        peak_id=str(uuid.uuid4())[:8],
        signal_name=sig.name,
        signal_description=sig.description,
        rt_min=0.5 * (t1 + t2),
        begin_min=t1,
        end_min=t2,
        baseline_start_y=y1,
        baseline_end_y=y2,
        area=0.0,
        height=0.0,
        baseline_code=bcode,
        is_negative=is_neg,
        is_tangent_skim=is_rider,
        is_manual=True,
    )
    filtered.append(new_pk)
    recalculate_signal_peaks(sig, filtered, method)
    return filtered, new_pk


def split_peak_at(
    sig: ChromatogramSignal,
    peaks: List[IntegratedPeak],
    t_split: float,
    method: Optional[ProcessingMethod] = None,
) -> List[IntegratedPeak]:
    """
    Split an existing peak at retention time `t_split` with a vertical drop line
    to the shared baseline.
    """
    if not sig.time_min or not sig.values:
        return peaks

    if not isinstance(t_split, (int, float)) or math.isnan(t_split) or math.isinf(t_split):
        return peaks

    target: Optional[IntegratedPeak] = None
    # Prefer smaller peak if nested
    candidates = [pk for pk in peaks if pk.begin_min + 0.005 < t_split < pk.end_min - 0.005]
    if not candidates:
        return peaks
    target = min(candidates, key=lambda p: p.end_min - p.begin_min)

    y_base_split = target.baseline_y_at(t_split)

    left_pk = IntegratedPeak(
        peak_id=str(uuid.uuid4())[:8],
        signal_name=sig.name,
        signal_description=sig.description,
        rt_min=0.5 * (target.begin_min + t_split),
        begin_min=target.begin_min,
        end_min=t_split,
        baseline_start_y=target.baseline_start_y,
        baseline_end_y=y_base_split,
        area=0.0,
        height=0.0,
        baseline_code="MM m",
        is_negative=target.is_negative,
        is_tangent_skim=target.is_tangent_skim,
        is_manual=True,
    )
    right_pk = IntegratedPeak(
        peak_id=str(uuid.uuid4())[:8],
        signal_name=sig.name,
        signal_description=sig.description,
        rt_min=0.5 * (t_split + target.end_min),
        begin_min=t_split,
        end_min=target.end_min,
        baseline_start_y=y_base_split,
        baseline_end_y=target.baseline_end_y,
        area=0.0,
        height=0.0,
        baseline_code="MM m",
        is_negative=target.is_negative,
        is_tangent_skim=target.is_tangent_skim,
        is_manual=True,
    )

    updated = [pk for pk in peaks if pk is not target] + [left_pk, right_pk]
    return recalculate_signal_peaks(sig, updated, method)


def toggle_peak_negative(
    sig: ChromatogramSignal,
    peaks: List[IntegratedPeak],
    peak_id: str,
    method: Optional[ProcessingMethod] = None,
) -> List[IntegratedPeak]:
    """Invert a peak between positive and negative integration mode."""
    for pk in peaks:
        if pk.peak_id == peak_id:
            pk.is_negative = not pk.is_negative
            pk.baseline_code = "MM N" if pk.is_negative else "MM m"
            pk.is_manual = True
            break
    return recalculate_signal_peaks(sig, peaks, method)


def delete_peak_by_id(
    sig: ChromatogramSignal,
    peaks: List[IntegratedPeak],
    peak_id: str,
    method: Optional[ProcessingMethod] = None,
) -> List[IntegratedPeak]:
    """Delete a peak by ID and update percentages & compound assignments."""
    updated = [pk for pk in peaks if pk.peak_id != peak_id]
    return recalculate_signal_peaks(sig, updated, method)
