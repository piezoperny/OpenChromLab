"""
OpenChromLab Unified Theme Management (Light and Dark Modes).
Provides standardized color palettes for application windows, toolbars,
treeviews, and chromatogram plot canvas elements.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    """Immutable color palette definition for OpenChromLab UI and Canvas."""
    name: str

    # App & Frames
    bg_app: str
    bg_frame: str
    fg_app: str

    # Header & Toolbar
    topbar_bg: str
    topbar_fg: str
    topbar_btn_bg: str
    topbar_btn_fg: str
    subbar_bg: str
    subbar_fg: str
    subbar_btn_bg: str
    subbar_btn_fg: str

    # Canvas & Chromatogram Plot
    canvas_bg: str
    panel_bg: str
    panel_border: str
    grid_line: str
    axis_tick: str
    axis_text: str
    panel_title: str
    axis_title: str
    trace_fid: str
    trace_tcd: str
    baseline_normal: str
    baseline_negative: str
    baseline_selected: str
    peak_drop_line: str
    anchor_fill: str
    anchor_outline: str
    anchor_selected: str
    apex_marker: str
    label_compound: str
    label_unnamed: str
    label_selected: str
    leader_line: str
    rt_window_line: str
    rt_window_hi_fill: str
    rt_window_hi_line: str
    shaded_pos_fill: str
    shaded_neg_fill: str
    timed_event_on: str
    timed_event_off: str
    timed_event_bl: str
    zoom_box_line: str

    # Treeviews & Tables
    tree_bg: str
    tree_fg: str
    tree_header_bg: str
    tree_header_fg: str
    tree_selected_bg: str
    tree_selected_fg: str
    tag_identified_bg: str
    tag_identified_fg: str
    tag_negative_bg: str
    tag_negative_fg: str
    tag_unidentified_fg: str
    tag_found_bg: str
    tag_missing_fg: str

    # Status bar
    status_bg: str
    status_fg: str

    # Extended modern UI tokens (default values preserve 48-arg backward compatibility)
    topbar_btn_border: str = "#344054"
    subbar_btn_border: str = "#2E3A4E"
    subbar_active_bg: str = "#2563EB"
    subbar_active_fg: str = "#FFFFFF"
    subbar_active_border: str = "#3B82F6"
    subbar_delete_fg: str = "#F87171"
    method_badge_bg: str = "#1E2636"
    method_badge_fg: str = "#FBBF24"
    method_badge_border: str = "#334155"
    seq_header_bg: str = "#18202C"
    seq_header_fg: str = "#E2E8F0"
    overlay_card_bg: str = "#151C28"
    overlay_card_border: str = "#263040"
    toggle_on_bg: str = "#3898EC"
    toggle_off_bg: str = "#222630"
    toggle_knob_on: str = "#FFFFFF"
    toggle_knob_off: str = "#94A3B8"
    tab_active_bg: str = "#0E4149"
    tab_active_fg: str = "#38BDF8"
    tab_inactive_bg: str = "#161C27"
    tab_inactive_fg: str = "#94A3B8"
    trace_glow: str = "#1E3A5F"
    trace_under_fill: str = "#162A42"
    rt_window_band_fill: str = "#152232"
    event_on_pill_bg: str = "#132E28"
    event_on_pill_border: str = "#10B981"
    event_off_pill_bg: str = "#311B22"
    event_off_pill_border: str = "#EF4444"


LIGHT_PALETTE = ThemePalette(
    name="light",
    bg_app="#F0F2F5",
    bg_frame="#FFFFFF",
    fg_app="#1F3864",
    topbar_bg="#1F3864",
    topbar_fg="#FFFFFF",
    topbar_btn_bg="#FFFFFF",
    topbar_btn_fg="#1F3864",
    subbar_bg="#E9EDF4",
    subbar_fg="#1F3864",
    subbar_btn_bg="#FFFFFF",
    subbar_btn_fg="#1F3864",
    canvas_bg="#FFFFFF",
    panel_bg="#FAFAFC",
    panel_border="#B8C0CC",
    grid_line="#EAECEF",
    axis_tick="#666666",
    axis_text="#333333",
    panel_title="#1F3864",
    axis_title="#333333",
    trace_fid="#0067B8",
    trace_tcd="#0067B8",
    baseline_normal="#222222",
    baseline_negative="#881798",
    baseline_selected="#D83B01",
    peak_drop_line="#555555",
    anchor_fill="#FFFFFF",
    anchor_outline="#222222",
    anchor_selected="#FFD700",
    apex_marker="#B4009E",
    label_compound="#004578",
    label_unnamed="#555555",
    label_selected="#D83B01",
    leader_line="#999999",
    rt_window_line="#B3D7FF",
    rt_window_hi_fill="#E6F2FF",
    rt_window_hi_line="#0078D4",
    shaded_pos_fill="#D0E8FF",
    shaded_neg_fill="#FFE8CC",
    timed_event_on="#107C10",
    timed_event_off="#A4262C",
    timed_event_bl="#8764B8",
    zoom_box_line="#0078D4",
    tree_bg="#FFFFFF",
    tree_fg="#000000",
    tree_header_bg="#E1E6EB",
    tree_header_fg="#1F3864",
    tree_selected_bg="#CCE4F7",
    tree_selected_fg="#000000",
    tag_identified_bg="#F2F8FF",
    tag_identified_fg="#000000",
    tag_negative_bg="#FFF4EA",
    tag_negative_fg="#000000",
    tag_unidentified_fg="#555555",
    tag_found_bg="#F2F9F4",
    tag_missing_fg="#888888",
    status_bg="#1F3864",
    status_fg="#FFFFFF",
    topbar_btn_border="#C8D1E0",
    subbar_btn_border="#B8C0CC",
    subbar_active_bg="#CCE4F7",
    subbar_active_fg="#1F3864",
    subbar_active_border="#0078D4",
    subbar_delete_fg="#A4262C",
    method_badge_bg="#2B4C7E",
    method_badge_fg="#FFD700",
    method_badge_border="#3E65A0",
    seq_header_bg="#D9E1F2",
    seq_header_fg="#1F3864",
    overlay_card_bg="#FFFFFF",
    overlay_card_border="#C8D1E0",
    toggle_on_bg="#0078D4",
    toggle_off_bg="#CBD5E1",
    toggle_knob_on="#FFFFFF",
    toggle_knob_off="#FFFFFF",
    tab_active_bg="#FFFFFF",
    tab_active_fg="#1F3864",
    tab_inactive_bg="#E1E6EB",
    tab_inactive_fg="#4A5568",
    trace_glow="#D8ECFF",
    trace_under_fill="#EBF5FF",
    rt_window_band_fill="#F3F8FF",
    event_on_pill_bg="#E8F5E9",
    event_on_pill_border="#2E7D32",
    event_off_pill_bg="#FFEBEE",
    event_off_pill_border="#C62828",
)


DARK_PALETTE = ThemePalette(
    name="dark",
    bg_app="#0D1117",
    bg_frame="#161C27",
    fg_app="#CBD5E1",
    topbar_bg="#151B26",
    topbar_fg="#F0F6FC",
    topbar_btn_bg="#212936",
    topbar_btn_fg="#E2E8F0",
    subbar_bg="#18202C",
    subbar_fg="#9AA2B0",
    subbar_btn_bg="#1E2634",
    subbar_btn_fg="#CBD5E1",
    canvas_bg="#0D1117",
    panel_bg="#0D1117",
    panel_border="#263040",
    grid_line="#1C2433",
    axis_tick="#64748B",
    axis_text="#94A3B8",
    panel_title="#7DD3FC",
    axis_title="#CBD5E1",
    trace_fid="#4DA6FF",
    trace_tcd="#38BDF8",
    baseline_normal="#94A3B8",
    baseline_negative="#C084FC",
    baseline_selected="#F97316",
    peak_drop_line="#475569",
    anchor_fill="#0D1117",
    anchor_outline="#38BDF8",
    anchor_selected="#FBBF24",
    apex_marker="#F472B6",
    label_compound="#93C5FD",
    label_unnamed="#94A3B8",
    label_selected="#FDBA74",
    leader_line="#475569",
    rt_window_line="#2A4365",
    rt_window_hi_fill="#16293E",
    rt_window_hi_line="#38BDF8",
    shaded_pos_fill="#172E47",
    shaded_neg_fill="#3B2119",
    timed_event_on="#34D399",
    timed_event_off="#F87171",
    timed_event_bl="#C084FC",
    zoom_box_line="#38BDF8",
    tree_bg="#131822",
    tree_fg="#D1D5DB",
    tree_header_bg="#1B2332",
    tree_header_fg="#CBD5E1",
    tree_selected_bg="#254B7C",
    tree_selected_fg="#FFFFFF",
    tag_identified_bg="#182638",
    tag_identified_fg="#F1F5F9",
    tag_negative_bg="#2B1F1D",
    tag_negative_fg="#FDBA74",
    tag_unidentified_fg="#64748B",
    tag_found_bg="#132A24",
    tag_missing_fg="#64748B",
    status_bg="#0D1117",
    status_fg="#94A3B8",
    topbar_btn_border="#344054",
    subbar_btn_border="#2E3A4E",
    subbar_active_bg="#2563EB",
    subbar_active_fg="#FFFFFF",
    subbar_active_border="#3B82F6",
    subbar_delete_fg="#F87171",
    method_badge_bg="#1E2636",
    method_badge_fg="#FBBF24",
    method_badge_border="#334155",
    seq_header_bg="#18202C",
    seq_header_fg="#E2E8F0",
    overlay_card_bg="#151C28",
    overlay_card_border="#263040",
    toggle_on_bg="#3898EC",
    toggle_off_bg="#222630",
    toggle_knob_on="#FFFFFF",
    toggle_knob_off="#94A3B8",
    tab_active_bg="#0E4149",
    tab_active_fg="#38BDF8",
    tab_inactive_bg="#161C27",
    tab_inactive_fg="#8B949E",
    trace_glow="#1E3A5F",
    trace_under_fill="#162A42",
    rt_window_band_fill="#152232",
    event_on_pill_bg="#132E28",
    event_on_pill_border="#10B981",
    event_off_pill_bg="#311B22",
    event_off_pill_border="#EF4444",
)
