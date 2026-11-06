"""
Reader for Agilent .D folders, .ch binary chromatogram files (version 179),
and .rx (InjectionACAML) processed result archives.
"""

import array
import math
import os
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ChromatogramSignal:
    """Represents a single detector signal (e.g., FID1A or TCD2B)."""
    name: str                    # e.g. 'FID1A', 'TCD2B'
    description: str             # e.g. 'FID1 A, Front Signal'
    units: str                   # e.g. 'pA', '25 µV'
    sample_name: str             # e.g. 'MPZHY14_reaction_261015_126'
    acq_date: str                # e.g. '20-Oct-26, 00:40:38'
    time_min: List[float]        # Retention time array in minutes
    values: List[float]          # Signal response array in detector units
    dt_sec: float                # Time step in seconds between consecutive points
    file_path: str = ""

    def index_at_time(self, t_min: float) -> int:
        """Fast O(1) index lookup given uniform sampling with NaN/Inf protection."""
        if not self.time_min or not isinstance(t_min, (int, float)) or math.isnan(t_min) or math.isinf(t_min):
            return 0
        if t_min <= self.time_min[0]:
            return 0
        if t_min >= self.time_min[-1]:
            return len(self.time_min) - 1
        t0 = self.time_min[0]
        dt_min = self.dt_sec / 60.0
        if dt_min <= 0:
            return 0
        idx = int(round((t_min - t0) / dt_min))
        return max(0, min(len(self.time_min) - 1, idx))

    def value_at_time(self, t_min: float) -> float:
        """Linearly interpolated signal value at t_min with NaN/Inf and empty protection."""
        if not self.time_min or not self.values or not isinstance(t_min, (int, float)) or math.isnan(t_min) or math.isinf(t_min):
            return 0.0
        if t_min <= self.time_min[0]:
            return self.values[0]
        if t_min >= self.time_min[-1]:
            return self.values[-1]
        t0 = self.time_min[0]
        dt_min = self.dt_sec / 60.0
        if dt_min <= 0 or len(self.values) == 1:
            return self.values[0]
        pos = (t_min - t0) / dt_min
        if pos <= 0:
            return self.values[0]
        if pos >= len(self.values) - 1:
            return self.values[-1]
        idx = int(pos)
        frac = pos - idx
        return self.values[idx] * (1.0 - frac) + self.values[idx + 1] * frac


@dataclass
class IntegratedPeak:
    """Represents an integrated peak (automatic, from .rx, or manually adjusted)."""
    peak_id: str
    signal_name: str             # 'FID1A' or 'TCD2B'
    signal_description: str      # 'FID1 A, Front Signal' or 'TCD2 B, Back Signal'
    rt_min: float                # Apex retention time in minutes
    begin_min: float             # Baseline start time in minutes
    end_min: float               # Baseline end time in minutes
    baseline_start_y: float      # Baseline Y value at begin_min
    baseline_end_y: float        # Baseline Y value at end_min
    area: float                  # Integrated area (response * seconds)
    height: float                # Apex height relative to baseline
    area_pct: float = 0.0        # Percentage of total signal area
    height_pct: float = 0.0      # Percentage of total signal height
    width_min: float = 0.0       # Peak width (min)
    symmetry: float = 1.0        # Peak symmetry factor
    baseline_code: str = "BB"    # e.g., 'BB', 'BV', 'VB', 'MM m', 'MM t', 'MM N'
    compound_name: str = ""      # Identified compound name (from Method Compound Table)
    expected_rt: float = 0.0     # Expected RT if matched
    is_negative: bool = False    # True for inverted/negative peaks (e.g., H2 on TCD2B)
    is_tangent_skim: bool = False  # True if rider peak skimmed on tail of a parent peak
    is_manual: bool = False      # True if created/modified manually

    def baseline_y_at(self, t_min: float) -> float:
        """Return linear baseline Y value at retention time t_min."""
        if not isinstance(t_min, (int, float)) or math.isnan(t_min) or math.isinf(t_min):
            return self.baseline_start_y
        span = self.end_min - self.begin_min
        if abs(span) < 1e-12 or math.isnan(span) or math.isinf(span):
            return self.baseline_start_y
        return self.baseline_start_y + (self.baseline_end_y - self.baseline_start_y) * (
            (t_min - self.begin_min) / span
        )


@dataclass
class InjectionData:
    """Represents a loaded .D injection folder."""
    folder_path: str
    folder_name: str             # e.g. 'MPZHY14_reaction_261015--126F.D'
    sample_name: str             # e.g. 'MPZHY14_reaction_261015_126'
    injection_number: int        # Extracted injection number (e.g. 126)
    acq_date: str                # Acquisition timestamp string
    acq_method: str = ""
    pmx_path: Optional[str] = None
    rx_path: Optional[str] = None
    signals: Dict[str, ChromatogramSignal] = field(default_factory=dict)
    peaks_by_signal: Dict[str, List[IntegratedPeak]] = field(default_factory=dict)
    integration_source: str = "auto"  # 'auto', 'rx', or 'manual'

    @property
    def short_label(self) -> str:
        """Compact label for UI and Excel column headers."""
        base = self.folder_name
        if base.upper().endswith(".D"):
            base = base[:-2]
        return base


def _read_pascal_utf16(buf: bytes, offset: int) -> str:
    """Read a length-prefixed UTF-16LE string from an Agilent 179 header."""
    if offset >= len(buf):
        return ""
    length = buf[offset]
    if length == 0 or offset + 1 + length * 2 > len(buf):
        return ""
    raw = buf[offset + 1 : offset + 1 + length * 2]
    return raw.decode("utf-16-le", errors="ignore").strip("\x00").strip()


def read_ch_file(file_path: str) -> ChromatogramSignal:
    """
    Parse an Agilent OpenLab / ChemStation .ch file (version 179 double array format).
    """
    with open(file_path, "rb") as f:
        data = f.read()

    if len(data) < 6144:
        raise ValueError(f"File too small to be a valid Agilent .ch file: {file_path}")

    magic = _read_pascal_utf16(data, 0)
    # Standard offsets for version 179 .ch files
    sample_name = _read_pascal_utf16(data, 858)
    acq_date = _read_pascal_utf16(data, 2391)
    units = _read_pascal_utf16(data, 4172)
    raw_desc = _read_pascal_utf16(data, 4213)

    sig_stem = os.path.splitext(os.path.basename(file_path))[0].upper()
    # Normalize description to match OpenLab (e.g., 'FID1A, Front Signal' -> 'FID1 A, Front Signal')
    if raw_desc.startswith("FID1A"):
        description = "FID1 A" + raw_desc[5:]
    elif raw_desc.startswith("TCD2B"):
        description = "TCD2 B" + raw_desc[5:]
    elif raw_desc:
        description = raw_desc
    else:
        description = sig_stem

    start_ms, end_ms = struct.unpack(">ff", data[282:290])
    slope, intercept = struct.unpack(">dd", data[4732:4748])
    if slope == 0.0:
        slope = 1.0

    raw_doubles = array.array("d")
    payload = data[6144:]
    n_bytes = (len(payload) // 8) * 8
    raw_doubles.frombytes(payload[:n_bytes])
    if os.sys.byteorder != "little":
        raw_doubles.byteswap()

    n_pts = len(raw_doubles)
    if n_pts > 1:
        dt_sec = (end_ms - start_ms) / 1000.0 / (n_pts - 1)
    else:
        dt_sec = 0.02

    t0_min = start_ms / 60000.0
    dt_min = dt_sec / 60.0

    time_min = [t0_min + i * dt_min for i in range(n_pts)]
    values = [v * slope + intercept for v in raw_doubles]

    return ChromatogramSignal(
        name=sig_stem,
        description=description,
        units=units or ("pA" if "FID" in sig_stem else "25 µV"),
        sample_name=sample_name,
        acq_date=acq_date,
        time_min=time_min,
        values=values,
        dt_sec=dt_sec,
        file_path=file_path,
    )


def read_rx_peaks(
    rx_path: str, signals: Dict[str, ChromatogramSignal]
) -> Dict[str, List[IntegratedPeak]]:
    """
    Parse OpenLab .rx archive (Base/InjectionACAML) to extract exact OpenLab
    integrated peaks, baselines, and manual integration flags if present.
    """
    result: Dict[str, List[IntegratedPeak]] = {k: [] for k in signals}
    if not rx_path or not os.path.exists(rx_path):
        return result

    try:
        with zipfile.ZipFile(rx_path, "r") as zf:
            if "Base/InjectionACAML" not in zf.namelist():
                return result
            xml_bytes = zf.read("Base/InjectionACAML")
    except Exception:
        return result

    xml_text = xml_bytes.decode("utf-8", errors="ignore")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return result

    ns = {"a": "urn:schemas-agilent-com:acaml21"}

    # Map Peak_ID -> CompoundName & ExpectedRetTime from InjectionCompound blocks
    peak_to_compound: Dict[str, Tuple[str, float, str]] = {}
    for ic in root.findall(".//a:InjectionCompound", ns):
        cname_el = ic.find("a:CompoundName", ns)
        cname = (cname_el.text or "").strip() if cname_el is not None else ""
        exp_rt_el = ic.find("a:ExpectedRetTime", ns)
        exp_rt = float(exp_rt_el.attrib.get("val", "0")) if exp_rt_el is not None else 0.0
        exp_sig_el = ic.find("a:ExpectedSignal", ns)
        exp_sig = (exp_sig_el.text or "").strip() if exp_sig_el is not None else ""
        for pk_id_el in ic.findall(".//a:Peak_ID", ns):
            pid = pk_id_el.attrib.get("id", "")
            if pid:
                peak_to_compound[pid] = (cname, exp_rt, exp_sig)

    # Also inspect ManualIntegration CustomField to map SignalId -> SignalName ('FID1A' / 'TCD2B')
    # and identify which SignalResult belongs to which signal
    sig_results = root.findall(".//a:SignalResult", ns)
    sig_keys = list(signals.keys())

    for idx, sr in enumerate(sig_results):
        peaks_el = sr.findall(".//a:Peak", ns)
        if not peaks_el:
            continue

        # Determine which signal ('FID1A' vs 'TCD2B') this SignalResult corresponds to
        matched_sig = None
        for p in peaks_el:
            pid = p.attrib.get("id", "")
            if pid in peak_to_compound and peak_to_compound[pid][2] in signals:
                matched_sig = peak_to_compound[pid][2]
                break
        if not matched_sig:
            # Fallback by unit or index
            first_area = peaks_el[0].find("a:Area", ns)
            unit_str = first_area.attrib.get("unit", "") if first_area is not None else ""
            if "pA" in unit_str and "FID1A" in signals:
                matched_sig = "FID1A"
            elif "TCD2B" in signals and idx == 1:
                matched_sig = "TCD2B"
            elif idx < len(sig_keys):
                matched_sig = sig_keys[idx]

        if not matched_sig or matched_sig not in signals:
            continue

        sig_obj = signals[matched_sig]
        parsed_peaks: List[IntegratedPeak] = []

        for p in peaks_el:
            pid = p.attrib.get("id", "")
            rt = float(p.find("a:RetentionTime", ns).attrib.get("val", "0"))
            area = float(p.find("a:Area", ns).attrib.get("val", "0"))
            height = float(p.find("a:Height", ns).attrib.get("val", "0"))
            area_pct_el = p.find("a:AreaPercent", ns)
            area_pct = float(area_pct_el.attrib.get("val", "0")) if area_pct_el is not None else 0.0
            height_pct_el = p.find("a:HeightPercent", ns)
            height_pct = float(height_pct_el.attrib.get("val", "0")) if height_pct_el is not None else 0.0
            begin_t = float(p.find("a:BeginTime", ns).attrib.get("val", "0"))
            end_t = float(p.find("a:EndTime", ns).attrib.get("val", "0"))
            bs_el = p.find("a:BaselineStart", ns)
            be_el = p.find("a:BaselineEnd", ns)
            bs_y = float(bs_el.attrib.get("val", "0")) if bs_el is not None else sig_obj.value_at_time(begin_t)
            be_y = float(be_el.attrib.get("val", "0")) if be_el is not None else sig_obj.value_at_time(end_t)
            wb_el = p.find("a:WidthBase", ns)
            width_b = float(wb_el.attrib.get("val", str(end_t - begin_t))) if wb_el is not None else (end_t - begin_t)
            sym_el = p.find("a:Symmetry", ns)
            sym = float(sym_el.attrib.get("val", "1.0")) if (sym_el is not None and "val" in sym_el.attrib) else 1.0
            bcode_el = p.find("a:BaselineCode", ns)
            bcode = (bcode_el.text or "BB").strip() if bcode_el is not None else "BB"

            cname, exp_rt, _ = peak_to_compound.get(pid, ("", 0.0, ""))
            is_neg = ("N" in bcode.upper()) or (
                sig_obj.value_at_time(rt) < (bs_y + be_y) * 0.5
            )
            is_skim = "t" in bcode

            parsed_peaks.append(
                IntegratedPeak(
                    peak_id=pid or f"{matched_sig}_{rt:.3f}",
                    signal_name=matched_sig,
                    signal_description=sig_obj.description,
                    rt_min=rt,
                    begin_min=begin_t,
                    end_min=end_t,
                    baseline_start_y=bs_y,
                    baseline_end_y=be_y,
                    area=area,
                    height=height,
                    area_pct=area_pct,
                    height_pct=height_pct,
                    width_min=width_b,
                    symmetry=sym,
                    baseline_code=bcode,
                    compound_name=cname,
                    expected_rt=exp_rt,
                    is_negative=is_neg,
                    is_tangent_skim=is_skim,
                    is_manual=bcode.startswith("M") or ("m" in bcode.lower()),
                )
            )

        parsed_peaks.sort(key=lambda pk: pk.rt_min)
        result[matched_sig] = parsed_peaks

    return result


def extract_injection_number(folder_name: str, sample_name: str = "") -> int:
    """Extract numeric injection sequence number from folder or sample name."""
    # Look for patterns like '--126F.D' or '_126'
    m = re.search(r"--(\d+)[A-Za-z]?\.D$", folder_name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r"[_-](\d+)[A-Za-z]?$", sample_name)
    if m2:
        return int(m2.group(1))
    nums = re.findall(r"(\d+)", folder_name)
    return int(nums[-1]) if nums else 1


def load_d_folder(folder_path: str) -> InjectionData:
    """
    Load an Agilent .D injection folder, including all .ch chromatogram files,
    any .pmx method path, and .rx file path.
    """
    folder_path = os.path.abspath(folder_path)
    folder_name = os.path.basename(folder_path)

    signals: Dict[str, ChromatogramSignal] = {}
    pmx_path: Optional[str] = None
    rx_path: Optional[str] = None

    for fname in sorted(os.listdir(folder_path)):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        lower = fname.lower()
        if lower.endswith(".ch"):
            try:
                sig = read_ch_file(fpath)
                signals[sig.name] = sig
            except Exception as exc:
                print(f"Warning: could not read {fpath}: {exc}")
        elif lower.endswith(".pmx") and pmx_path is None:
            pmx_path = fpath
        elif lower.endswith(".rx") and rx_path is None:
            rx_path = fpath

    first_sig = next(iter(signals.values()), None)
    sample_name = first_sig.sample_name if first_sig and first_sig.sample_name else folder_name
    acq_date = first_sig.acq_date if first_sig else ""
    inj_num = extract_injection_number(folder_name, sample_name)

    return InjectionData(
        folder_path=folder_path,
        folder_name=folder_name,
        sample_name=sample_name,
        injection_number=inj_num,
        acq_date=acq_date,
        pmx_path=pmx_path,
        rx_path=rx_path,
        signals=signals,
    )


def find_d_folders(path: str) -> List[str]:
    """
    Given a directory path (either a single .D folder, a sequence folder, or workspace root),
    return a sorted list of .D folder paths. Probes candidate subfolders ('test-set', 'data-set')
    and subdirectories up to depth 2 if top path has no immediate .D folders.
    """
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return []

    try:
        entries = os.listdir(path)
    except OSError:
        return []

    # Check if path itself is a .D folder (or contains .ch files directly)
    has_ch = any(f.lower().endswith(".ch") for f in entries if os.path.isfile(os.path.join(path, f)))
    if path.upper().endswith(".D") or has_ch:
        return [path]

    d_folders: List[str] = []
    for entry in entries:
        sub = os.path.join(path, entry)
        if os.path.isdir(sub):
            if entry.upper().endswith(".D"):
                d_folders.append(sub)
            else:
                try:
                    if any(f.lower().endswith(".ch") for f in os.listdir(sub) if os.path.isfile(os.path.join(sub, f))):
                        d_folders.append(sub)
                except OSError:
                    continue

    # If no immediate .D folders found, probe common candidate sequence folders
    if not d_folders:
        for candidate in ("test-set", "data-set", "sequences", "data"):
            cand_path = os.path.join(path, candidate)
            if os.path.isdir(cand_path):
                cand_res = find_d_folders(cand_path)
                if cand_res:
                    return cand_res

        # Probe depth-2 subfolders (any immediate subfolder containing .D folders)
        for entry in entries:
            sub = os.path.join(path, entry)
            if os.path.isdir(sub) and not entry.startswith("."):
                try:
                    sub_entries = os.listdir(sub)
                except OSError:
                    continue
                sub_d: List[str] = []
                for sub_e in sub_entries:
                    sub_sub = os.path.join(sub, sub_e)
                    if os.path.isdir(sub_sub) and (
                        sub_e.upper().endswith(".D")
                        or any(f.lower().endswith(".ch") for f in os.listdir(sub_sub) if os.path.isfile(os.path.join(sub_sub, f)))
                    ):
                        sub_d.append(sub_sub)
                if sub_d:
                    sub_d.sort(key=lambda p: (extract_injection_number(os.path.basename(p)), os.path.basename(p)))
                    return sub_d

    d_folders.sort(key=lambda p: (extract_injection_number(os.path.basename(p)), os.path.basename(p)))
    return d_folders
