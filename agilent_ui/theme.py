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
)


DARK_PALETTE = ThemePalette(
    name="dark",
    bg_app="#1E1E1E",
    bg_frame="#252526",
    fg_app="#CCCCCC",
    topbar_bg="#181818",
    topbar_fg="#E0E0E0",
    topbar_btn_bg="#2D2D30",
    topbar_btn_fg="#FFFFFF",
    subbar_bg="#252526",
    subbar_fg="#D4D4D4",
    subbar_btn_bg="#333333",
    subbar_btn_fg="#FFFFFF",
    canvas_bg="#181818",
    panel_bg="#121212",
    panel_border="#3E3E42",
    grid_line="#252526",
    axis_tick="#858585",
    axis_text="#CCCCCC",
    panel_title="#569CD6",
    axis_title="#CCCCCC",
    trace_fid="#389BFF",
    trace_tcd="#4EC9B0",
    baseline_normal="#E0E0E0",
    baseline_negative="#D16DFF",
    baseline_selected="#FF7B54",
    peak_drop_line="#888888",
    anchor_fill="#252526",
    anchor_outline="#E0E0E0",
    anchor_selected="#FFD700",
    apex_marker="#FF70C6",
    label_compound="#79B8FF",
    label_unnamed="#AAAAAA",
    label_selected="#FF9E66",
    leader_line="#666666",
    rt_window_line="#1A4B75",
    rt_window_hi_fill="#152B42",
    rt_window_hi_line="#4FC1FF",
    shaded_pos_fill="#152B42",
    shaded_neg_fill="#40241A",
    timed_event_on="#4EC9B0",
    timed_event_off="#F14C4C",
    timed_event_bl="#C586C0",
    zoom_box_line="#4FC1FF",
    tree_bg="#1E1E1E",
    tree_fg="#D4D4D4",
    tree_header_bg="#2D2D30",
    tree_header_fg="#E0E0E0",
    tree_selected_bg="#094771",
    tree_selected_fg="#FFFFFF",
    tag_identified_bg="#152B42",
    tag_identified_fg="#D4D4D4",
    tag_negative_bg="#3D2618",
    tag_negative_fg="#D4D4D4",
    tag_unidentified_fg="#888888",
    tag_found_bg="#1E3626",
    tag_missing_fg="#666666",
    status_bg="#007ACC",
    status_fg="#FFFFFF",
)
