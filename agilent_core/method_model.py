"""
Processing Method model and parser for Agilent OpenLab .pmx archives
and human-readable .json method files.
"""

import html
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class TimedEvent:
    """Represents a timed integration event on a signal."""
    time_min: float
    event_type: str              # 'IntegrationOn', 'IntegrationOff', 'BaselineNow', 'NegativePeakOn', 'NegativePeakOff'
    value: str = ""
    enabled: bool = True


@dataclass
class ManualMethodEvent:
    """Represents a method-level manual baseline integration window (from .pmx or user)."""
    begin_min: float
    end_min: float
    baseline_start_y: Optional[float] = None
    baseline_end_y: Optional[float] = None
    is_negative: bool = False
    drop_lines: List[float] = field(default_factory=list)
    enabled: bool = True


@dataclass
class SignalMethodConfig:
    """Integration parameters and timed events for a single detector channel."""
    signal_name: str             # 'FID1A' or 'TCD2B'
    slope_sensitivity: float = 1.0
    peak_width: float = 0.02
    area_reject: float = 1.0
    height_reject: float = 1.7
    shoulders_mode: str = "OFF"
    area_pct_reject: float = 0.0
    timed_events: List[TimedEvent] = field(default_factory=list)
    manual_method_events: List[ManualMethodEvent] = field(default_factory=list)


@dataclass
class CompoundDef:
    """Represents a row in the Method Compound Identification Table."""
    index: int
    name: str
    signal: str                  # 'FID1A' or 'TCD2B'
    exp_rt_min: float            # Expected RT (min)
    abs_window_min: float = 0.0  # Absolute RT window (min)
    rel_window_pct: float = 1.0  # Relative RT window (%)
    rt_update: str = "Never"
    rt_update_factor_pct: float = 50.0
    peak_match: str = "Closest"
    is_negative_peak: bool = False  # e.g., True for H2 on TCD2B
    # Calibration parameters (R5):
    response_factor: float = 1.0     # Response factor / calibration multiplier
    calib_curve: str = "Linear"      # 'Linear', 'PointToPoint', 'Quadratic'
    amount_unit: str = "%"           # Concentration unit, e.g. '%', 'ppm', 'mmol/g'
    calib_level: int = 1             # Calibration level

    @property
    def half_window_min(self) -> float:
        """
        Effective half-window in minutes matching OpenLab CDS v2.7:
        HalfWindow = AbsWindow + (RelWindow% / 100.0) * ExpRT
        """
        return self.abs_window_min + (self.rel_window_pct / 100.0) * self.exp_rt_min

    @property
    def window_range(self) -> Tuple[float, float]:
        """Return (min_rt, max_rt) identification window."""
        hw = self.half_window_min
        return (self.exp_rt_min - hw, self.exp_rt_min + hw)


@dataclass
class ZoomPresetDef:
    """Named zoom preset embedded within a processing method."""
    name: str
    time_min: float
    time_max: float
    y_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "time_min": self.time_min,
            "time_max": self.time_max,
            "y_ranges": {k: list(v) for k, v in self.y_ranges.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ZoomPresetDef":
        y_r = {}
        for k, v in data.get("y_ranges", {}).items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                y_r[k] = (float(v[0]), float(v[1]))
        return cls(
            name=str(data.get("name", "Custom Preset")),
            time_min=float(data.get("time_min", 0.0)),
            time_max=float(data.get("time_max", 40.0)),
            y_ranges=y_r,
        )


@dataclass
class ProcessingMethod:
    """Complete processing method (signals + compound table + custom zoom presets)."""
    name: str = "MPZ_method-2.2"
    source_path: str = ""
    signals: Dict[str, SignalMethodConfig] = field(default_factory=dict)
    compounds: List[CompoundDef] = field(default_factory=list)
    custom_zoom_presets: List[ZoomPresetDef] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["custom_zoom_presets"] = [p.to_dict() for p in self.custom_zoom_presets]
        return d

    def save_json(self, file_path: str) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        self.source_path = file_path

    @classmethod
    def load_json(cls, file_path: str) -> "ProcessingMethod":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise ValueError(f"Could not parse method JSON from '{file_path}': {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"Method JSON in '{file_path}' must be an object at top level.")

        signals: Dict[str, SignalMethodConfig] = {}
        for sname, sdict in data.get("signals", {}).items():
            if not isinstance(sdict, dict):
                continue
            te_list: List[TimedEvent] = []
            for te in sdict.get("timed_events", []):
                if not isinstance(te, dict):
                    continue
                try:
                    te_list.append(TimedEvent(
                        time_min=float(te.get("time_min", 0.0)),
                        event_type=str(te.get("event_type", "IntegrationOn")).strip(),
                        value=str(te.get("value", "")),
                        enabled=bool(te.get("enabled", True)),
                    ))
                except Exception:
                    continue

            me_list: List[ManualMethodEvent] = []
            for me in sdict.get("manual_method_events", []):
                if not isinstance(me, dict):
                    continue
                try:
                    bs_y = float(me["baseline_start_y"]) if me.get("baseline_start_y") is not None else None
                    be_y = float(me["baseline_end_y"]) if me.get("baseline_end_y") is not None else None
                    dl = [float(x) for x in me.get("drop_lines", []) if isinstance(x, (int, float))]
                    me_list.append(ManualMethodEvent(
                        begin_min=float(me.get("begin_min", 0.0)),
                        end_min=float(me.get("end_min", 0.0)),
                        baseline_start_y=bs_y,
                        baseline_end_y=be_y,
                        is_negative=bool(me.get("is_negative", False)),
                        drop_lines=dl,
                        enabled=bool(me.get("enabled", True)),
                    ))
                except Exception:
                    continue

            signals[sname] = SignalMethodConfig(
                signal_name=str(sdict.get("signal_name", sname)),
                slope_sensitivity=float(sdict.get("slope_sensitivity", 1.0)),
                peak_width=float(sdict.get("peak_width", 0.02)),
                area_reject=float(sdict.get("area_reject", 1.0)),
                height_reject=float(sdict.get("height_reject", 1.7)),
                shoulders_mode=str(sdict.get("shoulders_mode", "OFF")),
                area_pct_reject=float(sdict.get("area_pct_reject", 0.0)),
                timed_events=te_list,
                manual_method_events=me_list,
            )

        compounds: List[CompoundDef] = []
        for c in data.get("compounds", []):
            if not isinstance(c, dict):
                continue
            try:
                compounds.append(CompoundDef(
                    index=int(c.get("index", len(compounds) + 1)),
                    name=str(c.get("name", f"Compound_{len(compounds) + 1}")),
                    signal=str(c.get("signal", "FID1A")),
                    exp_rt_min=float(c.get("exp_rt_min", 0.0)),
                    abs_window_min=float(c.get("abs_window_min", 0.0)),
                    rel_window_pct=float(c.get("rel_window_pct", 1.0)),
                    rt_update=str(c.get("rt_update", "Never")),
                    rt_update_factor_pct=float(c.get("rt_update_factor_pct", 50.0)),
                    peak_match=str(c.get("peak_match", "Closest")),
                    is_negative_peak=bool(c.get("is_negative_peak", False)),
                    response_factor=float(c.get("response_factor", 1.0)),
                    calib_curve=str(c.get("calib_curve", "Linear")),
                    amount_unit=str(c.get("amount_unit", "%")),
                    calib_level=int(c.get("calib_level", 1)),
                ))
            except Exception:
                continue

        custom_zoom_presets: List[ZoomPresetDef] = []
        for p in data.get("custom_zoom_presets", []):
            if not isinstance(p, dict):
                continue
            try:
                custom_zoom_presets.append(ZoomPresetDef.from_dict(p))
            except Exception:
                continue

        if not signals:
            signals["FID1A"] = SignalMethodConfig(signal_name="FID1A")
            signals["TCD2B"] = SignalMethodConfig(signal_name="TCD2B")

        return cls(
            name=str(data.get("name", os.path.splitext(os.path.basename(file_path))[0])),
            source_path=file_path,
            signals=signals,
            compounds=compounds,
            custom_zoom_presets=custom_zoom_presets,
        )


def build_default_mpz_method() -> ProcessingMethod:
    """
    Build the exact MPZ_method-2.2 processing method from the user's OpenLab v2.7
    screenshots and .pmx ground truth.
    """
    fid1a = SignalMethodConfig(
        signal_name="FID1A",
        slope_sensitivity=1.0,
        peak_width=0.02,
        area_reject=1.0,
        height_reject=1.7,
        shoulders_mode="OFF",
        area_pct_reject=0.0,
        timed_events=[
            TimedEvent(time_min=4.000, event_type="IntegrationOn", value="ON", enabled=True),
            TimedEvent(time_min=12.000, event_type="IntegrationOff", value="OFF", enabled=True),
            # Allow CH3CH2CH2OH around 15.38 min to be integrated automatically as well
            TimedEvent(time_min=15.000, event_type="IntegrationOn", value="ON", enabled=True),
            TimedEvent(time_min=16.400, event_type="IntegrationOff", value="OFF", enabled=True),
        ],
        manual_method_events=[],
    )

    tcd2b = SignalMethodConfig(
        signal_name="TCD2B",
        slope_sensitivity=1.0,
        peak_width=0.02,
        area_reject=1.0,
        height_reject=1.7,
        shoulders_mode="OFF",
        area_pct_reject=0.0,
        timed_events=[
            TimedEvent(time_min=0.002, event_type="BaselineNow", value="true", enabled=True),
            TimedEvent(time_min=1.000, event_type="IntegrationOff", value="OFF", enabled=True),
            TimedEvent(time_min=4.900, event_type="IntegrationOn", value="ON", enabled=True),
            TimedEvent(time_min=5.500, event_type="IntegrationOff", value="OFF", enabled=True),
            TimedEvent(time_min=8.000, event_type="IntegrationOn", value="ON", enabled=True),
            TimedEvent(time_min=8.100, event_type="BaselineNow", value="true", enabled=True),
            TimedEvent(time_min=8.700, event_type="BaselineNow", value="true", enabled=True),
            TimedEvent(time_min=9.300, event_type="IntegrationOff", value="OFF", enabled=True),
            TimedEvent(time_min=13.000, event_type="IntegrationOn", value="ON", enabled=True),
            TimedEvent(time_min=14.500, event_type="IntegrationOff", value="OFF", enabled=True),
        ],
        manual_method_events=[
            ManualMethodEvent(
                begin_min=8.102323,
                end_min=8.725645,
                baseline_start_y=None,
                baseline_end_y=None,
                is_negative=True,
                enabled=True,
            ),
            ManualMethodEvent(
                begin_min=13.425745,
                end_min=14.022498,
                baseline_start_y=None,
                baseline_end_y=None,
                is_negative=False,
                enabled=True,
            ),
        ],
    )

    compounds = [
        CompoundDef(1, "unknown #1", "FID1A", 4.546, 0.000, 1.000),
        CompoundDef(2, "CH4", "FID1A", 4.614, 0.000, 1.000),
        CompoundDef(3, "C2H4", "FID1A", 4.821, 0.000, 1.000),
        CompoundDef(4, "C2H6", "FID1A", 4.942, 0.000, 1.000),
        CompoundDef(5, "CO2", "TCD2B", 5.180, 0.100, 1.000),
        CompoundDef(6, "C3H6", "FID1A", 5.620, 0.010, 1.000),
        CompoundDef(7, "C3H8", "FID1A", 5.694, 0.000, 1.000),
        CompoundDef(8, "CH3OCH3", "FID1A", 6.331, 0.000, 1.000),
        CompoundDef(9, "CH3OH", "FID1A", 6.892, 0.000, 1.000),
        CompoundDef(10, "C4H10", "FID1A", 7.917, 0.000, 1.000),
        CompoundDef(11, "unknown #2", "FID1A", 8.375, 0.100, 1.000),
        CompoundDef(12, "H2", "TCD2B", 8.415, 0.225, 1.000, is_negative_peak=True),
        CompoundDef(13, "Argon", "TCD2B", 8.850, 0.225, 1.000),
        CompoundDef(14, "CH3CH2OH", "FID1A", 9.608, 0.500, 1.000),
        CompoundDef(15, "CO", "TCD2B", 13.439, 0.750, 1.000),
        CompoundDef(16, "CH3CH2CH2OH", "FID1A", 15.380, 0.700, 1.000),
    ]

    mpz_zoom_presets = [
        ZoomPresetDef("Reaction (3.5–16.5m)", 3.5, 16.5, {"FID1A": (9.0, 25.0), "TCD2B": (20.0, 320.0)}),
        ZoomPresetDef("C1–C3 + DME (4.4–6.5m)", 4.4, 6.5, {"FID1A": (9.4, 19.0), "TCD2B": (35.0, 220.0)}),
        ZoomPresetDef("MeOH + C4 (6.6–8.6m)", 6.6, 8.6, {"FID1A": (9.5, 16.0), "TCD2B": (20.0, 120.0)}),
        ZoomPresetDef("H2 + Ar (8.0–9.3m)", 8.0, 9.3, {"FID1A": (9.7, 11.0), "TCD2B": (10.0, 160.0)}),
        ZoomPresetDef("CO (13.0–14.3m)", 13.0, 14.3, {"FID1A": (9.8, 12.0), "TCD2B": (30.0, 310.0)}),
    ]

    return ProcessingMethod(
        name="MPZ_method-2.2",
        signals={"FID1A": fid1a, "TCD2B": tcd2b},
        compounds=compounds,
        custom_zoom_presets=mpz_zoom_presets,
    )


def load_pmx_method(pmx_path: str) -> ProcessingMethod:
    """
    Parse an Agilent OpenLab .pmx processing method archive directly.
    Extracts 12-Tone Integrator settings, Timed Events, Method Manual Integration Events,
    and the Expected Compounds Identification table.
    """
    method = build_default_mpz_method()
    method.name = os.path.splitext(os.path.basename(pmx_path))[0]
    method.source_path = pmx_path

    try:
        with zipfile.ZipFile(pmx_path, "r") as zf:
            if "TransformationChains/DefaultChain" not in zf.namelist():
                return method
            raw_bytes = zf.read("TransformationChains/DefaultChain")
    except Exception:
        return method

    try:
        xml_outer = raw_bytes.decode("utf-16")
    except UnicodeDecodeError:
        xml_outer = raw_bytes.decode("utf-8", errors="ignore")

    unescaped = html.unescape(xml_outer)

    # 1. Parse 12-Tone Integrator Container
    m_t12 = re.search(
        r'<TransformationPSets SetpointContainerName="DefaultChain_12ToneIntegrator"[\s\S]*?</TransformationPSets>',
        unescaped,
    )
    if m_t12:
        try:
            t12_root = ET.fromstring(m_t12.group(0))
            for ps in t12_root.findall("ParameterSet"):
                uk = ps.attrib.get("usagekey", "")
                if uk.startswith("12ToneIntegratorSettings") and len(uk) > len("12ToneIntegratorSettings"):
                    sig_name = uk.replace("12ToneIntegratorSettings", "").strip()
                    sig_cfg = SignalMethodConfig(signal_name=sig_name)

                    # Initial events
                    init_param = ps.find('Parameters/Parameter[@id="InitialEventsTable"]/Value')
                    if init_param is not None:
                        for ev_ps in init_param.findall("ParameterSet"):
                            ev_name_el = ev_ps.find(".//IntegrationEvent")
                            val_el = ev_ps.find(".//IntegrationEventValue/Parameter/Value")
                            if ev_name_el is None or val_el is None:
                                continue
                            ev_name = (ev_name_el.text or "").strip()
                            val_txt = (val_el.text or "").strip()
                            if ev_name == "SlopeSensitivity":
                                sig_cfg.slope_sensitivity = float(val_txt)
                            elif ev_name == "PeakWidth":
                                sig_cfg.peak_width = float(val_txt)
                            elif ev_name == "AreaReject":
                                sig_cfg.area_reject = float(val_txt)
                            elif ev_name == "HeightReject":
                                sig_cfg.height_reject = float(val_txt)
                            elif ev_name == "ShouldersMode":
                                sig_cfg.shoulders_mode = val_txt
                            elif ev_name == "AreaPercentReject":
                                sig_cfg.area_pct_reject = float(val_txt)

                    # Timed events
                    timed_param = ps.find('Parameters/Parameter[@id="TimedEventsTable"]/Value')
                    if timed_param is not None:
                        for ev_ps in timed_param.findall("ParameterSet"):
                            ev_name_el = ev_ps.find(".//IntegrationEvent")
                            used_el = ev_ps.find(".//IsUsed")
                            val_el = ev_ps.find(".//IntegrationEventValue/Parameter/Value")
                            tm_el = ev_ps.find('Parameters/Parameter[@id="Time"]/Value')
                            if ev_name_el is None or tm_el is None:
                                continue
                            ev_name = (ev_name_el.text or "").strip()
                            is_used = (used_el.text or "true").strip().lower() == "true" if used_el is not None else True
                            val_txt = (val_el.text or "").strip() if val_el is not None else ""
                            t_val = float(tm_el.text or "0")

                            # Note: In Agilent 12-Tone XML, Integration event value 'false' means IntegratorOff=False (Integration ON)
                            # and 'true' means IntegratorOff=True (Integration OFF)
                            if ev_name == "Integration":
                                mapped_type = "IntegrationOn" if val_txt.lower() == "false" else "IntegrationOff"
                                mapped_val = "ON" if mapped_type == "IntegrationOn" else "OFF"
                            elif ev_name == "BaselineNow":
                                mapped_type = "BaselineNow"
                                mapped_val = "true"
                            else:
                                mapped_type = ev_name
                                mapped_val = val_txt

                            sig_cfg.timed_events.append(
                                TimedEvent(
                                    time_min=t_val,
                                    event_type=mapped_type,
                                    value=mapped_val,
                                    enabled=is_used,
                                )
                            )

                    sig_cfg.timed_events.sort(key=lambda e: e.time_min)
                    # Preserve any manual_method_events already parsed
                    if sig_name in method.signals:
                        sig_cfg.manual_method_events = method.signals[sig_name].manual_method_events
                    method.signals[sig_name] = sig_cfg

                elif uk.startswith("ManualMethodIntegrationSettings") and len(uk) > len("ManualMethodIntegrationSettings"):
                    sig_name = uk.replace("ManualMethodIntegrationSettings", "").strip()
                    manual_events: List[ManualMethodEvent] = []
                    for ev_ps in ps.findall("Parameters/Parameter/Value/ParameterSet"):
                        p_map = {
                            p.attrib.get("id", ""): (p.find("Value").text if p.find("Value") is not None else "")
                            for p in ev_ps.findall("Parameters/Parameter")
                        }
                        used = str(p_map.get("KeyIsUsedParameter", "true")).lower() == "true"
                        b_t = float(p_map.get("KeyBeginTimeParameter") or 0.0)
                        e_t = float(p_map.get("KeyEndTimeParameter") or 0.0)
                        bs_y = float(p_map.get("KeyBaselineStartParameter") or 0.0)
                        be_y = float(p_map.get("KeyBaselineEndParameter") or 0.0)
                        # Check if this corresponds to the H2 negative peak window around 8.1-8.7 min
                        is_neg = (sig_name == "TCD2B" and 8.0 <= b_t <= 8.6)
                        if e_t > b_t:
                            manual_events.append(
                                ManualMethodEvent(
                                    begin_min=b_t,
                                    end_min=e_t,
                                    baseline_start_y=bs_y,
                                    baseline_end_y=be_y,
                                    is_negative=is_neg,
                                    enabled=used,
                                )
                            )
                    if sig_name not in method.signals:
                        method.signals[sig_name] = SignalMethodConfig(signal_name=sig_name)
                    if manual_events:
                        method.signals[sig_name].manual_method_events = manual_events
        except Exception:
            pass

    # 2. Parse Compound Identification Container
    m_cid = re.search(
        r'<TransformationPSets SetpointContainerName="DefaultChain_COMPOUNDIdentification"[\s\S]*?</TransformationPSets>',
        unescaped,
    )
    if m_cid:
        try:
            cid_root = ET.fromstring(m_cid.group(0))
            comp_list_el = cid_root.find(
                './/Parameter[@id="ExpectedCompoundsList"]/Value'
            )
            if comp_list_el is not None:
                parsed_compounds: List[CompoundDef] = []
                for cps in comp_list_el.findall('ParameterSet[@usagekey="CompoundId"]'):
                    p_map = {}
                    for p in cps.findall("Parameters/Parameter"):
                        pid = p.attrib.get("id", "")
                        val_el = p.find("Value")
                        p_map[pid] = (val_el.text or "").strip() if val_el is not None else ""

                    cname = p_map.get("Name", "")
                    exp_rt = float(p_map.get("ExpectedRetentionTime") or 0.0)
                    sig = p_map.get("Signal", "FID1A") or "FID1A"
                    abs_win = float(p_map.get("ExpectedTimeAbsoluteLeft") or 0.0)
                    rel_win = float(p_map.get("ExpectedTimeRelativeLeft") or 1.0)
                    match_mode = p_map.get("IdentificationScore", "Closest") or "Closest"
                    rt_upd = p_map.get("UpdateExpectedRetentionTimeMode", "Never") or "Never"
                    rt_fac = float(p_map.get("UpdateExpectedRetentionTimeWeightingFactor") or 50.0)
                    is_neg = (cname.upper() in ("H2", "HYDROGEN") and "TCD" in sig.upper())

                    parsed_compounds.append(
                        CompoundDef(
                            index=len(parsed_compounds) + 1,
                            name=cname,
                            signal=sig,
                            exp_rt_min=exp_rt,
                            abs_window_min=abs_win,
                            rel_window_pct=rel_win,
                            rt_update=rt_upd,
                            rt_update_factor_pct=rt_fac,
                            peak_match=match_mode,
                            is_negative_peak=is_neg,
                        )
                    )

                if parsed_compounds:
                    # Sort ascending by Expected RT (min) to match OpenLab Compound Table display
                    parsed_compounds.sort(key=lambda c: c.exp_rt_min)
                    for i, c in enumerate(parsed_compounds, start=1):
                        c.index = i
                    method.compounds = parsed_compounds
        except Exception:
            pass

    # Ensure FID1A also includes the 15.0-16.4 min gate if CH3CH2CH2OH is at ~15.38 min
    if "FID1A" in method.signals:
        has_late_compound = any(
            c.signal == "FID1A" and c.exp_rt_min > 12.5 for c in method.compounds
        )
        has_late_gate = any(
            e.time_min > 12.5 and e.event_type == "IntegrationOn"
            for e in method.signals["FID1A"].timed_events
        )
        if has_late_compound and not has_late_gate:
            method.signals["FID1A"].timed_events.extend(
                [
                    TimedEvent(time_min=15.000, event_type="IntegrationOn", value="ON", enabled=True),
                    TimedEvent(time_min=16.400, event_type="IntegrationOff", value="OFF", enabled=True),
                ]
            )

    return method
