"""
Main Desktop Window for OpenChromLab — Chromatography Data System.
Built for educational & research GC workflows (FID1A + TCD2B).
"""

import copy
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Tuple

from agilent_core.ch_reader import (
    InjectionData,
    IntegratedPeak,
    find_d_folders,
    load_d_folder,
)
from agilent_core.exporter import (
    _lookup_compound_peak,
    export_sequence_single_sheet_xlsx,
)
from agilent_core.integrator import (
    MANUAL_OVERRIDES_FILENAME,
    add_manual_peak,
    delete_peak_by_id,
    process_injection,
    save_manual_overrides,
    split_peak_at,
    toggle_peak_negative,
    update_peak_anchors,
)
from agilent_core.method_model import (
    CompoundDef,
    ProcessingMethod,
    TimedEvent,
    ZoomPresetDef,
    build_default_mpz_method,
    load_pmx_method,
)
from agilent_ui.theme import ThemePalette, LIGHT_PALETTE, DARK_PALETTE
from agilent_ui.method_editor import MethodEditorDialog
from .chrom_canvas import DualChromatogramCanvas, HitType


class InjectionUndoManager:
    """Per-injection undo history manager using deepcopy snapshots of peaks_by_signal."""

    def __init__(self, max_depth: int = 50) -> None:
        self.max_depth = max_depth
        self.history: List[Tuple[str, Dict[str, List[IntegratedPeak]]]] = []

    def push_state(self, description: str, peaks_by_signal: Dict[str, List[IntegratedPeak]]) -> None:
        snapshot = copy.deepcopy(peaks_by_signal)
        self.history.append((description, snapshot))
        if len(self.history) > self.max_depth:
            self.history.pop(0)

    def undo(self) -> Optional[Tuple[str, Dict[str, List[IntegratedPeak]]]]:
        if not self.history:
            return None
        return self.history.pop()


class OpenChromLabApp(tk.Tk):
    """Main Desktop Application Window for OpenChromLab."""

    def __init__(self, initial_workspace: str) -> None:
        super().__init__()
        self.title("OpenChromLab — Chromatography Data System")

        # Responsive sizing: fit standard 1080p @ 125% DPI displays (1536x864) without pushing status bar off-screen
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(1380, max(1024, int(sw * 0.92))) if sw > 600 else 1380
        h = min(780, max(600, int(sh * 0.85))) if sh > 500 else 780
        if sw > w and sh > h:
            pos_x = (sw - w) // 2
            pos_y = max(0, (sh - h - 40) // 2)
            self.geometry(f"{w}x{h}+{pos_x}+{pos_y}")
        else:
            self.geometry(f"{w}x{h}")
        self.minsize(1024, 600)
        self.configure(bg="#F0F2F5")

        self.workspace_dir = os.path.abspath(initial_workspace)

        # Application Icon (F30)
        ico_path = os.path.join(self.workspace_dir, "OpenChromLab.ico")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        # Theme & Channel Selection Attributes (F20, F23)
        self.current_theme_name: str = "light"
        self.theme: ThemePalette = LIGHT_PALETTE
        self.channel_view_var = tk.StringVar(value="both")

        # Undo Managers per injection (F28)
        self.undo_managers: Dict[str, InjectionUndoManager] = {}

        self.method: ProcessingMethod = build_default_mpz_method()
        self.injections: List[InjectionData] = []
        self.current_injection: Optional[InjectionData] = None

        self._setup_styles()
        self._build_menu()
        self._build_top_toolbar()
        self._build_main_panes()
        self._build_status_bar()

        # Wire canvas context menu callback (F27)
        self.chrom_canvas.on_context_menu_callback = self._show_chromatogram_context_menu
        self.chrom_canvas.canvas.bind("<<CanvasContextMenu>>", self._on_canvas_context_virtual_event)

        # Keyboard shortcuts (F28)
        self.bind("<Delete>", lambda e: self._delete_selected_peak())
        self.bind("<Control-e>", lambda e: self._export_excel_dialog())
        self.bind("<Control-s>", lambda e: self._save_current_manual_overrides())
        self.bind("<Control-z>", self._on_undo_triggered)
        self.bind("<Control-Z>", self._on_undo_triggered)
        self.bind("<Escape>", self._on_escape_triggered)

        # Automatically load any .D folders in the workspace directory
        self.after(80, lambda: self.load_directory(self.workspace_dir))

    # ------------------------------------------------------------------
    # Styling & Layout Construction
    # ------------------------------------------------------------------

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        # Dynamically compute rowheight for crisp text rendering on high-DPI displays
        try:
            import tkinter.font as tkfont
            base_font = tkfont.Font(font=("Segoe UI", 9))
            f_height = base_font.metrics("linespace")
            row_height = max(26, f_height + 8)
        except Exception:
            row_height = 26

        style.configure("Treeview", font=("Segoe UI", 9), rowheight=row_height)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=(10, 4))
        style.configure("Toolbar.TButton", font=("Segoe UI", 9), padding=(6, 3))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), padding=(8, 4))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .D Folder or Sequence Directory...", command=self._open_folder_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="New Method (From Scratch)...", command=self._open_new_method_dialog)
        file_menu.add_command(label="Method Editor / Edit Method...", command=self._open_method_editor_dialog)
        file_menu.add_command(label="Import Method (.pmx or .json)...", command=self._import_method_dialog)
        file_menu.add_command(label="Save Method as .json...", command=self._save_method_dialog)
        file_menu.add_separator()
        file_menu.add_command(
            label="Export All Injections to Single-Sheet Excel (.xlsx)...   Ctrl+E",
            command=self._export_excel_dialog,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        int_menu = tk.Menu(menubar, tearoff=0)
        int_menu.add_command(label="Auto-Integrate Current Injection (12-Tone Engine)", command=self._reprocess_current_auto)
        int_menu.add_command(label="Reload OpenLab .rx Ground Truth (Current Injection)", command=self._reprocess_current_rx)
        int_menu.add_separator()
        int_menu.add_command(label="Reprocess Entire Sequence (Auto Integrator)", command=lambda: self._reprocess_all(prefer_rx=False))
        int_menu.add_command(label="Reprocess Entire Sequence (Prefer .rx + Manual)", command=lambda: self._reprocess_all(prefer_rx=True))
        int_menu.add_separator()
        int_menu.add_command(label="Save Manual Overrides for Current Injection   Ctrl+S", command=self._save_current_manual_overrides)
        int_menu.add_command(label="Clear Saved Manual Overrides for Current Injection", command=self._clear_current_manual_overrides)
        menubar.add_cascade(label="Integration", menu=int_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        chan_menu = tk.Menu(view_menu, tearoff=0)
        chan_menu.add_radiobutton(label="Both", variable=self.channel_view_var, value="both", command=self._on_channel_view_changed)
        chan_menu.add_radiobutton(label="FID Only", variable=self.channel_view_var, value="FID1A", command=self._on_channel_view_changed)
        chan_menu.add_radiobutton(label="TCD Only", variable=self.channel_view_var, value="TCD2B", command=self._on_channel_view_changed)
        view_menu.add_cascade(label="Channel View", menu=chan_menu)
        view_menu.add_separator()
        view_menu.add_command(label="Toggle Dark/Light Theme", command=self._toggle_theme)
        view_menu.add_command(label="Save Current Zoom View as Preset...", command=self._save_custom_zoom_preset)
        view_menu.add_separator()
        view_menu.add_command(label="Zoom Reaction Window (3.5 - 16.5 min)", command=lambda: self.chrom_canvas.zoom_active_region())
        view_menu.add_command(label="Zoom Full Run (0 - 40 min)", command=lambda: self.chrom_canvas.zoom_full_range())
        view_menu.add_command(label="Auto-Scale Visible Y Axes", command=lambda: self.chrom_canvas.autoscale_visible_y())
        menubar.add_cascade(label="View", menu=view_menu)

        self.config(menu=menubar)

    def _build_top_toolbar(self) -> None:
        bar = tk.Frame(self, bg="#1F3864", pady=5, padx=8)
        bar.pack(side=tk.TOP, fill=tk.X)

        # App Title & Method Badge (F19)
        tk.Label(
            bar,
            text="OpenChromLab",
            font=("Segoe UI", 11, "bold"),
            fg="#FFFFFF",
            bg="#1F3864",
        ).pack(side=tk.LEFT, padx=(2, 10))

        self.lbl_method_badge = tk.Label(
            bar,
            text=f"Method: {self.method.name}",
            font=("Segoe UI", 9, "bold"),
            fg="#FFD700",
            bg="#2B4C7E",
            padx=8,
            pady=2,
        )
        self.lbl_method_badge.pack(side=tk.LEFT, padx=4)

        tk.Button(
            bar,
            text="📂 Open .D / Sequence",
            command=self._open_folder_dialog,
            font=("Segoe UI", 9, "bold"),
            bg="#FFFFFF",
            fg="#1F3864",
            relief=tk.FLAT,
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            bar,
            text="⚙ Method Editor",
            command=self._open_method_editor_dialog,
            font=("Segoe UI", 9),
            bg="#E8EEF5",
            fg="#1F3864",
            relief=tk.FLAT,
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            bar,
            text="⚙ Import .pmx/.json",
            command=self._import_method_dialog,
            font=("Segoe UI", 9),
            bg="#E8EEF5",
            fg="#1F3864",
            relief=tk.FLAT,
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=4)

        # Theme Toggle Button (F23)
        self.btn_theme_toggle = tk.Button(
            bar,
            text="🌙 Dark Mode",
            command=self._toggle_theme,
            font=("Segoe UI", 9, "bold"),
            bg="#2B4C7E",
            fg="#FFFFFF",
            relief=tk.FLAT,
            padx=8,
            pady=2,
        )
        self.btn_theme_toggle.pack(side=tk.RIGHT, padx=4)

        # Right side: Single-Sheet Excel Export & Copy buttons
        tk.Button(
            bar,
            text="📊 Export Single-Sheet Excel (.xlsx)",
            command=self._export_excel_dialog,
            font=("Segoe UI", 9, "bold"),
            bg="#107C41",
            fg="#FFFFFF",
            activebackground="#0B5C2E",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=10,
            pady=3,
        ).pack(side=tk.RIGHT, padx=4)

        tk.Button(
            bar,
            text="📋 Copy Matrix",
            command=self._copy_matrix_to_clipboard,
            font=("Segoe UI", 9),
            bg="#2B4C7E",
            fg="#FFFFFF",
            relief=tk.FLAT,
            padx=8,
            pady=3,
        ).pack(side=tk.RIGHT, padx=4)

        # Second row toolbar: Channel View + Manual Tools + Zoom Presets
        subbar = tk.Frame(self, bg="#E9EDF4", pady=4, padx=8, bd=1, relief=tk.SOLID)
        subbar.pack(side=tk.TOP, fill=tk.X)

        # Channel Display Selection (F20)
        tk.Label(
            subbar,
            text="Channel View:",
            font=("Segoe UI", 9, "bold"),
            bg="#E9EDF4",
            fg="#1F3864",
        ).pack(side=tk.LEFT, padx=(0, 4))

        for c_label, c_val in [("Both", "both"), ("FID Only", "FID1A"), ("TCD Only", "TCD2B")]:
            rb = tk.Radiobutton(
                subbar,
                text=c_label,
                variable=self.channel_view_var,
                value=c_val,
                command=self._on_channel_view_changed,
                indicatoron=False,
                font=("Segoe UI", 9),
                bg="#FFFFFF",
                fg="#1F3864",
                selectcolor="#CCE4F7",
                padx=5,
                pady=2,
                bd=1,
                relief=tk.RAISED,
            )
            rb.pack(side=tk.LEFT, padx=1)

        ttk.Separator(subbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        tk.Label(
            subbar,
            text="Manual Tools:",
            font=("Segoe UI", 9, "bold"),
            bg="#E9EDF4",
            fg="#1F3864",
        ).pack(side=tk.LEFT, padx=(0, 4))

        self.tool_var = tk.StringVar(value="pan_zoom")
        tools = [
            ("🖱 Select / Pan", "pan_zoom"),
            ("⚓ Anchors", "drag_anchor"),
            ("✏ Draw (+/-)", "draw_peak"),
            ("✂ Split", "split_peak"),
        ]
        for text, mode in tools:
            rb = tk.Radiobutton(
                subbar,
                text=text,
                variable=self.tool_var,
                value=mode,
                command=lambda m=mode: self.chrom_canvas.set_tool_mode(m),
                indicatoron=False,
                font=("Segoe UI", 9),
                bg="#FFFFFF",
                fg="#1F3864",
                selectcolor="#CCE4F7",
                padx=5,
                pady=2,
                bd=1,
                relief=tk.RAISED,
            )
            rb.pack(side=tk.LEFT, padx=1)

        tk.Button(
            subbar,
            text="⇅ Invert (+/-)",
            command=self._toggle_selected_peak_polarity,
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#5C2D91",
            padx=4,
            pady=1,
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            subbar,
            text="🗑 Delete",
            command=self._delete_selected_peak,
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#A4262C",
            padx=4,
            pady=1,
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            subbar,
            text="⚡ Auto",
            command=self._reprocess_current_auto,
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#004578",
            padx=4,
            pady=1,
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            subbar,
            text="↺ .rx",
            command=self._reprocess_current_rx,
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#333333",
            padx=4,
            pady=1,
        ).pack(side=tk.LEFT, padx=2)

        # Quick Zoom Region Presets on right side using compact ttk.Combobox (F26)
        zoom_frame = tk.Frame(subbar, bg="#E9EDF4")
        zoom_frame.pack(side=tk.RIGHT, padx=2)

        tk.Label(
            zoom_frame,
            text="Zoom Preset:",
            font=("Segoe UI", 9, "bold"),
            bg="#E9EDF4",
            fg="#1F3864",
        ).pack(side=tk.LEFT, padx=(2, 4))

        tk.Button(
            zoom_frame,
            text="📷 Save Preset...",
            command=self._save_custom_zoom_preset,
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#1F3864",
            padx=5,
            pady=1,
            relief=tk.RAISED,
        ).pack(side=tk.LEFT, padx=2)

        self.zoom_presets: Dict[str, Any] = {}
        self.zoom_combo = ttk.Combobox(
            zoom_frame,
            values=[],
            state="readonly",
            width=22,
            font=("Segoe UI", 9),
        )
        self.zoom_combo.pack(side=tk.LEFT, padx=2)
        self.zoom_combo.bind("<<ComboboxSelected>>", self._on_zoom_preset_selected)

        tk.Button(
            zoom_frame,
            text="Auto-Y",
            command=lambda: self.chrom_canvas.autoscale_visible_y(),
            font=("Segoe UI", 9, "bold"),
            bg="#FFFFFF",
            fg="#1F3864",
            padx=5,
            pady=1,
            relief=tk.RAISED,
        ).pack(side=tk.LEFT, padx=2)

        self._refresh_zoom_presets()
        if "Reaction (3.5–16.5m)" in self.zoom_combo["values"]:
            self.zoom_combo.set("Reaction (3.5–16.5m)")

    def _build_main_panes(self) -> None:
        outer_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer_paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # 1. Left Sidebar: Sequence / Injections Tree + Overlay Toggles
        left_frame = ttk.Frame(outer_paned, width=310)
        outer_paned.add(left_frame, weight=0)

        lbl_seq = tk.Label(
            left_frame,
            text="Sequence Injections (.D)",
            font=("Segoe UI", 9, "bold"),
            bg="#D9E1F2",
            fg="#1F3864",
            anchor="w",
            padx=6,
            pady=4,
        )
        lbl_seq.pack(fill=tk.X)

        tree_container = ttk.Frame(left_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, pady=(2, 4))

        self.inj_tree = ttk.Treeview(
            tree_container,
            columns=("inj_num", "sample", "mode"),
            show="headings",
            selectmode="browse",
        )
        self.inj_tree.heading("inj_num", text="#")
        self.inj_tree.heading("sample", text="Injection / Sample")
        self.inj_tree.heading("mode", text="Mode")
        self.inj_tree.column("inj_num", width=38, anchor="center", stretch=False)
        self.inj_tree.column("sample", width=215, anchor="w", stretch=True)
        self.inj_tree.column("mode", width=54, anchor="center", stretch=False)

        inj_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.inj_tree.yview)
        self.inj_tree.configure(yscrollcommand=inj_scroll.set)
        self.inj_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inj_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.inj_tree.bind("<<TreeviewSelect>>", self._on_injection_selected)

        # Display Overlay Checkboxes inside Left Panel
        right_paned = ttk.PanedWindow(outer_paned, orient=tk.VERTICAL)
        outer_paned.add(right_paned, weight=1)

        # 2. Top-Right: Dual Stacked Chromatogram Viewer
        chrom_frame = ttk.Frame(right_paned)
        right_paned.add(chrom_frame, weight=3)

        self.chrom_canvas = DualChromatogramCanvas(
            chrom_frame,
            on_peak_selected=self._on_canvas_peak_selected,
            on_peaks_modified=self._on_canvas_peaks_modified,
        )
        self.chrom_canvas.pack(fill=tk.BOTH, expand=True)

        # Add display checkboxes in left panel now that chrom_canvas exists
        ov_frame = ttk.LabelFrame(left_frame, text="Plot Overlays & Options", padding=6)
        ov_frame.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(
            ov_frame,
            text="Show Compound Names & RTs",
            variable=self.chrom_canvas.show_compound_labels,
            command=self.chrom_canvas.redraw,
        ).pack(anchor="w")
        ttk.Checkbutton(
            ov_frame,
            text="Show RT Identification Windows",
            variable=self.chrom_canvas.show_rt_windows,
            command=self.chrom_canvas.redraw,
        ).pack(anchor="w")
        ttk.Checkbutton(
            ov_frame,
            text="Show Timed Integration Events",
            variable=self.chrom_canvas.show_timed_events,
            command=self.chrom_canvas.redraw,
        ).pack(anchor="w")
        ttk.Checkbutton(
            ov_frame,
            text="Show Baselines & Anchors",
            variable=self.chrom_canvas.show_baselines,
            command=self.chrom_canvas.redraw,
        ).pack(anchor="w")
        ttk.Checkbutton(
            ov_frame,
            text="Snap Dragged Anchors to Curve",
            variable=self.chrom_canvas.snap_anchors_to_trace,
        ).pack(anchor="w")

        # 3. Bottom-Right: Notebook with 4 Tabs
        bottom_frame = ttk.Frame(right_paned)
        right_paned.add(bottom_frame, weight=2)

        self.notebook = ttk.Notebook(bottom_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_tab_injection_peaks()
        self._build_tab_compound_table()
        self._build_tab_timed_events()
        self._build_tab_matrix_preview()

    def _build_tab_injection_peaks(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  1. Injection Peaks (FID1A + TCD2B)  ")

        cols = (
            "idx",
            "name",
            "signal",
            "rt",
            "area",
            "area_pct",
            "height",
            "height_pct",
            "begin",
            "end",
            "code",
        )
        self.peak_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        headers = [
            ("idx", "#", 42, "center"),
            ("name", "Name (Compound)", 150, "w"),
            ("signal", "Signal description", 165, "w"),
            ("rt", "RT (min)", 85, "e"),
            ("area", "Area", 105, "e"),
            ("area_pct", "Area%", 80, "e"),
            ("height", "Height", 95, "e"),
            ("height_pct", "Height%", 80, "e"),
            ("begin", "Begin (min)", 85, "e"),
            ("end", "End (min)", 85, "e"),
            ("code", "Type", 65, "center"),
        ]
        for cid, text, w, anc in headers:
            self.peak_tree.heading(cid, text=text)
            self.peak_tree.column(cid, width=w, anchor=anc)

        scroll_y = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.peak_tree.yview)
        scroll_x = ttk.Scrollbar(tab, orient=tk.HORIZONTAL, command=self.peak_tree.xview)
        self.peak_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.peak_tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)

        self.peak_tree.tag_configure("identified", background="#F2F8FF", font=("Segoe UI", 9, "bold"))
        self.peak_tree.tag_configure("negative", background="#FFF4EA", font=("Segoe UI", 9, "bold"))
        self.peak_tree.tag_configure("unidentified", foreground="#555555")

        self.peak_tree.bind("<<TreeviewSelect>>", self._on_peak_table_select)
        self.peak_tree.bind("<Double-1>", self._on_peak_table_double_click)

    def _build_tab_compound_table(self) -> None:
        """
        Replicates the exact Compound Table from the user's MPZ_method-2.2 screenshot:
        #, Name, Signal, Exp. RT (min), Absolute RT window (min), Relative RT window (%),
        RT update, RT update factor (%), Peak match, plus live Matched RT & Area in current injection.
        """
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  2. Method Compound Table (16 Compounds)  ")

        btn_bar = tk.Frame(tab, bg="#F0F2F5", pady=3)
        btn_bar.pack(side=tk.TOP, fill=tk.X, padx=6)

        tk.Label(
            btn_bar,
            text="Method Compounds (16) — Double-click to edit, click to highlight on plot:",
            font=("Segoe UI", 9, "bold"),
            bg="#F0F2F5",
            fg="#1F3864",
        ).pack(side=tk.LEFT)

        ttk.Button(btn_bar, text="🛠 Open Method Editor...", command=self._open_method_editor_dialog).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="💾 Save Method (.json)", command=self._save_method_dialog).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="➖ Remove", command=self._remove_selected_compound).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="➕ Add", command=self._add_compound_dialog).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="✏ Edit Compound", command=self._edit_selected_compound_dialog).pack(side=tk.RIGHT, padx=3)

        cols = (
            "idx",
            "name",
            "signal",
            "exp_rt",
            "abs_win",
            "rel_win",
            "rt_update",
            "rt_factor",
            "match_mode",
            "eff_window",
            "cur_rt",
            "cur_area",
        )
        comp_container = ttk.Frame(tab)
        comp_container.pack(fill=tk.BOTH, expand=True)

        self.comp_tree = ttk.Treeview(comp_container, columns=cols, show="headings", selectmode="browse")
        headers = [
            ("idx", "#", 38, "center"),
            ("name", "Name", 130, "w"),
            ("signal", "Signal", 68, "center"),
            ("exp_rt", "Exp. RT (min) ▲", 105, "e"),
            ("abs_win", "Absolute RT window (min)", 150, "e"),
            ("rel_win", "Relative RT window (%)", 140, "e"),
            ("rt_update", "RT update", 75, "center"),
            ("rt_factor", "RT update factor (%)", 120, "e"),
            ("match_mode", "Peak match", 85, "center"),
            ("eff_window", "Active Window [min]", 135, "center"),
            ("cur_rt", "Found RT (min)", 95, "e"),
            ("cur_area", "Found Area", 100, "e"),
        ]
        for cid, text, w, anc in headers:
            self.comp_tree.heading(cid, text=text)
            self.comp_tree.column(cid, width=w, anchor=anc)

        scroll_y = ttk.Scrollbar(comp_container, orient=tk.VERTICAL, command=self.comp_tree.yview)
        scroll_x = ttk.Scrollbar(comp_container, orient=tk.HORIZONTAL, command=self.comp_tree.xview)
        self.comp_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.comp_tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        comp_container.rowconfigure(0, weight=1)
        comp_container.columnconfigure(0, weight=1)

        self.comp_tree.tag_configure("found", background="#F2F9F4")
        self.comp_tree.tag_configure("missing", foreground="#888888")

        self.comp_tree.bind("<<TreeviewSelect>>", self._on_compound_table_select)
        self.comp_tree.bind("<Double-1>", lambda e: self._edit_selected_compound_dialog())

    def _build_tab_timed_events(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  3. Integration Events ChemStation (FID1A & TCD2B)  ")

        paned = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        self.event_trees: Dict[str, ttk.Treeview] = {}
        self.param_vars: Dict[str, Dict[str, tk.StringVar]] = {}

        for sname in ("FID1A", "TCD2B"):
            frame = ttk.LabelFrame(paned, text=f"{sname} — Initial Parameters & Timed Integration Events", padding=6)
            paned.add(frame, weight=1)

            p_row = ttk.Frame(frame)
            p_row.pack(fill=tk.X, pady=(0, 4))
            self.param_vars[sname] = {}
            for p_key, p_lbl in (
                ("slope_sensitivity", "Slope:"),
                ("peak_width", "Width:"),
                ("area_reject", "Area:"),
                ("height_reject", "Height:"),
            ):
                ttk.Label(p_row, text=p_lbl).pack(side=tk.LEFT, padx=(3, 1))
                sv = tk.StringVar(value="1.0")
                self.param_vars[sname][p_key] = sv
                ttk.Entry(p_row, textvariable=sv, width=5).pack(side=tk.LEFT, padx=(0, 4))

            ttk.Button(
                p_row,
                text="Apply & Re-Integrate",
                command=lambda s=sname: self._apply_signal_params(s),
            ).pack(side=tk.RIGHT, padx=4)

            tree_box = ttk.Frame(frame)
            tree_box.pack(fill=tk.BOTH, expand=True)

            tree = ttk.Treeview(
                tree_box,
                columns=("time", "event", "value", "enabled"),
                show="headings",
                height=7,
            )
            tree.heading("time", text="Time (min)")
            tree.heading("event", text="Integration Event")
            tree.heading("value", text="Value")
            tree.heading("enabled", text="Enabled")
            tree.column("time", width=85, anchor="e")
            tree.column("event", width=140, anchor="w")
            tree.column("value", width=80, anchor="center")
            tree.column("enabled", width=65, anchor="center")

            ev_scroll_y = ttk.Scrollbar(tree_box, orient=tk.VERTICAL, command=tree.yview)
            ev_scroll_x = ttk.Scrollbar(tree_box, orient=tk.HORIZONTAL, command=tree.xview)
            tree.configure(yscrollcommand=ev_scroll_y.set, xscrollcommand=ev_scroll_x.set)

            tree.grid(row=0, column=0, sticky="nsew")
            ev_scroll_y.grid(row=0, column=1, sticky="ns")
            ev_scroll_x.grid(row=1, column=0, sticky="ew")
            tree_box.rowconfigure(0, weight=1)
            tree_box.columnconfigure(0, weight=1)

            self.event_trees[sname] = tree

            tree.bind("<Double-1>", lambda e, s=sname: self._edit_selected_timed_event(s))
            tree.bind("<Delete>", lambda e, s=sname: self._delete_timed_event(s))

            btn_row = ttk.Frame(frame)
            btn_row.pack(fill=tk.X, pady=(4, 0))
            ttk.Button(
                btn_row,
                text="➕ Add Timed Event",
                command=lambda s=sname: self._open_timed_event_editor(s, None),
            ).pack(side=tk.LEFT, padx=2)
            ttk.Button(
                btn_row,
                text="✏ Edit Selected Event",
                command=lambda s=sname: self._edit_selected_timed_event(s),
            ).pack(side=tk.LEFT, padx=2)
            ttk.Button(
                btn_row,
                text="➖ Delete Selected Event",
                command=lambda s=sname: self._delete_timed_event(s),
            ).pack(side=tk.LEFT, padx=2)

    def _build_tab_matrix_preview(self) -> None:
        """
        Live preview of Point 2.4: Single-Sheet Matrix where Columns = Injections
        and Rows = Specific Compounds.
        """
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  4. Single-Sheet Matrix Preview (Rows=Compounds, Cols=Injections)  ")

        top_bar = tk.Frame(tab, bg="#F0F2F5", pady=4)
        top_bar.pack(side=tk.TOP, fill=tk.X, padx=6)

        tk.Label(
            top_bar,
            text="Live Preview of Single-Sheet Export (Rows = 16 Method Compounds | Columns = All Loaded Injections):",
            font=("Segoe UI", 9, "bold"),
            bg="#F0F2F5",
            fg="#1F3864",
        ).pack(side=tk.LEFT)

        self.preview_metric_var = tk.StringVar(value="area")
        for lbl, val in (("Area", "area"), ("Area %", "area_pct"), ("Height", "height"), ("RT (min)", "rt")):
            ttk.Radiobutton(
                top_bar,
                text=lbl,
                variable=self.preview_metric_var,
                value=val,
                command=self._refresh_matrix_preview,
            ).pack(side=tk.LEFT, padx=6)

        ttk.Button(
            top_bar,
            text="📊 Export Single-Sheet .xlsx...",
            command=self._export_excel_dialog,
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            top_bar,
            text="📋 Copy Table (Paste Directly into Excel)",
            command=self._copy_matrix_to_clipboard,
        ).pack(side=tk.RIGHT, padx=4)

        container = ttk.Frame(tab)
        container.pack(fill=tk.BOTH, expand=True)

        self.matrix_tree = ttk.Treeview(container, show="headings", selectmode="browse")
        scroll_y = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.matrix_tree.yview)
        scroll_x = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=self.matrix_tree.xview)
        self.matrix_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.matrix_tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

    def _build_status_bar(self) -> None:
        self.status_var = tk.StringVar(
            value="Ready. Scroll wheel = Zoom X | Shift+Scroll = Zoom Y | Click peak anchor to drag baseline."
        )
        self.status_bar_lbl = tk.Label(
            self,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            bg="#1F3864",
            fg="#FFFFFF",
            anchor="w",
            padx=10,
            pady=3,
        )
        self.status_bar_lbl.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # Data Loading & Processing
    # ------------------------------------------------------------------

    def load_directory(self, folder_path: str) -> None:
        d_paths = find_d_folders(folder_path)
        if not d_paths:
            self.status_var.set(f"No Agilent .D folders found in {folder_path}")
            return

        loaded_injections: List[InjectionData] = []
        failed_injections: List[Tuple[str, str]] = []
        loaded_pmx = False
        total = len(d_paths)

        for idx, dp in enumerate(d_paths, start=1):
            name = os.path.basename(dp)
            self.status_var.set(f"Loading injection ({idx}/{total}): {name}...")
            self.update_idletasks()
            try:
                inj = load_d_folder(dp)
                if not inj.signals:
                    raise ValueError(f"No valid chromatogram signals found in '{name}'.")
                if not loaded_pmx and inj.pmx_path and os.path.exists(inj.pmx_path):
                    try:
                        self.method = load_pmx_method(inj.pmx_path)
                        self.lbl_method_badge.configure(text=f"Method: {self.method.name}")
                        loaded_pmx = True
                    except Exception:
                        pass
                process_injection(inj, self.method, prefer_rx=True, prefer_manual=True)
                loaded_injections.append(inj)
            except Exception as exc:
                failed_injections.append((name, str(exc)))

        self.injections = loaded_injections
        self._populate_injection_tree()
        self._refresh_zoom_presets()
        self._refresh_method_tabs()
        self._refresh_matrix_preview()

        if self.injections:
            first_iid = self.inj_tree.get_children()[0]
            self.inj_tree.selection_set(first_iid)
            self._select_injection_by_index(0, reset_view=True)

        msg = f"Loaded {len(self.injections)}/{total} injection(s) from '{os.path.basename(folder_path)}' using method '{self.method.name}'."
        if failed_injections:
            msg += f" (Warning: {len(failed_injections)} skipped due to error: {failed_injections[0][0]})"
        self.status_var.set(msg)

    def _populate_injection_tree(self) -> None:
        self.inj_tree.delete(*self.inj_tree.get_children())
        for idx, inj in enumerate(self.injections):
            src_badge = {
                "manual": "Manual*",
                "rx": "OpenLab",
                "auto": "Auto",
            }.get(inj.integration_source, inj.integration_source)
            self.inj_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(inj.injection_number, inj.sample_name or inj.short_label, src_badge),
            )

    def _select_injection_by_index(self, idx: int, reset_view: bool = False) -> None:
        if not (0 <= idx < len(self.injections)):
            return
        self.current_injection = self.injections[idx]
        self.chrom_canvas.set_data(self.current_injection, self.method, reset_view=reset_view)
        self._refresh_peak_table()
        self._refresh_compound_table()

    # ------------------------------------------------------------------
    # Table Refresh Methods
    # ------------------------------------------------------------------

    def _refresh_peak_table(self) -> None:
        self.peak_tree.delete(*self.peak_tree.get_children())
        if not self.current_injection:
            return

        row_num = 1
        for sname in ("FID1A", "TCD2B"):
            pks = self.current_injection.peaks_by_signal.get(sname, [])
            for pk in pks:
                if pk.is_negative:
                    tag = "negative"
                elif pk.compound_name:
                    tag = "identified"
                else:
                    tag = "unidentified"

                self.peak_tree.insert(
                    "",
                    tk.END,
                    iid=pk.peak_id,
                    values=(
                        row_num,
                        pk.compound_name,
                        pk.signal_description,
                        f"{pk.rt_min:.3f}",
                        f"{pk.area:.3f}",
                        f"{pk.area_pct:.2f}",
                        f"{pk.height:.3f}",
                        f"{pk.height_pct:.2f}",
                        f"{pk.begin_min:.3f}",
                        f"{pk.end_min:.3f}",
                        pk.baseline_code,
                    ),
                    tags=(tag,),
                )
                row_num += 1

    def _refresh_compound_table(self) -> None:
        self.comp_tree.delete(*self.comp_tree.get_children())
        for comp in self.method.compounds:
            w0, w1 = comp.window_range
            pk = _lookup_compound_peak(self.current_injection, comp) if self.current_injection else None
            cur_rt_str = f"{pk.rt_min:.3f}" if pk else "—"
            cur_area_str = f"{pk.area:.3f}" if pk else "0.000"
            tag = "found" if pk else "missing"

            self.comp_tree.insert(
                "",
                tk.END,
                iid=str(comp.index),
                values=(
                    comp.index,
                    comp.name,
                    comp.signal,
                    f"{comp.exp_rt_min:.3f}",
                    f"{comp.abs_window_min:.3f}",
                    f"{comp.rel_window_pct:.3f}",
                    comp.rt_update,
                    f"{comp.rt_update_factor_pct:.3f}",
                    comp.peak_match,
                    f"[{w0:.3f} – {w1:.3f}]",
                    cur_rt_str,
                    cur_area_str,
                ),
                tags=(tag,),
            )

    def _refresh_method_tabs(self) -> None:
        self._refresh_compound_table()
        for sname, tree in self.event_trees.items():
            tree.delete(*tree.get_children())
            cfg = self.method.signals.get(sname)
            if not cfg:
                continue
            pvars = self.param_vars.get(sname, {})
            if "slope_sensitivity" in pvars:
                pvars["slope_sensitivity"].set(f"{cfg.slope_sensitivity:g}")
                pvars["peak_width"].set(f"{cfg.peak_width:g}")
                pvars["area_reject"].set(f"{cfg.area_reject:g}")
                pvars["height_reject"].set(f"{cfg.height_reject:g}")

            for i, ev in enumerate(cfg.timed_events):
                tree.insert(
                    "",
                    tk.END,
                    iid=f"{sname}_{i}",
                    values=(f"{ev.time_min:.3f}", ev.event_type, ev.value, "Yes" if ev.enabled else "No"),
                )

    def _refresh_matrix_preview(self) -> None:
        self.matrix_tree.delete(*self.matrix_tree.get_children())
        inj_cols = [f"inj_{i}" for i in range(len(self.injections))]
        all_cols = ["idx", "compound", "signal", "exp_rt"] + inj_cols
        self.matrix_tree["columns"] = all_cols

        self.matrix_tree.heading("idx", text="#")
        self.matrix_tree.column("idx", width=40, anchor="center", stretch=False)
        self.matrix_tree.heading("compound", text="Compound (Row)")
        self.matrix_tree.column("compound", width=135, anchor="w", stretch=False)
        self.matrix_tree.heading("signal", text="Signal")
        self.matrix_tree.column("signal", width=68, anchor="center", stretch=False)
        self.matrix_tree.heading("exp_rt", text="Exp. RT")
        self.matrix_tree.column("exp_rt", width=75, anchor="e", stretch=False)

        for i, inj in enumerate(self.injections):
            cid = f"inj_{i}"
            hdr = inj.sample_name or inj.short_label
            self.matrix_tree.heading(cid, text=hdr)
            self.matrix_tree.column(cid, width=155, anchor="e", stretch=False)

        metric = self.preview_metric_var.get()
        for comp in self.method.compounds:
            row_vals = [comp.index, comp.name, comp.signal, f"{comp.exp_rt_min:.3f}"]
            for inj in self.injections:
                pk = _lookup_compound_peak(inj, comp)
                if pk is None:
                    row_vals.append("0.000" if metric != "rt" else "—")
                else:
                    if metric == "area":
                        row_vals.append(f"{pk.area:.3f}")
                    elif metric == "area_pct":
                        row_vals.append(f"{pk.area_pct:.2f}")
                    elif metric == "height":
                        row_vals.append(f"{pk.height:.3f}")
                    elif metric == "rt":
                        row_vals.append(f"{pk.rt_min:.3f}")
            self.matrix_tree.insert("", tk.END, values=row_vals)

    # ------------------------------------------------------------------
    # Callbacks & Interactive Handlers
    # ------------------------------------------------------------------

    def _on_injection_selected(self, event: tk.Event) -> None:
        sel = self.inj_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._select_injection_by_index(idx, reset_view=False)

    def _on_canvas_peak_selected(self, pk: Optional[IntegratedPeak]) -> None:
        if pk is None:
            return
        if pk.peak_id in self.peak_tree.get_children():
            self.peak_tree.selection_set(pk.peak_id)
            self.peak_tree.see(pk.peak_id)
        self.status_var.set(
            f"Selected Peak: {pk.compound_name or '(Unnamed)'} on {pk.signal_name} | "
            f"RT = {pk.rt_min:.3f} min [{pk.begin_min:.3f} – {pk.end_min:.3f} min] | "
            f"Area = {pk.area:.3f} ({pk.area_pct:.2f}%) | Height = {pk.height:.3f}"
        )

    def _on_canvas_peaks_modified(self, msg: str) -> None:
        if not self.current_injection:
            return
        save_manual_overrides(self.current_injection)
        self._populate_injection_tree()
        self._refresh_peak_table()
        self._refresh_compound_table()
        self._refresh_matrix_preview()
        self.status_var.set(f"{msg}  (Saved manual overrides to {MANUAL_OVERRIDES_FILENAME})")

    def _on_peak_table_select(self, event: tk.Event) -> None:
        sel = self.peak_tree.selection()
        if not sel:
            return
        pk_id = sel[0]
        self.chrom_canvas.select_peak(pk_id, zoom_to=False)

    def _on_peak_table_double_click(self, event: tk.Event) -> None:
        sel = self.peak_tree.selection()
        if not sel:
            return
        pk_id = sel[0]
        self.chrom_canvas.select_peak(pk_id, zoom_to=True)

    def _on_compound_table_select(self, event: tk.Event) -> None:
        sel = self.comp_tree.selection()
        if not sel:
            return
        c_idx = int(sel[0]) - 1
        if 0 <= c_idx < len(self.method.compounds):
            comp = self.method.compounds[c_idx]
            self.chrom_canvas.highlight_compound_window(comp, zoom_to=True)
            self.status_var.set(
                f"Compound #{comp.index}: {comp.name} ({comp.signal}) | "
                f"Exp. RT = {comp.exp_rt_min:.3f} min | Window = [{comp.window_range[0]:.3f}, {comp.window_range[1]:.3f}] min"
            )

    def _zoom_preset(
        self,
        t0: float,
        t1: float,
        fid_y: tuple,
        tcd_y: tuple,
    ) -> None:
        self.chrom_canvas.x_range = (t0, t1)
        self.chrom_canvas.y_ranges["FID1A"] = fid_y
        self.chrom_canvas.y_ranges["TCD2B"] = tcd_y
        self.chrom_canvas.redraw()

    def _on_zoom_preset_selected(self, event: Optional[tk.Event] = None) -> None:
        sel = self.zoom_combo.get()
        handler = self.zoom_presets.get(sel)
        if handler:
            handler()

    # ------------------------------------------------------------------
    # Manual Peak Actions & Reprocessing
    # ------------------------------------------------------------------

    def _toggle_selected_peak_polarity(self) -> None:
        if not self.current_injection or not self.chrom_canvas.selected_peak_id:
            return
        pk_id = self.chrom_canvas.selected_peak_id
        for sname, pks in self.current_injection.peaks_by_signal.items():
            if any(p.peak_id == pk_id for p in pks):
                sig = self.current_injection.signals[sname]
                self.current_injection.peaks_by_signal[sname] = toggle_peak_negative(
                    sig, pks, pk_id, self.method
                )
                self.current_injection.integration_source = "manual"
                self._on_canvas_peaks_modified(f"Inverted polarity for peak on {sname}")
                self.chrom_canvas.redraw()
                break

    def _delete_selected_peak(self) -> None:
        if not self.current_injection or not self.chrom_canvas.selected_peak_id:
            return
        pk_id = self.chrom_canvas.selected_peak_id
        for sname, pks in self.current_injection.peaks_by_signal.items():
            if any(p.peak_id == pk_id for p in pks):
                sig = self.current_injection.signals[sname]
                self.current_injection.peaks_by_signal[sname] = delete_peak_by_id(
                    sig, pks, pk_id, self.method
                )
                self.current_injection.integration_source = "manual"
                self.chrom_canvas.selected_peak_id = None
                self._on_canvas_peaks_modified(f"Deleted peak on {sname}")
                self.chrom_canvas.redraw()
                break

    def _reprocess_current_auto(self) -> None:
        if not self.current_injection:
            return
        process_injection(self.current_injection, self.method, prefer_rx=False, prefer_manual=False)
        self._populate_injection_tree()
        self.chrom_canvas.redraw()
        self._refresh_peak_table()
        self._refresh_compound_table()
        self._refresh_matrix_preview()
        self.status_var.set(f"Auto-integrated '{self.current_injection.sample_name}' using 12-Tone engine.")

    def _reprocess_current_rx(self) -> None:
        if not self.current_injection:
            return
        # Remove manual overrides file if user explicitly resets to .rx
        man_file = os.path.join(self.current_injection.folder_path, MANUAL_OVERRIDES_FILENAME)
        if os.path.exists(man_file):
            try:
                os.remove(man_file)
            except OSError:
                pass
        process_injection(self.current_injection, self.method, prefer_rx=True, prefer_manual=False)
        self._populate_injection_tree()
        self.chrom_canvas.redraw()
        self._refresh_peak_table()
        self._refresh_compound_table()
        self._refresh_matrix_preview()
        self.status_var.set(f"Reloaded OpenLab .rx integration for '{self.current_injection.sample_name}'.")

    def _reprocess_all(self, prefer_rx: bool = True) -> None:
        total = len(self.injections)
        failed_count = 0
        for idx, inj in enumerate(self.injections, start=1):
            sname = inj.sample_name or inj.short_label
            self.status_var.set(f"Reprocessing injection ({idx}/{total}): {sname}...")
            self.update_idletasks()
            try:
                process_injection(inj, self.method, prefer_rx=prefer_rx, prefer_manual=True)
            except Exception:
                failed_count += 1
        self._populate_injection_tree()
        self.chrom_canvas.redraw()
        self._refresh_peak_table()
        self._refresh_compound_table()
        self._refresh_matrix_preview()
        msg = f"Reprocessed {total - failed_count}/{total} injection(s)."
        if failed_count:
            msg += f" (Warning: {failed_count} failed)"
        self.status_var.set(msg)

    def _save_current_manual_overrides(self) -> None:
        if not self.current_injection:
            return
        out = save_manual_overrides(self.current_injection)
        self.status_var.set(f"Saved manual integration overrides to {out}")

    def _clear_current_manual_overrides(self) -> None:
        self._reprocess_current_rx()

    # ------------------------------------------------------------------
    # Method Editing Dialogs
    # ------------------------------------------------------------------

    def _edit_selected_compound_dialog(self) -> None:
        sel = self.comp_tree.selection()
        if not sel:
            messagebox.showinfo("Edit Compound", "Please select a compound row in the Compound Table first.")
            return
        c_idx = int(sel[0]) - 1
        if not (0 <= c_idx < len(self.method.compounds)):
            return
        comp = self.method.compounds[c_idx]
        self._open_compound_editor(comp, is_new=False)

    def _add_compound_dialog(self) -> None:
        new_comp = CompoundDef(
            index=len(self.method.compounds) + 1,
            name="New_Compound",
            signal="FID1A",
            exp_rt_min=5.000,
            abs_window_min=0.050,
            rel_window_pct=1.000,
        )
        self._open_compound_editor(new_comp, is_new=True)

    def _open_compound_editor(self, comp: CompoundDef, is_new: bool) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Add Compound" if is_new else f"Edit Compound #{comp.index} — {comp.name}")
        dlg.minsize(380, 320)
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.grab_set()

        # Center over parent window
        try:
            self.update_idletasks()
            pw = self.winfo_width()
            ph = self.winfo_height()
            px = self.winfo_rootx()
            py = self.winfo_rooty()
            dw, dh = 400, 340
            cx = max(0, px + (pw - dw) // 2)
            cy = max(0, py + (ph - dh) // 2)
            dlg.geometry(f"{dw}x{dh}+{cx}+{cy}")
        except Exception:
            dlg.geometry("400x340")

        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)

        v_name = tk.StringVar(value=comp.name)
        v_sig = tk.StringVar(value=comp.signal)
        v_rt = tk.StringVar(value=f"{comp.exp_rt_min:.3f}")
        v_abs = tk.StringVar(value=f"{comp.abs_window_min:.3f}")
        v_rel = tk.StringVar(value=f"{comp.rel_window_pct:.3f}")
        v_match = tk.StringVar(value=comp.peak_match)

        rows = [
            ("Compound Name:", ttk.Entry(frm, textvariable=v_name, width=24)),
            ("Signal Channel:", ttk.Combobox(frm, textvariable=v_sig, values=("FID1A", "TCD2B"), width=21, state="readonly")),
            ("Expected RT (min):", ttk.Entry(frm, textvariable=v_rt, width=24)),
            ("Absolute RT Window (min):", ttk.Entry(frm, textvariable=v_abs, width=24)),
            ("Relative RT Window (%):", ttk.Entry(frm, textvariable=v_rel, width=24)),
            ("Peak Match Mode:", ttk.Combobox(frm, textvariable=v_match, values=("Closest", "Largest"), width=21, state="readonly")),
        ]
        for r_idx, (lbl, widget) in enumerate(rows):
            ttk.Label(frm, text=lbl).grid(row=r_idx, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=r_idx, column=1, sticky="ew", pady=4)

        def on_save(event: Optional[tk.Event] = None) -> None:
            try:
                comp.name = v_name.get().strip() or "Unknown"
                comp.signal = v_sig.get().strip() or "FID1A"
                comp.exp_rt_min = float(v_rt.get())
                comp.abs_window_min = float(v_abs.get())
                comp.rel_window_pct = float(v_rel.get())
                comp.peak_match = v_match.get()
            except ValueError:
                messagebox.showerror("Invalid Number", "Please enter valid numeric values for RT and Windows.", parent=dlg)
                return

            if is_new:
                self.method.compounds.append(comp)
            self.method.compounds.sort(key=lambda c: c.exp_rt_min)
            for idx_c, c_item in enumerate(self.method.compounds, start=1):
                c_item.index = idx_c

            self._reprocess_all(prefer_rx=True)
            dlg.destroy()

        dlg.bind("<Return>", on_save)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        btn_f = ttk.Frame(frm)
        btn_f.grid(row=len(rows), column=0, columnspan=2, pady=(14, 0))
        ttk.Button(btn_f, text="Save & Apply", command=on_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=6)

    def _remove_selected_compound(self) -> None:
        sel = self.comp_tree.selection()
        if not sel:
            return
        c_idx = int(sel[0]) - 1
        if 0 <= c_idx < len(self.method.compounds):
            del self.method.compounds[c_idx]
            for idx_c, c_item in enumerate(self.method.compounds, start=1):
                c_item.index = idx_c
            self._reprocess_all(prefer_rx=True)

    def _apply_signal_params(self, sname: str) -> None:
        cfg = self.method.signals.get(sname)
        if not cfg:
            return
        pvars = self.param_vars.get(sname, {})
        try:
            cfg.slope_sensitivity = float(pvars["slope_sensitivity"].get())
            cfg.peak_width = float(pvars["peak_width"].get())
            cfg.area_reject = float(pvars["area_reject"].get())
            cfg.height_reject = float(pvars["height_reject"].get())
        except ValueError:
            messagebox.showerror("Invalid Parameter", "Integration parameters must be numeric.")
            return
        self._reprocess_current_auto()

    def _open_timed_event_editor(self, sname: str, event_idx: Optional[int] = None) -> None:
        cfg = self.method.signals.get(sname)
        if not cfg:
            return
        is_new = (event_idx is None or event_idx >= len(cfg.timed_events))
        curr_ev = TimedEvent(time_min=1.0, event_type="IntegrationOn", value="", enabled=True) if is_new else cfg.timed_events[event_idx]

        dlg = tk.Toplevel(self)
        dlg.title(f"{'Add' if is_new else 'Edit'} Timed Integration Event — {sname}")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.configure(padx=16, pady=12)

        time_var = tk.StringVar(value=f"{curr_ev.time_min:.3f}")
        event_types = [
            "IntegrationOn", "IntegrationOff", "BaselineNow",
            "NegativePeakOn", "NegativePeakOff",
            "SlopeSensitivity", "PeakWidth", "AreaReject", "HeightReject",
            "Integration", "Baseline Now", "Negative Peak"
        ]
        type_var = tk.StringVar(value=curr_ev.event_type)
        val_var = tk.StringVar(value=curr_ev.value or "")
        en_var = tk.BooleanVar(value=curr_ev.enabled)

        ttk.Label(dlg, text="Retention Time (min):", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(dlg, textvariable=time_var, width=16).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(dlg, text="Integration Event:", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        cb = ttk.Combobox(dlg, textvariable=type_var, values=event_types, width=20)
        cb.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(dlg, text="Event Value (Optional):", font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(dlg, textvariable=val_var, width=16).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(dlg, text="Status:", font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Checkbutton(dlg, text="Enabled", variable=en_var).grid(row=3, column=1, sticky="w", pady=4)

        def on_save():
            try:
                t = float(time_var.get().strip())
                if t < 0:
                    raise ValueError("Retention time must be >= 0.")
            except ValueError as exc:
                messagebox.showerror("Invalid Input", f"Invalid retention time: {exc}", parent=dlg)
                return

            ev_type = type_var.get().strip()
            if not ev_type:
                messagebox.showerror("Invalid Input", "Event type cannot be blank.", parent=dlg)
                return

            val_str = val_var.get().strip()
            is_en = en_var.get()

            updated = TimedEvent(time_min=t, event_type=ev_type, value=val_str, enabled=is_en)
            if is_new:
                cfg.timed_events.append(updated)
            else:
                cfg.timed_events[event_idx] = updated

            cfg.timed_events.sort(key=lambda e: e.time_min)
            self._refresh_method_tabs()
            self._reprocess_current_auto()
            dlg.destroy()

        btn_f = ttk.Frame(dlg)
        btn_f.grid(row=4, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btn_f, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_f, text="Save Event", command=on_save).pack(side=tk.RIGHT, padx=4)

        dlg.bind("<Return>", lambda e: on_save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _add_timed_event_dialog(self, sname: str) -> None:
        self._open_timed_event_editor(sname, None)

    def _edit_selected_timed_event(self, sname: str) -> None:
        tree = self.event_trees.get(sname)
        if not tree:
            return
        sel = tree.selection()
        if not sel:
            return
        idx = int(sel[0].split("_")[-1])
        self._open_timed_event_editor(sname, idx)

    def _delete_timed_event(self, sname: str) -> None:
        tree = self.event_trees.get(sname)
        cfg = self.method.signals.get(sname)
        if not tree or not cfg:
            return
        sel = tree.selection()
        if not sel:
            return
        idx = int(sel[0].split("_")[-1])
        if 0 <= idx < len(cfg.timed_events):
            del cfg.timed_events[idx]
            self._refresh_method_tabs()
            self._reprocess_current_auto()

    # ------------------------------------------------------------------
    # File / Export Dialogs
    # ------------------------------------------------------------------

    def _open_folder_dialog(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select an Agilent .D Folder or Sequence Directory",
            initialdir=self.workspace_dir,
        )
        if chosen:
            self.workspace_dir = chosen
            self.load_directory(chosen)

    def _import_method_dialog(self) -> None:
        fpath = filedialog.askopenfilename(
            title="Import Method (.pmx or .json)",
            initialdir=self.workspace_dir,
            filetypes=[("Agilent & JSON Methods", "*.pmx *.json"), ("All Files", "*.*")],
        )
        if not fpath:
            return
        if fpath.lower().endswith(".pmx"):
            self.method = load_pmx_method(fpath)
        else:
            self.method = ProcessingMethod.load_json(fpath)
        self.lbl_method_badge.configure(text=f"Method: {self.method.name}")
        self._refresh_zoom_presets()
        self._refresh_method_tabs()
        self._reprocess_all(prefer_rx=True)
        self.status_var.set(f"Imported method '{self.method.name}' from {os.path.basename(fpath)}")

    def _save_method_dialog(self) -> None:
        fpath = filedialog.asksaveasfilename(
            title="Save Processing Method (.json)",
            initialdir=self.workspace_dir,
            initialfile=f"{self.method.name}.json",
            defaultextension=".json",
            filetypes=[("JSON Method", "*.json")],
        )
        if not fpath:
            return
        self.method.save_json(fpath)
        self.status_var.set(f"Saved method to {fpath}")

    def _export_excel_dialog(self) -> None:
        if not self.injections:
            messagebox.showwarning("No Injections", "Load at least one .D injection before exporting.")
            return
        default_name = "MPZ_Reaction_SingleSheet_Summary.xlsx"
        fpath = filedialog.asksaveasfilename(
            title="Export All Injections to Single-Sheet Excel (.xlsx)",
            initialdir=self.workspace_dir,
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook (.xlsx)", "*.xlsx")],
        )
        if not fpath:
            return
        try:
            export_sequence_single_sheet_xlsx(
                self.injections,
                self.method,
                fpath,
                include_extra_blocks=True,
            )
            self.status_var.set(f"Exported single-sheet summary ({len(self.injections)} injections × {len(self.method.compounds)} compounds) to {fpath}")
            messagebox.showinfo(
                "Excel Export Complete",
                f"Successfully exported single-sheet summary:\n\n"
                f"File: {fpath}\n"
                f"Layout: Columns = {len(self.injections)} Injection(s) | Rows = {len(self.method.compounds)} Specific Compounds\n\n"
                f"Ready to select & graph in Excel!",
            )
        except PermissionError:
            messagebox.showerror(
                "Excel File Locked",
                f"Could not save to:\n{fpath}\n\n"
                "The file appears to be open in Microsoft Excel.\n"
                "Please close the spreadsheet in Excel and try exporting again.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Export Error", f"Could not write Excel file:\n{exc}", parent=self)

    def _copy_matrix_to_clipboard(self) -> None:
        """Copy the (Rows = Compounds, Columns = Injections) table as TSV to the clipboard for instant Ctrl+V in Excel."""
        if not self.injections:
            return
        metric = self.preview_metric_var.get()
        headers = ["#", "Compound", "Signal", "Exp. RT (min)"] + [
            inj.sample_name or inj.short_label for inj in self.injections
        ]
        lines = ["\t".join(headers)]
        for comp in self.method.compounds:
            row = [str(comp.index), comp.name, comp.signal, f"{comp.exp_rt_min:.3f}"]
            for inj in self.injections:
                pk = _lookup_compound_peak(inj, comp)
                if pk is None:
                    row.append("0.000" if metric != "rt" else "")
                else:
                    val = {
                        "area": pk.area,
                        "area_pct": pk.area_pct,
                        "height": pk.height,
                        "rt": pk.rt_min,
                    }.get(metric, pk.area)
                    row.append(f"{val:.4f}" if metric != "rt" else f"{val:.3f}")
            lines.append("\t".join(row))

        tsv = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(tsv)
        self.status_var.set(
            f"Copied ({len(self.method.compounds)} compounds × {len(self.injections)} injections) {metric.upper()} matrix to clipboard! Press Ctrl+V in Excel."
        )

    # ------------------------------------------------------------------
    # Channel Display Selection (F20 / R2)
    # ------------------------------------------------------------------

    def set_channel_view(self, mode: str) -> None:
        """Switch channel display mode: 'both', 'FID1A', or 'TCD2B'."""
        norm = mode.lower().strip()
        if "fid" in norm:
            m = "FID1A"
        elif "tcd" in norm:
            m = "TCD2B"
        else:
            m = "both"
        self.channel_view_var.set(m)
        self.chrom_canvas.set_channel_mode(m)
        self.update_idletasks()

    def _on_channel_view_changed(self) -> None:
        self.set_channel_view(self.channel_view_var.get())

    # ------------------------------------------------------------------
    # Theme Management & Toggle (F23 / R4)
    # ------------------------------------------------------------------

    def _toggle_theme(self) -> None:
        """Toggle between Light and Dark themes."""
        new_theme = "dark" if self.current_theme_name == "light" else "light"
        self.set_theme(new_theme)

    def set_theme(self, theme_name: str) -> None:
        """Apply theme by name: 'light' or 'dark'."""
        norm = theme_name.lower().strip()
        palette = DARK_PALETTE if norm == "dark" else LIGHT_PALETTE
        self.current_theme_name = palette.name
        self.theme = palette

        self.configure(bg=palette.bg_app)
        if hasattr(self, "btn_theme_toggle"):
            self.btn_theme_toggle.configure(
                text="☀️ Light Mode" if norm == "dark" else "🌙 Dark Mode",
                bg=palette.topbar_btn_bg,
                fg=palette.topbar_btn_fg,
            )

        style = ttk.Style(self)
        if norm == "dark":
            if "clam" in style.theme_names():
                style.theme_use("clam")
            style.configure(
                "Treeview",
                background=palette.tree_bg,
                foreground=palette.tree_fg,
                fieldbackground=palette.tree_bg,
            )
            style.configure(
                "Treeview.Heading",
                background=palette.tree_header_bg,
                foreground=palette.tree_header_fg,
            )
            style.configure("TNotebook", background=palette.bg_app)
            style.configure("TNotebook.Tab", background=palette.bg_frame, foreground=palette.fg_app)
            style.map(
                "TNotebook.Tab",
                background=[("selected", palette.topbar_bg)],
                foreground=[("selected", "#FFFFFF")],
            )
        else:
            if "vista" in style.theme_names():
                style.theme_use("vista")
            elif "clam" in style.theme_names():
                style.theme_use("clam")
            style.configure(
                "Treeview",
                background=palette.tree_bg,
                foreground=palette.tree_fg,
                fieldbackground=palette.tree_bg,
            )
            style.configure(
                "Treeview.Heading",
                background=palette.tree_header_bg,
                foreground=palette.tree_header_fg,
            )
            style.configure("TNotebook", background=palette.bg_app)
            style.configure("TNotebook.Tab", background=palette.bg_frame, foreground=palette.fg_app)

        if hasattr(self, "peak_tree"):
            self.peak_tree.tag_configure("identified", background=palette.tag_identified_bg, foreground=palette.tag_identified_fg, font=("Segoe UI", 9, "bold"))
            self.peak_tree.tag_configure("negative", background=palette.tag_negative_bg, foreground=palette.tag_negative_fg, font=("Segoe UI", 9, "bold"))
            self.peak_tree.tag_configure("unidentified", foreground=palette.tag_unidentified_fg)
        if hasattr(self, "comp_tree"):
            self.comp_tree.tag_configure("found", background=palette.tag_found_bg)
            self.comp_tree.tag_configure("missing", foreground=palette.tag_missing_fg)
        if hasattr(self, "status_bar_lbl"):
            self.status_bar_lbl.configure(bg=palette.status_bg, fg=palette.status_fg)

        if hasattr(self, "chrom_canvas"):
            self.chrom_canvas.set_theme(palette)

    # ------------------------------------------------------------------
    # Undo Stack (Ctrl+Z) & Escape Deselect (F28 / R7)
    # ------------------------------------------------------------------

    def _get_active_undo_manager(self) -> InjectionUndoManager:
        key = self.current_injection.folder_name if self.current_injection else "default"
        if key not in self.undo_managers:
            self.undo_managers[key] = InjectionUndoManager()
        return self.undo_managers[key]

    def _push_undo_checkpoint(self, description: str) -> None:
        if self.current_injection:
            self._get_active_undo_manager().push_state(
                description, self.current_injection.peaks_by_signal
            )

    def _on_undo_triggered(self, event: Optional[tk.Event] = None):
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
            return None
        if not self.current_injection:
            return None
        mgr = self._get_active_undo_manager()
        item = mgr.undo()
        if not item:
            self.status_var.set("Nothing to undo.")
            return None
        desc, restored_peaks = item
        self.current_injection.peaks_by_signal = restored_peaks
        self.current_injection.integration_source = "manual"
        self.chrom_canvas.selected_peak_id = None
        self.chrom_canvas.redraw()
        self._refresh_peak_table()
        self._refresh_compound_table()
        self._refresh_matrix_preview()
        self.status_var.set(f"Undid: {desc}")
        return "break"

    def _on_escape_triggered(self, event: Optional[tk.Event] = None):
        if self.chrom_canvas._drag_state is not None:
            self.chrom_canvas._drag_state = None
        self.chrom_canvas.selected_peak_id = None
        self.chrom_canvas.highlighted_compound = None
        self.tool_var.set("pan_zoom")
        self.chrom_canvas.set_tool_mode("pan_zoom")
        for tree in (self.peak_tree, self.comp_tree):
            sel = tree.selection()
            if sel:
                tree.selection_remove(sel)
        self.chrom_canvas.redraw()
        self.status_var.set("Deselected active tool and peak. Returned to default pointer mode.")
        return "break"

    # ------------------------------------------------------------------
    # Method-Embedded Custom Zoom Presets (F26 / R8)
    # ------------------------------------------------------------------

    def _save_custom_zoom_preset(self, name: Optional[str] = None) -> None:
        if not name:
            name = simpledialog.askstring(
                "Save Zoom Preset",
                "Enter name for this custom zoom preset:",
                parent=self,
            )
        if not name:
            return
        name = name.strip()
        if not name:
            return

        x0, x1 = self.chrom_canvas.x_range
        y_ranges = {k: (v[0], v[1]) for k, v in self.chrom_canvas.y_ranges.items()}

        new_preset = ZoomPresetDef(
            name=name,
            time_min=float(x0),
            time_max=float(x1),
            y_ranges=y_ranges,
        )

        existing_idx = None
        for i, p in enumerate(self.method.custom_zoom_presets):
            if p.name == name:
                existing_idx = i
                break
        if existing_idx is not None:
            self.method.custom_zoom_presets[existing_idx] = new_preset
        else:
            self.method.custom_zoom_presets.append(new_preset)

        if self.method.source_path and os.path.exists(os.path.dirname(os.path.abspath(self.method.source_path))):
            try:
                self.method.save_json(self.method.source_path)
            except Exception:
                pass

        self._refresh_zoom_presets()
        for val in self.zoom_combo["values"]:
            if name in val:
                self.zoom_combo.set(val)
                break
        self.status_var.set(f"Saved custom zoom preset '{name}' [{x0:.2f}–{x1:.2f} min] to method.")

    def _refresh_zoom_presets(self) -> None:
        self.zoom_presets = {
            "Reaction (3.5–16.5m)": lambda: self.chrom_canvas.zoom_active_region(),
            "C1–C3 + DME (4.4–6.5m)": lambda: self._zoom_preset(4.4, 6.5, (9.4, 19.0), (35.0, 220.0)),
            "MeOH + C4 (6.6–8.6m)": lambda: self._zoom_preset(6.6, 8.6, (9.5, 16.0), (20.0, 120.0)),
            "H2 + Ar (8.0–9.3m)": lambda: self._zoom_preset(8.0, 9.3, (9.7, 11.0), (10.0, 160.0)),
            "CO (13.0–14.3m)": lambda: self._zoom_preset(13.0, 14.3, (9.8, 12.0), (30.0, 310.0)),
            "Full (0–40m)": lambda: self.chrom_canvas.zoom_full_range(),
            "Auto-Y": lambda: self.chrom_canvas.autoscale_visible_y(),
        }

        for preset in getattr(self.method, "custom_zoom_presets", []):
            lbl = f"★ {preset.name} ({preset.time_min:.1f}–{preset.time_max:.1f}m)"
            def _make_handler(p=preset):
                return lambda: self._apply_custom_zoom_preset(p)
            self.zoom_presets[lbl] = _make_handler(preset)

        if hasattr(self, "zoom_combo"):
            vals = list(self.zoom_presets.keys())
            self.zoom_combo["values"] = vals

    def _apply_custom_zoom_preset(self, preset: ZoomPresetDef) -> None:
        self.chrom_canvas.x_range = (preset.time_min, preset.time_max)
        for sname, yr in preset.y_ranges.items():
            self.chrom_canvas.y_ranges[sname] = (yr[0], yr[1])
        self.chrom_canvas.redraw()

    # ------------------------------------------------------------------
    # Method Creation & Modification Dialog (F24 / R5)
    # ------------------------------------------------------------------

    def _open_new_method_dialog(self) -> None:
        MethodEditorDialog(self, method=None, on_method_saved=self._on_method_saved_from_editor)

    def _open_method_editor_dialog(self) -> None:
        MethodEditorDialog(self, method=self.method, on_method_saved=self._on_method_saved_from_editor)

    def _on_method_saved_from_editor(self, updated_method: ProcessingMethod) -> None:
        self.method = updated_method
        self.lbl_method_badge.configure(text=f"Method: {self.method.name}")
        self._refresh_zoom_presets()
        self._refresh_method_tabs()
        self._reprocess_all(prefer_rx=True)
        self.status_var.set(f"Applied updated method '{self.method.name}'.")

    # ------------------------------------------------------------------
    # Right-Click Context Menu Integration (F27 / R6)
    # ------------------------------------------------------------------

    def _on_canvas_context_virtual_event(self, event: Optional[tk.Event] = None) -> None:
        pass

    def _show_chromatogram_context_menu(self, event: tk.Event, hit_type: Any, info: dict) -> None:
        if not self.current_injection:
            return
        sname = self.chrom_canvas._panel_at_xy(event.x, event.y)
        if not sname or sname not in self.current_injection.signals:
            if info.get("peak"):
                sname = info["peak"].signal_name
            elif info.get("left_peak"):
                sname = info["left_peak"].signal_name
            else:
                return

        sig = self.current_injection.signals[sname]
        menu = tk.Menu(self.chrom_canvas.canvas, tearoff=0)

        val = hit_type.value if hasattr(hit_type, "value") else str(hit_type).lower()

        if "peak_body" in val:
            pk = info.get("peak")
            if not pk:
                return
            t_click = info.get("t_click", pk.rt_min)
            title_str = f"Peak: {pk.compound_name or f'RT {pk.rt_min:.3f} min'} (Area: {pk.area:.1f})"
            menu.add_command(label=title_str, state=tk.DISABLED)
            menu.add_separator()
            menu.add_command(
                label="🗑 Delete Peak",
                command=lambda: self._context_action_delete_peak(sname, pk.peak_id),
            )
            menu.add_command(
                label=f"✂ Split Peak at {t_click:.3f} min",
                command=lambda: self._context_action_split_peak(sname, t_click),
            )
            menu.add_command(
                label="⚓ Adjust Baseline Anchors",
                command=lambda: self._context_action_adjust_anchors(pk.peak_id),
            )
            sub_comp = tk.Menu(menu, tearoff=0)
            self._populate_compound_menu_items(sub_comp, sname, pk)
            menu.add_cascade(label="🏷 Assign Compound", menu=sub_comp)
            menu.add_separator()
            menu.add_command(
                label="⇅ Invert Polarity (+/-)",
                command=lambda: self._context_action_toggle_polarity(sname, pk.peak_id),
            )

        elif "anchor" in val and "shared" not in val:
            pk = info.get("peak")
            if not pk:
                return
            kind = info.get("kind", "start")
            t_anc = info.get("t_anc", pk.begin_min if kind == "start" else pk.end_min)
            menu.add_command(label=f"Anchor Point ({kind.capitalize()}) @ {t_anc:.3f} min", state=tk.DISABLED)
            menu.add_separator()
            menu.add_command(
                label="⚓ Move Baseline Anchor",
                command=lambda: self._context_action_adjust_anchors(pk.peak_id),
            )
            menu.add_command(
                label="🎯 Snap Anchor to Trace",
                command=lambda: self._context_action_snap_anchor(sname, pk.peak_id, kind),
            )
            menu.add_command(
                label=f"✂ Split Peak at {t_anc:.3f} min",
                command=lambda: self._context_action_split_peak(sname, t_anc),
            )
            menu.add_command(
                label="🗑 Delete Peak",
                command=lambda: self._context_action_delete_peak(sname, pk.peak_id),
            )
            sub_comp = tk.Menu(menu, tearoff=0)
            self._populate_compound_menu_items(sub_comp, sname, pk)
            menu.add_cascade(label="🏷 Assign Compound", menu=sub_comp)

        elif "shared_extreme" in val:
            p_left = info.get("left_peak")
            p_right = info.get("right_peak")
            t_split = info.get("t_split", p_left.end_min if p_left else 0.0)
            lbl_left = (p_left.compound_name or f"{p_left.rt_min:.2f}m") if p_left else "Left"
            lbl_right = (p_right.compound_name or f"{p_right.rt_min:.2f}m") if p_right else "Right"
            menu.add_command(label=f"Shared Peak Boundary @ {t_split:.3f} min", state=tk.DISABLED)
            menu.add_separator()
            if p_left and p_right:
                menu.add_command(
                    label=f"🔗 Merge / Join Split Peaks ({lbl_left} + {lbl_right})",
                    command=lambda: self._context_action_merge_peaks(sname, p_left, p_right),
                )
            if p_left:
                menu.add_command(
                    label="⚓ Adjust Shared Baseline Anchor",
                    command=lambda: self._context_action_adjust_anchors(p_left.peak_id),
                )
                menu.add_command(
                    label=f"🗑 Delete Left Peak ({lbl_left})",
                    command=lambda: self._context_action_delete_peak(sname, p_left.peak_id),
                )
            if p_right:
                menu.add_command(
                    label=f"🗑 Delete Right Peak ({lbl_right})",
                    command=lambda: self._context_action_delete_peak(sname, p_right.peak_id),
                )

            if p_left:
                sub_l = tk.Menu(menu, tearoff=0)
                self._populate_compound_menu_items(sub_l, sname, p_left)
                menu.add_cascade(label=f"🏷 Assign Left Peak ({lbl_left})", menu=sub_l)
            if p_right:
                sub_r = tk.Menu(menu, tearoff=0)
                self._populate_compound_menu_items(sub_r, sname, p_right)
                menu.add_cascade(label=f"🏷 Assign Right Peak ({lbl_right})", menu=sub_r)
        else:
            return

        menu.tk_popup(event.x_root, event.y_root)

    def _context_action_delete_peak(self, sname: str, peak_id: str) -> None:
        if not self.current_injection:
            return
        pks = self.current_injection.peaks_by_signal.get(sname, [])
        sig = self.current_injection.signals.get(sname)
        if not sig:
            return
        self._push_undo_checkpoint("Delete Peak")
        self.current_injection.peaks_by_signal[sname] = delete_peak_by_id(sig, pks, peak_id, self.method)
        self.current_injection.integration_source = "manual"
        self.chrom_canvas.selected_peak_id = None
        self.chrom_canvas.redraw()
        self._on_canvas_peaks_modified(f"Deleted peak on {sname}")

    def _context_action_split_peak(self, sname: str, t_split: float) -> None:
        if not self.current_injection:
            return
        pks = self.current_injection.peaks_by_signal.get(sname, [])
        sig = self.current_injection.signals.get(sname)
        if not sig:
            return
        self._push_undo_checkpoint(f"Split Peak at {t_split:.3f} min")
        self.current_injection.peaks_by_signal[sname] = split_peak_at(sig, pks, t_split, self.method)
        self.current_injection.integration_source = "manual"
        self.chrom_canvas.redraw()
        self._on_canvas_peaks_modified(f"Split peak at {t_split:.3f} min on {sname}")

    def _context_action_adjust_anchors(self, peak_id: str) -> None:
        self.tool_var.set("drag_anchor")
        self.chrom_canvas.set_tool_mode("drag_anchor")
        self.chrom_canvas.select_peak(peak_id, zoom_to=False)
        self.status_var.set(f"Selected peak anchors for peak '{peak_id}'. Drag anchor handles on canvas.")

    def _context_action_toggle_polarity(self, sname: str, peak_id: str) -> None:
        if not self.current_injection:
            return
        pks = self.current_injection.peaks_by_signal.get(sname, [])
        sig = self.current_injection.signals.get(sname)
        if not sig:
            return
        self._push_undo_checkpoint("Toggle Peak Polarity")
        self.current_injection.peaks_by_signal[sname] = toggle_peak_negative(sig, pks, peak_id, self.method)
        self.current_injection.integration_source = "manual"
        self.chrom_canvas.redraw()
        self._on_canvas_peaks_modified(f"Toggled polarity for peak on {sname}")

    def _context_action_snap_anchor(self, sname: str, peak_id: str, kind: str) -> None:
        if not self.current_injection:
            return
        pks = self.current_injection.peaks_by_signal.get(sname, [])
        sig = self.current_injection.signals.get(sname)
        if not sig:
            return
        target = next((p for p in pks if p.peak_id == peak_id), None)
        if not target:
            return
        self._push_undo_checkpoint(f"Snap {kind.capitalize()} Anchor to Trace")
        if kind == "start":
            new_bs_y = sig.value_at_time(target.begin_min)
            self.current_injection.peaks_by_signal[sname] = update_peak_anchors(
                sig, pks, peak_id, target.begin_min, new_bs_y, target.end_min, target.baseline_end_y, self.method
            )
        else:
            new_be_y = sig.value_at_time(target.end_min)
            self.current_injection.peaks_by_signal[sname] = update_peak_anchors(
                sig, pks, peak_id, target.begin_min, target.baseline_start_y, target.end_min, new_be_y, self.method
            )
        self.current_injection.integration_source = "manual"
        self.chrom_canvas.redraw()
        self._on_canvas_peaks_modified(f"Snapped {kind} anchor to curve on {sname}")

    def _context_action_merge_peaks(self, sname: str, p1: IntegratedPeak, p2: IntegratedPeak) -> None:
        if not self.current_injection:
            return
        pks = self.current_injection.peaks_by_signal.get(sname, [])
        sig = self.current_injection.signals.get(sname)
        if not sig:
            return
        t_start = min(p1.begin_min, p2.begin_min)
        t_end = max(p1.end_min, p2.end_min)
        y_start = p1.baseline_start_y if p1.begin_min < p2.begin_min else p2.baseline_start_y
        y_end = p2.baseline_end_y if p2.end_min > p1.end_min else p1.baseline_end_y

        self._push_undo_checkpoint(f"Merge Split Peaks ({t_start:.2f}–{t_end:.2f} min)")
        updated_pks, _ = add_manual_peak(sig, pks, t_start, y_start, t_end, y_end, method=self.method, snap_to_curve=False)
        self.current_injection.peaks_by_signal[sname] = updated_pks
        self.current_injection.integration_source = "manual"
        self.chrom_canvas.redraw()
        self._on_canvas_peaks_modified(f"Merged split peaks into single peak ({t_start:.2f}–{t_end:.2f} min) on {sname}")

    def _populate_compound_menu_items(self, menu: tk.Menu, sname: str, pk: IntegratedPeak) -> None:
        matching_comps = [c for c in self.method.compounds if c.signal == sname]
        for comp in matching_comps:
            def _assign(c_name=comp.name):
                self._push_undo_checkpoint(f"Assign Compound '{c_name}'")
                pk.compound_name = c_name
                pk.is_identified = True
                self.current_injection.integration_source = "manual"
                self.chrom_canvas.redraw()
                self._on_canvas_peaks_modified(f"Assigned peak at {pk.rt_min:.2f}m as '{c_name}'")
            menu.add_command(label=f"{comp.name} (Exp RT {comp.exp_rt_min:.2f}m)", command=_assign)

        menu.add_separator()
        def _assign_custom():
            val = simpledialog.askstring("Custom Compound Name", "Enter custom compound identification name:", parent=self)
            if val and val.strip():
                c_name = val.strip()
                self._push_undo_checkpoint(f"Assign Custom Compound '{c_name}'")
                pk.compound_name = c_name
                pk.is_identified = True
                self.current_injection.integration_source = "manual"
                self.chrom_canvas.redraw()
                self._on_canvas_peaks_modified(f"Assigned peak at {pk.rt_min:.2f}m as '{c_name}'")
        menu.add_command(label="Custom Name...", command=_assign_custom)

        def _clear_id():
            self._push_undo_checkpoint("Clear Compound Identification")
            pk.compound_name = ""
            pk.is_identified = False
            self.current_injection.integration_source = "manual"
            self.chrom_canvas.redraw()
            self._on_canvas_peaks_modified(f"Cleared identification for peak at {pk.rt_min:.2f}m")
        menu.add_command(label="Clear Identification", command=_clear_id)


# Backward Compatibility Alias (PROJECT.md § Interface Contracts)
OpenLabSubstituteApp = OpenChromLabApp
