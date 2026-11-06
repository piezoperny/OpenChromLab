"""
Excel (.xlsx) Exporter for OpenLab CDS Substitute.
Exports all injections in a single sheet where:
  - Columns = Injections (sorted in sequence order)
  - Rows    = Specific Compounds from the Method Compound Table
Designed for immediate graphing in Excel.
"""

from typing import Dict, List, Optional, Tuple
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .ch_reader import InjectionData, IntegratedPeak
from .method_model import CompoundDef, ProcessingMethod


def _lookup_compound_peak(
    inj: InjectionData, comp: CompoundDef
) -> Optional[IntegratedPeak]:
    """Find the integrated peak matched to `comp` in `inj`, enforcing polarity."""
    sig_peaks = inj.peaks_by_signal.get(comp.signal, [])
    for pk in sig_peaks:
        if pk.compound_name.strip().lower() == comp.name.strip().lower():
            if pk.is_negative == comp.is_negative_peak:
                return pk
    # Fallback: check if any unnamed peak falls in the compound's RT window and matches polarity
    w_min, w_max = comp.window_range
    candidates = [
        pk
        for pk in sig_peaks
        if not pk.compound_name
        and w_min <= pk.rt_min <= w_max
        and (pk.is_negative == comp.is_negative_peak)
    ]
    if candidates:
        if comp.peak_match.lower() == "largest":
            return max(candidates, key=lambda p: p.area)
        return min(candidates, key=lambda p: abs(p.rt_min - comp.exp_rt_min))
    return None


def export_sequence_single_sheet_xlsx(
    injections: List[InjectionData],
    method: ProcessingMethod,
    output_path: str,
    include_extra_blocks: bool = True,
) -> str:
    """
    Export all loaded injections into a SINGLE Excel sheet where:
      - Columns = Injections (Col E onwards)
      - Rows    = Specific Compounds (1..N from Method Compound Table)

    The primary block at the top is Peak Area (so selecting the rows and clicking
    Insert Chart in Excel graphs Compound Area vs. Injection immediately).
    Optionally includes Area%, Height, and RT (min) blocks further down on the same sheet.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compound_vs_Injections"

    # Styling definitions
    font_title = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    font_header = Font(name="Segoe UI", size=10, bold=True, color="1F3864")
    font_meta = Font(name="Segoe UI", size=9, italic=True, color="333333")
    font_comp = Font(name="Segoe UI", size=10, bold=True, color="000000")
    font_data = Font(name="Segoe UI", size=10, bold=False, color="000000")

    fill_banner = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    fill_header = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    fill_meta = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid")
    fill_zebra = PatternFill(start_color="F9FAFC", end_color="F9FAFC", fill_type="solid")
    fill_sum = PatternFill(start_color="EDEDED", end_color="EDEDED", fill_type="solid")

    thin_side = Side(border_style="thin", color="D0D7DE")
    med_bottom = Side(border_style="medium", color="1F4E78")
    border_cell = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    border_header = Border(left=thin_side, right=thin_side, top=thin_side, bottom=med_bottom)

    align_left = Alignment(horizontal="left", vertical="center")
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    compounds = method.compounds

    def write_matrix_block(
        start_row: int,
        block_title: str,
        metric_key: str,
        num_format: str,
    ) -> int:
        """
        Write a (Compounds x Injections) matrix block starting at `start_row`.
        Returns the next available row index after this block.
        """
        r = start_row
        total_cols = max(4 + len(injections), 5)

        # Banner row
        ws.cell(row=r, column=1, value=block_title)
        for c in range(1, total_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_title
            cell.fill = fill_banner
            cell.alignment = align_left if c == 1 else align_center
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        r += 1

        # Injection Metadata Row 1: Sequence / Injection #
        ws.cell(row=r, column=1, value="")
        ws.cell(row=r, column=2, value="Injection #")
        ws.cell(row=r, column=3, value="")
        ws.cell(row=r, column=4, value="")
        for c in range(1, 5):
            ws.cell(row=r, column=c).font = font_meta
            ws.cell(row=r, column=c).fill = fill_meta
        for idx, inj in enumerate(injections):
            col = 5 + idx
            cell = ws.cell(row=r, column=col, value=inj.injection_number)
            cell.font = font_meta
            cell.fill = fill_meta
            cell.alignment = align_center
        r += 1

        # Injection Metadata Row 2: Acquisition Date/Time
        ws.cell(row=r, column=2, value="Acquisition Date")
        for c in range(1, 5):
            ws.cell(row=r, column=c).font = font_meta
            ws.cell(row=r, column=c).fill = fill_meta
        for idx, inj in enumerate(injections):
            col = 5 + idx
            cell = ws.cell(row=r, column=col, value=inj.acq_date)
            cell.font = font_meta
            cell.fill = fill_meta
            cell.alignment = align_center
        r += 1

        # Main Column Header Row (Compound info + Injection Names as column headers)
        headers = ["#", "Compound", "Signal", "Exp. RT (min)"]
        for c, h_text in enumerate(headers, start=1):
            cell = ws.cell(row=r, column=c, value=h_text)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = border_header
            cell.alignment = align_center if c != 2 else align_left

        for idx, inj in enumerate(injections):
            col = 5 + idx
            label = inj.sample_name or inj.short_label
            cell = ws.cell(row=r, column=col, value=label)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = border_header
            cell.alignment = align_center
        r += 1

        # Compound Rows (Rows = Specific Compounds, Columns = Injections)
        first_data_row = r
        for comp_idx, comp in enumerate(compounds):
            is_even = (comp_idx % 2 == 1)
            row_fill = fill_zebra if is_even else None

            c1 = ws.cell(row=r, column=1, value=comp.index)
            c2 = ws.cell(row=r, column=2, value=comp.name)
            c3 = ws.cell(row=r, column=3, value=comp.signal)
            c4 = ws.cell(row=r, column=4, value=round(comp.exp_rt_min, 3))

            c1.alignment = align_center
            c2.alignment = align_left
            c3.alignment = align_center
            c4.alignment = align_right
            c4.number_format = "0.000"

            for c_cell in (c1, c2, c3, c4):
                c_cell.font = font_comp if c_cell is c2 else font_data
                c_cell.border = border_cell
                if row_fill:
                    c_cell.fill = row_fill

            for idx, inj in enumerate(injections):
                col = 5 + idx
                pk = _lookup_compound_peak(inj, comp)
                if pk is None:
                    val = 0.0 if metric_key != "rt" else None
                else:
                    if metric_key == "area":
                        val = round(pk.area, 4)
                    elif metric_key == "area_pct":
                        val = round(pk.area_pct, 4)
                    elif metric_key == "height":
                        val = round(pk.height, 4)
                    elif metric_key == "rt":
                        val = round(pk.rt_min, 3)
                    else:
                        val = 0.0

                cell = ws.cell(row=r, column=col, value=val)
                cell.font = font_data
                cell.border = border_cell
                cell.alignment = align_right
                if val is not None:
                    cell.number_format = num_format
                if row_fill:
                    cell.fill = row_fill

            r += 1

        last_data_row = r - 1

        # Add Total Row for Area / Height blocks
        if metric_key in ("area", "height") and last_data_row >= first_data_row:
            ws.cell(row=r, column=1, value="")
            ws.cell(row=r, column=2, value=f"Total Identified {metric_key.capitalize()}")
            ws.cell(row=r, column=3, value="")
            ws.cell(row=r, column=4, value="")
            for c in range(1, 5):
                ws.cell(row=r, column=c).font = font_header
                ws.cell(row=r, column=c).fill = fill_sum
                ws.cell(row=r, column=c).border = border_cell
            for idx in range(len(injections)):
                col = 5 + idx
                col_let = get_column_letter(col)
                formula = f"=SUM({col_let}{first_data_row}:{col_let}{last_data_row})"
                cell = ws.cell(row=r, column=col, value=formula)
                cell.font = font_header
                cell.fill = fill_sum
                cell.border = border_cell
                cell.alignment = align_right
                cell.number_format = num_format
            r += 1

        return r + 2  # Leave 2 blank rows before next block

    # Write Primary Block: Peak Area (Columns = Injections, Rows = Compounds)
    next_row = write_matrix_block(
        start_row=1,
        block_title=f"PEAK AREA MATRIX ({method.name}) — Columns: Injections | Rows: Compounds",
        metric_key="area",
        num_format="0.000",
    )

    if include_extra_blocks:
        next_row = write_matrix_block(
            start_row=next_row,
            block_title="PEAK AREA % MATRIX — Columns: Injections | Rows: Compounds",
            metric_key="area_pct",
            num_format="0.000",
        )
        next_row = write_matrix_block(
            start_row=next_row,
            block_title="PEAK HEIGHT MATRIX — Columns: Injections | Rows: Compounds",
            metric_key="height",
            num_format="0.000",
        )
        next_row = write_matrix_block(
            start_row=next_row,
            block_title="RETENTION TIME (min) MATRIX — Columns: Injections | Rows: Compounds",
            metric_key="rt",
            num_format="0.000",
        )

    # Auto-fit column widths
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 14
    for idx, inj in enumerate(injections):
        col_let = get_column_letter(5 + idx)
        label_len = max(len(inj.sample_name or ""), len(inj.short_label), 14)
        ws.column_dimensions[col_let].width = min(max(label_len + 3, 15), 28)

    # Freeze left compound columns (A..D) and top header rows (1..4) so scrolling across
    # many injections keeps the compound names locked on the left!
    ws.freeze_panes = "E5"

    try:
        wb.save(output_path)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot save export to '{output_path}'. The file appears to be open in Microsoft Excel "
            f"or another program, or write access was denied. Please close the file and try again."
        ) from exc
    except OSError as exc:
        raise OSError(
            f"Cannot save export to '{output_path}': {exc}"
        ) from exc

    return output_path
