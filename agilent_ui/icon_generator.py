"""
Programmatic Windows Multi-Resolution ICO Generator for OpenChromLab (F12).
Generates OpenChromLab.ico containing 5 uncompressed 32-bit BGRA DIB frames
(16x16, 24x24, 32x32, 48x48, 256x256) depicting the UPGRADE dark-themed
rounded-square badge with a glowing cyan chromatogram peak and pink apex crosshair.
Pure Python standard library (`struct`, `math`) — zero external dependencies.
"""

import math
import os
import struct
from typing import List, Tuple


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 == edge0:
        return 1.0 if x >= edge1 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _blend(
    dst: Tuple[float, float, float, float],
    src_rgb: Tuple[int, int, int],
    src_a: float,
) -> Tuple[float, float, float, float]:
    """Alpha-blend src_rgb (with opacity src_a in [0,1]) over dst (r, g, b, a)."""
    sa = max(0.0, min(1.0, src_a))
    if sa <= 0.0:
        return dst
    dr, dg, db, da = dst
    out_a = sa + da * (1.0 - sa)
    if out_a <= 1e-6:
        return (0.0, 0.0, 0.0, 0.0)
    sr, sg, sb = src_rgb
    out_r = (sr * sa + dr * da * (1.0 - sa)) / out_a
    out_g = (sg * sa + dg * da * (1.0 - sa)) / out_a
    out_b = (sb * sa + db * da * (1.0 - sa)) / out_a
    return (out_r, out_g, out_b, out_a)


def _sd_rounded_box(px: float, py: float, cx: float, cy: float, half_w: float, half_h: float, r: float) -> float:
    qx = abs(px - cx) - (half_w - r)
    qy = abs(py - cy) - (half_h - r)
    out_dist = math.hypot(max(qx, 0.0), max(qy, 0.0))
    in_dist = min(max(qx, qy), 0.0)
    return out_dist + in_dist - r


def _dist_to_segment(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> float:
    vx = x1 - x0
    vy = y1 - y0
    wx = px - x0
    wy = py - y0
    c1 = wx * vx + wy * vy
    if c1 <= 0.0:
        return math.hypot(px - x0, py - y0)
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(px - x1, py - y1)
    b = c1 / c2
    bx = x0 + b * vx
    by = y0 + b * vy
    return math.hypot(px - bx, py - by)


def _chromatogram_y(u: float) -> float:
    """
    Normalized chromatogram curve y in [0, 1] (0=bottom, 1=top) as a function of u in [0, 1]:
    - Baseline at y = 0.22
    - Secondary pre-peak at u = 0.28, height 0.24
    - Main sharp Gaussian peak at u = 0.56, height 0.62 (apex at y = 0.84)
    - Small product peak at u = 0.80, height 0.16
    """
    base = 0.22
    p1 = 0.24 * math.exp(-0.5 * ((u - 0.28) / 0.055) ** 2)
    p2 = 0.62 * math.exp(-0.5 * ((u - 0.56) / 0.068) ** 2)
    p3 = 0.16 * math.exp(-0.5 * ((u - 0.80) / 0.048) ** 2)
    return base + p1 + p2 + p3


def render_icon_frame_dib(size: int) -> bytes:
    """
    Render a single `size x size` 32-bit BGRA DIB frame (BITMAPINFOHEADER + XOR BGRA + AND mask)
    for embedding inside a Windows .ico resource.
    """
    w = size
    h = size
    aa = 1.25 / max(16.0, float(size))

    # Pre-sample polyline segments for accurate distance-to-curve rendering
    n_seg = max(32, min(128, size * 2))
    curve_pts: List[Tuple[float, float]] = []
    for i in range(n_seg + 1):
        u = 0.12 + 0.76 * (i / n_seg)
        v = _chromatogram_y(u)
        curve_pts.append((u, v))

    apex_u = 0.56
    apex_v = _chromatogram_y(apex_u)
    base_v = 0.22

    xor_rows: List[bytes] = []
    and_row_stride = ((w + 31) // 32) * 4
    and_rows: List[bytes] = []

    stroke_r = max(0.032, 1.35 / size)
    glow_r = stroke_r * 2.6

    # DIB rows are stored bottom-up (row 0 = bottom of image)
    for iy in range(h):
        ny = (iy + 0.5) / h  # 0 at bottom, 1 at top
        row_bytes = bytearray(w * 4)
        and_bits = bytearray(and_row_stride)

        for ix in range(w):
            nx = (ix + 0.5) / w  # 0 at left, 1 at right

            # 1. Rounded square dark badge (#11161F -> #182234 vertical gradient)
            sd_badge = _sd_rounded_box(nx, ny, 0.5, 0.5, 0.45, 0.45, 0.19)
            badge_alpha = 1.0 - _smoothstep(-aa, aa, sd_badge)
            if badge_alpha <= 0.004:
                # Fully transparent outer corner pixel -> set AND mask bit = 1
                and_bits[ix >> 3] |= (1 << (7 - (ix & 7)))
                continue

            # Background dark slate-navy gradient
            bg_r = int(17 + 10 * ny)
            bg_g = int(22 + 14 * ny)
            bg_b = int(31 + 22 * ny)
            col: Tuple[float, float, float, float] = (float(bg_r), float(bg_g), float(bg_b), badge_alpha)

            # Subtle steel-blue inner border (#2E3E56 -> #38BDF8 top highlight)
            border_band = 1.0 - _smoothstep(0.0, max(0.025, 1.3 / size), abs(sd_badge + 0.015))
            if border_band > 0.01:
                col = _blend(col, (56, 130, 200), border_band * 0.55 * badge_alpha)

            # 2. Subtle grid lines inside plot area
            if 0.12 <= nx <= 0.88 and 0.18 <= ny <= 0.86:
                for gy in (0.38, 0.56, 0.74):
                    if abs(ny - gy) < (0.8 / size):
                        col = _blend(col, (34, 46, 66), 0.55 * badge_alpha)
                for gx in (0.30, 0.56, 0.80):
                    if abs(nx - gx) < (0.8 / size):
                        col = _blend(col, (34, 46, 66), 0.45 * badge_alpha)

            # 3. Shaded area under chromatogram curve (#162A42 -> #1E446E)
            if 0.12 <= nx <= 0.88:
                cy_at_x = _chromatogram_y(nx)
                if base_v <= ny <= cy_at_x:
                    fill_t = (ny - base_v) / max(0.01, cy_at_x - base_v)
                    sh_r = int(22 + 30 * fill_t)
                    sh_g = int(46 + 75 * fill_t)
                    sh_b = int(74 + 115 * fill_t)
                    col = _blend(col, (sh_r, sh_g, sh_b), (0.38 + 0.32 * fill_t) * badge_alpha)

            # 4. Baseline horizontal line + anchor dots at y = 0.22
            if 0.12 <= nx <= 0.88 and abs(ny - base_v) <= max(0.012, 0.85 / size):
                col = _blend(col, (148, 163, 184), 0.75 * badge_alpha)

            # 5. Distance to chromatogram curve for outer glow (#1E6091) and core cyan line (#38BDF8 -> #7DD3FC)
            if 0.08 <= nx <= 0.92:
                min_d = 10.0
                for k in range(len(curve_pts) - 1):
                    x0, y0 = curve_pts[k]
                    x1, y1 = curve_pts[k + 1]
                    if nx < x0 - glow_r and nx < x1 - glow_r:
                        continue
                    if nx > x0 + glow_r and nx > x1 + glow_r:
                        continue
                    d = _dist_to_segment(nx, ny, x0, y0, x1, y1)
                    if d < min_d:
                        min_d = d

                if min_d < glow_r:
                    glow_a = (1.0 - _smoothstep(stroke_r * 0.6, glow_r, min_d)) * 0.55
                    col = _blend(col, (30, 110, 195), glow_a * badge_alpha)

                if min_d < stroke_r + aa:
                    core_a = 1.0 - _smoothstep(stroke_r - aa, stroke_r + aa, min_d)
                    col = _blend(col, (77, 196, 255), core_a * badge_alpha)

            # 6. Pink/magenta apex marker (#F472B6) & gold anchor handles (#FBBF24)
            d_apex = math.hypot(nx - apex_u, ny - apex_v)
            apex_rad = max(0.048, 1.7 / size)
            if d_apex <= apex_rad + aa:
                ap_a = 1.0 - _smoothstep(apex_rad - aa, apex_rad + aa, d_apex)
                col = _blend(col, (244, 114, 182), ap_a * badge_alpha)

            for anc_u in (0.42, 0.70):
                d_anc = math.hypot(nx - anc_u, ny - base_v)
                anc_rad = max(0.036, 1.3 / size)
                if d_anc <= anc_rad + aa:
                    an_a = 1.0 - _smoothstep(anc_rad - aa, anc_rad + aa, d_anc)
                    col = _blend(col, (251, 191, 36), an_a * badge_alpha)

            r_i = max(0, min(255, int(round(col[0]))))
            g_i = max(0, min(255, int(round(col[1]))))
            b_i = max(0, min(255, int(round(col[2]))))
            a_i = max(0, min(255, int(round(col[3] * 255.0))))

            off = ix * 4
            row_bytes[off] = b_i
            row_bytes[off + 1] = g_i
            row_bytes[off + 2] = r_i
            row_bytes[off + 3] = a_i

            if a_i < 16:
                and_bits[ix >> 3] |= (1 << (7 - (ix & 7)))

        xor_rows.append(bytes(row_bytes))
        and_rows.append(bytes(and_bits))

    xor_data = b"".join(xor_rows)
    and_data = b"".join(and_rows)
    img_bytes = len(xor_data) + len(and_data)

    # BITMAPINFOHEADER (40 bytes): biHeight is 2*h (XOR + AND masks)
    bih = struct.pack(
        "<IiiHHIIiiII",
        40,         # biSize
        w,          # biWidth
        h * 2,      # biHeight (doubled for ICO DIB)
        1,          # biPlanes
        32,         # biBitCount (32-bit BGRA)
        0,          # biCompression (BI_RGB = 0)
        img_bytes,  # biSizeImage
        0,          # biXPelsPerMeter
        0,          # biYPelsPerMeter
        0,          # biClrUsed
        0,          # biClrImportant
    )
    return bih + xor_data + and_data


def build_multi_res_ico(
    output_path: str,
    resolutions: Tuple[int, ...] = (16, 24, 32, 48, 256),
) -> str:
    """
    Generate a valid multi-resolution Windows .ico file at `output_path` and return its absolute path.
    """
    frames: List[Tuple[int, bytes]] = []
    for sz in resolutions:
        frames.append((sz, render_icon_frame_dib(sz)))

    count = len(frames)
    # ICONDIR header: reserved=0, type=1 (ICO), count=N
    icondir = struct.pack("<HHH", 0, 1, count)

    dir_entries: List[bytes] = []
    offset = 6 + 16 * count
    for sz, data in frames:
        b_width = 0 if sz >= 256 else sz
        b_height = 0 if sz >= 256 else sz
        entry = struct.pack(
            "<BBBBHHII",
            b_width,    # bWidth (0 means 256)
            b_height,   # bHeight (0 means 256)
            0,          # bColorCount
            0,          # bReserved
            1,          # wPlanes
            32,         # wBitCount
            len(data),  # dwBytesInRes
            offset,     # dwImageOffset
        )
        dir_entries.append(entry)
        offset += len(data)

    abs_out = os.path.abspath(output_path)
    with open(abs_out, "wb") as f:
        f.write(icondir)
        for ent in dir_entries:
            f.write(ent)
        for _, data in frames:
            f.write(data)
    return abs_out


if __name__ == "__main__":
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target_ico = os.path.join(root_dir, "OpenChromLab.ico")
    out = build_multi_res_ico(target_ico)
    print(f"Generated {out} ({os.path.getsize(out)} bytes)")
