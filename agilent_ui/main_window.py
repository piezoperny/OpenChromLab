"""
Main Desktop Window for OpenChromLab — Chromatography Data System.
Built for educational & research GC workflows (FID1A + TCD2B).
"""

import copy
import ctypes
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

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


class PillToggleSwitch(tk.Canvas):
    """Modern canvas-drawn rounded pill toggle switch bound to a tk.BooleanVar."""

    def __init__(
        self,
        parent: tk.Widget,
        variable: tk.BooleanVar,
        command: Optional[Callable[[], None]] = None,
        width: int = 34,
        height: int = 18,
        palette: ThemePalette = LIGHT_PALETTE,
    ) -> None:
        self.variable = variable
        self.command = command
        self.palette = palette
        self._sw_width = int(width)
        self._sw_height = int(height)
        bg_parent = getattr(palette, "overlay_card_bg", palette.bg_frame)
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=bg_parent,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.bind("<Button-1>", self._on_click)
        self._trace_id = self.variable.trace_add("write", self._on_var_changed)
        self.draw()

    def _on_click(self, event: Optional[tk.Event] = None) -> None:
        self.variable.set(not bool(self.variable.get()))
        if self.command:
            self.command()

    def _on_var_changed(self, *args: Any) -> None:
        if self.winfo_exists():
            self.draw()

    def set_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        bg_parent = getattr(palette, "overlay_card_bg", palette.bg_frame)
        self.configure(bg=bg_parent)
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        is_on = bool(self.variable.get())
        track_color = (
            getattr(self.palette, "toggle_on_bg", "#3898EC")
            if is_on
            else getattr(self.palette, "toggle_off_bg", "#222630")
        )
        knob_color = (
            getattr(self.palette, "toggle_knob_on", "#FFFFFF")
            if is_on
            else getattr(self.palette, "toggle_knob_off", "#94A3B8")
        )
        border_color = (
            getattr(self.palette, "subbar_active_border", track_color)
            if is_on
            else getattr(self.palette, "panel_border", "#263040")
        )
        w, h = self._sw_width, self._sw_height
        pad = 2
        r = (h - 2 * pad) / 2.0
        y0 = pad
        y1 = h - pad
        x0 = pad
        x1 = w - pad

        # Draw rounded pill track (left circle + center rect + right circle)
        self.create_oval(x0, y0, x0 + 2 * r, y1, fill=track_color, outline=border_color, width=1, tags=("track",))
        self.create_oval(x1 - 2 * r, y0, x1, y1, fill=track_color, outline=border_color, width=1, tags=("track",))
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=track_color, outline="", tags=("track",))
        self.create_line(x0 + r, y0, x1 - r, y0, fill=border_color, width=1, tags=("track",))
        self.create_line(x0 + r, y1, x1 - r, y1, fill=border_color, width=1, tags=("track",))

        # Draw circular sliding knob
        kr = max(3.0, r - 2.0)
        cy = h / 2.0
        cx = (x1 - r) if is_on else (x0 + r)
        self.create_oval(
            cx - kr, cy - kr, cx + kr, cy + kr,
            fill=knob_color, outline="", tags=("knob",),
        )


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

    def __init__(self, initial_workspace: Optional[str] = None) -> None:
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
        self.configure(bg=DARK_PALETTE.bg_app)

        if sys.platform == "win32":
            try:
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                val = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
            except Exception:
                pass

        if not initial_workspace:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            initial_workspace = repo_root if os.path.isdir(repo_root) else os.getcwd()
        self.workspace_dir = os.path.abspath(initial_workspace)
        self._load_seq_timer: Optional[str] = None

        # Application Icon (F30)
        ico_path = os.path.join(self.workspace_dir, "OpenChromLab.ico")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        # Theme & Channel Selection Attributes (F20, F23)
        self.current_theme_name: str = "dark"
        self.theme: ThemePalette = DARK_PALETTE
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
        self.set_theme("dark")

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
        self._load_seq_timer = self.after(80, lambda: self.load_directory(self.workspace_dir))

    def destroy(self) -> None:
        """Cancel pending after callbacks and clean up resources before destroying window."""
        try:
            self.update_idletasks()
        except Exception:
            pass

        if getattr(self, "_load_seq_timer", None) is not None:
            try:
                self.after_cancel(self._load_seq_timer)
            except Exception:
                pass
            self._load_seq_timer = None

        if hasattr(self, "chrom_canvas") and self.chrom_canvas is not None:
            if getattr(self.chrom_canvas, "_pending_redraw_id", None) is not None:
                try:
                    self.chrom_canvas.after_cancel(self.chrom_canvas._pending_redraw_id)
                except Exception:
                    pass
                self.chrom_canvas._pending_redraw_id = None

        try:
            for aid in self.tk.eval("after info").split():
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass

        super().destroy()

    def iconbitmap(self, bitmap: Any = None, default: Any = None) -> Any:
        """Cross-platform iconbitmap wrapper: loads Windows .ico natively on Windows and falls back gracefully on X11/Linux."""
        try:
            return super().iconbitmap(bitmap=bitmap, default=default)
        except tk.TclError:
            return ""

    # ------------------------------------------------------------------
    # Styling & Layout Construction
    # ------------------------------------------------------------------

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        # Dynamically compute rowheight for crisp text rendering on high-DPI displays
        try:
            import tkinter.font as tkfont
            base_font = tkfont.Font(font=("Segoe UI", 9))
            f_height = base_font.metrics("linespace")
            row_height = max(26, f_height + 8)
        except Exception:
            row_height = 26
        self._tree_row_height = row_height

        style.configure("Treeview", font=("Segoe UI", 9), rowheight=row_height, borderwidth=0, relief="flat")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), relief="flat")
        style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=(12, 5))
        style.configure("Toolbar.TButton", font=("Segoe UI", 9), padding=(6, 3))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), padding=(8, 4))

    def _build_menu(self) -> None:
        self.menubar = tk.Menu(self, tearoff=0)

        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.file_menu.add_command(label="Open .D Folder or Sequence Directory...", command=self._open_folder_dialog)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="New Method (From Scratch)...", command=self._open_new_method_dialog)
        self.file_menu.add_command(label="Method Editor / Edit Method...", command=self._open_method_editor_dialog)
        self.file_menu.add_command(label="Import Method (.pmx or .json)...", command=self._import_method_dialog)
        self.file_menu.add_command(label="Save Method as .json...", command=self._save_method_dialog)
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Export All Injections to Single-Sheet Excel (.xlsx)...   Ctrl+E",
            command=self._export_excel_dialog,
        )
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.destroy)
        self.menubar.add_cascade(label="File", menu=self.file_menu)

        self.int_menu = tk.Menu(self.menubar, tearoff=0)
        self.int_menu.add_command(label="Auto-Integrate Current Injection (12-Tone Engine)", command=self._reprocess_current_auto)
        self.int_menu.add_command(label="Reload OpenLab .rx Ground Truth (Current Injection)", command=self._reprocess_current_rx)
        self.int_menu.add_separator()
        self.int_menu.add_command(label="Reprocess Entire Sequence (Auto Integrator)", command=lambda: self._reprocess_all(prefer_rx=False))
        self.int_menu.add_command(label="Reprocess Entire Sequence (Prefer .rx + Manual)", command=lambda: self._reprocess_all(prefer_rx=True))
        self.int_menu.add_separator()
        self.int_menu.add_command(label="Save Manual Overrides for Current Injection   Ctrl+S", command=self._save_current_manual_overrides)
        self.int_menu.add_command(label="Clear Saved Manual Overrides for Current Injection", command=self._clear_current_manual_overrides)
        self.menubar.add_cascade(label="Integration", menu=self.int_menu)

        self.view_menu = tk.Menu(self.menubar, tearoff=0)
        self.chan_menu = tk.Menu(self.view_menu, tearoff=0)
        self.chan_menu.add_radiobutton(label="Both", variable=self.channel_view_var, value="both", command=self._on_channel_view_changed)
        self.chan_menu.add_radiobutton(label="FID Only", variable=self.channel_view_var, value="FID1A", command=self._on_channel_view_changed)
        self.chan_menu.add_radiobutton(label="TCD Only", variable=self.channel_view_var, value="TCD2B", command=self._on_channel_view_changed)
        self.view_menu.add_cascade(label="Channel View", menu=self.chan_menu)
        self.view_menu.add_separator()
        self.view_menu.add_command(label="Toggle Dark/Light Theme", command=self._toggle_theme)
        self.view_menu.add_command(label="Save Current Zoom View as Preset...", command=self._save_custom_zoom_preset)
        self.view_menu.add_separator()
        self.view_menu.add_command(label="Zoom Reaction Window (3.5 - 16.5 min)", command=lambda: self.chrom_canvas.zoom_active_region())
        self.view_menu.add_command(label="Zoom Full Run (0 - 40 min)", command=lambda: self.chrom_canvas.zoom_full_range())
        self.view_menu.add_command(label="Auto-Scale Visible Y Axes", command=lambda: self.chrom_canvas.autoscale_visible_y())
        self.menubar.add_cascade(label="View", menu=self.view_menu)

        for m in (self.menubar, self.file_menu, self.int_menu, self.view_menu, self.chan_menu):
            self._style_menu_widget(m, self.theme)
        self.config(menu=self.menubar)

    def _build_top_toolbar(self) -> None:
        self.topbar_frame = tk.Frame(
            self,
            bg=self.theme.topbar_bg,
            pady=5,
            padx=8,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
        )
        self.topbar_frame.pack(side=tk.TOP, fill=tk.X)

        # App Title & Method Badge (F19, F8)
        self.lbl_app_title = tk.Label(
            self.topbar_frame,
            text="OpenChromLab",
            font=("Segoe UI", 11, "bold"),
            fg=self.theme.topbar_fg,
            bg=self.theme.topbar_bg,
        )
        self.lbl_app_title.pack(side=tk.LEFT, padx=(2, 10))

        top_btn_bd = getattr(self.theme, "topbar_btn_border", self.theme.panel_border)
        badge_bg = getattr(self.theme, "method_badge_bg", self.theme.topbar_btn_bg)
        badge_fg = getattr(self.theme, "method_badge_fg", "#FBBF24")
        badge_bd = getattr(self.theme, "method_badge_border", self.theme.panel_border)

        self.lbl_method_badge = tk.Label(
            self.topbar_frame,
            text=f"Method: {self.method.name} ⚙",
            font=("Segoe UI", 9, "bold"),
            fg=badge_fg,
            bg=badge_bg,
            padx=8,
            pady=2,
            bd=0,
            highlightthickness=1,
            highlightbackground=badge_bd,
        )
        self.lbl_method_badge.pack(side=tk.LEFT, padx=4)

        self.btn_open_seq = tk.Button(
            self.topbar_frame,
            text="📂 Open .D / Sequence",
            command=self._open_folder_dialog,
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=top_btn_bd,
            padx=8,
            pady=2,
        )
        self.btn_open_seq.pack(side=tk.LEFT, padx=4)

        self.btn_method_editor = tk.Button(
            self.topbar_frame,
            text="📝 Method Editor",
            command=self._open_method_editor_dialog,
            font=("Segoe UI", 9),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=top_btn_bd,
            padx=8,
            pady=2,
        )
        self.btn_method_editor.pack(side=tk.LEFT, padx=4)

        self.btn_import_method = tk.Button(
            self.topbar_frame,
            text="⚙ Import .pmx/json",
            command=self._import_method_dialog,
            font=("Segoe UI", 9),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=top_btn_bd,
            padx=8,
            pady=2,
        )
        self.btn_import_method.pack(side=tk.LEFT, padx=4)

        # Theme Toggle Button (F23)
        toggle_txt = "☀️ Light Mode" if self.current_theme_name == "dark" else "🌙 Dark Mode"
        self.btn_theme_toggle = tk.Button(
            self.topbar_frame,
            text=toggle_txt,
            command=self._toggle_theme,
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=top_btn_bd,
            padx=8,
            pady=2,
        )
        self.btn_theme_toggle.pack(side=tk.RIGHT, padx=4)

        # Right side: Single-Sheet Excel Export & Copy buttons
        self.btn_export_excel = tk.Button(
            self.topbar_frame,
            text="📊 Export Excel",
            command=self._export_excel_dialog,
            font=("Segoe UI", 9, "bold"),
            bg="#107C41" if self.current_theme_name != "dark" else self.theme.topbar_btn_bg,
            fg="#FFFFFF" if self.current_theme_name != "dark" else self.theme.topbar_btn_fg,
            activebackground="#0B5C2E" if self.current_theme_name != "dark" else self.theme.tree_selected_bg,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground="#0B5C2E" if self.current_theme_name != "dark" else top_btn_bd,
            padx=10,
            pady=3,
        )
        self.btn_export_excel.pack(side=tk.RIGHT, padx=4)

        self.btn_copy_matrix = tk.Button(
            self.topbar_frame,
            text="📋 Copy Matrix",
            command=self._copy_matrix_to_clipboard,
            font=("Segoe UI", 9),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=top_btn_bd,
            padx=8,
            pady=3,
        )
        self.btn_copy_matrix.pack(side=tk.RIGHT, padx=4)

        self.topbar_buttons = [
            self.btn_open_seq,
            self.btn_method_editor,
            self.btn_import_method,
            self.btn_copy_matrix,
            self.btn_export_excel,
            self.btn_theme_toggle,
        ]

        # Second row toolbar: Channel View + Manual Tools + Zoom Presets
        sub_btn_bd = getattr(self.theme, "subbar_btn_border", self.theme.panel_border)
        sub_act_bg = getattr(self.theme, "subbar_active_bg", "#2563EB")
        del_fg = getattr(self.theme, "subbar_delete_fg", "#F87171")

        self.subbar_frame = tk.Frame(
            self,
            bg=self.theme.subbar_bg,
            pady=4,
            padx=8,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
        )
        self.subbar_frame.pack(side=tk.TOP, fill=tk.X)

        self.lbl_channel_view = tk.Label(
            self.subbar_frame,
            text="Channel View:",
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.subbar_bg,
            fg=self.theme.subbar_fg,
        )
        self.lbl_channel_view.pack(side=tk.LEFT, padx=(0, 4))

        self.channel_rbs: Dict[str, tk.Radiobutton] = {}
        for c_label, c_val in [("Both", "both"), ("FID Only", "FID1A"), ("TCD Only", "TCD2B")]:
            rb = tk.Radiobutton(
                self.subbar_frame,
                text=c_label,
                variable=self.channel_view_var,
                value=c_val,
                command=self._on_channel_view_changed,
                indicatoron=False,
                font=("Segoe UI", 9),
                bg=self.theme.subbar_btn_bg,
                fg=self.theme.subbar_btn_fg,
                selectcolor=sub_act_bg,
                padx=6,
                pady=2,
                bd=0,
                relief=tk.FLAT,
                offrelief=tk.FLAT,
                overrelief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=sub_btn_bd,
            )
            rb.pack(side=tk.LEFT, padx=1)
            self.channel_rbs[c_val] = rb

        ttk.Separator(self.subbar_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self.lbl_manual_tools = tk.Label(
            self.subbar_frame,
            text="Manual Tools:",
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.subbar_bg,
            fg=self.theme.subbar_fg,
        )
        self.lbl_manual_tools.pack(side=tk.LEFT, padx=(0, 4))

        self.tool_var = tk.StringVar(value="pan_zoom")
        tools = [
            ("🖱 Select / Pan", "pan_zoom"),
            ("⚓ Anchor", "drag_anchor"),
            ("✏ Draw (+/-)", "draw_peak"),
            ("✂ Split", "split_peak"),
        ]
        self.tool_rbs: Dict[str, tk.Radiobutton] = {}
        for text, mode in tools:
            rb = tk.Radiobutton(
                self.subbar_frame,
                text=text,
                variable=self.tool_var,
                value=mode,
                command=lambda m=mode: self._on_tool_button_clicked(m),
                indicatoron=False,
                font=("Segoe UI", 9),
                bg=self.theme.subbar_btn_bg,
                fg=self.theme.subbar_btn_fg,
                selectcolor=sub_act_bg,
                padx=6,
                pady=2,
                bd=0,
                relief=tk.FLAT,
                offrelief=tk.FLAT,
                overrelief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=sub_btn_bd,
            )
            rb.pack(side=tk.LEFT, padx=1)
            self.tool_rbs[mode] = rb

        self.btn_invert = tk.Button(
            self.subbar_frame,
            text="⇅ Invert (+/-)",
            command=self._toggle_selected_peak_polarity,
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.subbar_btn_fg,
            padx=5,
            pady=1,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=sub_btn_bd,
        )
        self.btn_invert.pack(side=tk.LEFT, padx=2)

        self.btn_delete = tk.Button(
            self.subbar_frame,
            text="🗑 Delete",
            command=self._delete_selected_peak,
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=del_fg,
            padx=5,
            pady=1,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=sub_btn_bd,
        )
        self.btn_delete.pack(side=tk.LEFT, padx=2)

        self.btn_auto = tk.Button(
            self.subbar_frame,
            text="⚡ Auto",
            command=self._reprocess_current_auto,
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.subbar_btn_fg,
            padx=5,
            pady=1,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=sub_btn_bd,
        )
        self.btn_auto.pack(side=tk.LEFT, padx=2)

        self.btn_rx = tk.Button(
            self.subbar_frame,
            text="↺ .rx",
            command=self._reprocess_current_rx,
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.subbar_btn_fg,
            padx=5,
            pady=1,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=sub_btn_bd,
        )
        self.btn_rx.pack(side=tk.LEFT, padx=2)

        # Quick Zoom Region Presets on right side using compact ttk.Combobox (F26)
        self.zoom_frame = tk.Frame(self.subbar_frame, bg=self.theme.subbar_bg)
        self.zoom_frame.pack(side=tk.RIGHT, padx=2)

        self.lbl_zoom_preset = tk.Label(
            self.zoom_frame,
            text="Zoom Preset:",
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.subbar_bg,
            fg=self.theme.subbar_fg,
        )
        self.lbl_zoom_preset.pack(side=tk.LEFT, padx=(2, 4))

        self.btn_save_preset = tk.Button(
            self.zoom_frame,
            text="📷 Save Preset ▾",
            command=self._save_custom_zoom_preset,
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.subbar_btn_fg,
            padx=6,
            pady=1,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=sub_btn_bd,
        )
        self.btn_save_preset.pack(side=tk.LEFT, padx=2)

        self.zoom_presets: Dict[str, Any] = {}
        self.zoom_combo = ttk.Combobox(
            self.zoom_frame,
            values=[],
            state="readonly",
            width=22,
            font=("Segoe UI", 9),
        )
        self.zoom_combo.pack(side=tk.LEFT, padx=2)
        self.zoom_combo.bind("<<ComboboxSelected>>", self._on_zoom_preset_selected)

        self.btn_auto_y = tk.Button(
            self.zoom_frame,
            text="Auto-Y",
            command=lambda: self.chrom_canvas.autoscale_visible_y(),
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.subbar_btn_fg,
            padx=6,
            pady=1,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=sub_btn_bd,
        )
        self.btn_auto_y.pack(side=tk.LEFT, padx=2)

        self.subbar_labels = [self.lbl_channel_view, self.lbl_manual_tools, self.lbl_zoom_preset]
        self.subbar_action_buttons = [
            self.btn_invert,
            self.btn_delete,
            self.btn_auto,
            self.btn_rx,
            self.btn_save_preset,
            self.btn_auto_y,
        ]
        self._refresh_segmented_button_styles()

        self._refresh_zoom_presets()
        if "Reaction (3.5–16.5m)" in self.zoom_combo["values"]:
            self.zoom_combo.set("Reaction (3.5–16.5m)")

    def _on_tool_button_clicked(self, mode: str) -> None:
        self.tool_var.set(mode)
        self._refresh_segmented_button_styles()
        if hasattr(self, "chrom_canvas"):
            self.chrom_canvas.set_tool_mode(mode)

    def _refresh_segmented_button_styles(self) -> None:
        """Apply flat active/inactive pill colors to Channel View and Manual Tools buttons."""
        palette = self.theme
        act_bg = getattr(palette, "subbar_active_bg", "#2563EB")
        act_fg = getattr(palette, "subbar_active_fg", "#FFFFFF")
        act_bd = getattr(palette, "subbar_active_border", "#3B82F6")
        inact_bg = palette.subbar_btn_bg
        inact_fg = "#94A3B8" if palette.name == "dark" else palette.subbar_btn_fg
        inact_bd = getattr(palette, "subbar_btn_border", palette.panel_border)

        cur_chan = self.channel_view_var.get()
        for val, rb in getattr(self, "channel_rbs", {}).items():
            is_act = (val == cur_chan)
            rb.configure(
                bg=act_bg if is_act else inact_bg,
                fg=act_fg if is_act else inact_fg,
                selectcolor=act_bg,
                activebackground=act_bg,
                activeforeground=act_fg,
                highlightbackground=act_bd if is_act else inact_bd,
                relief=tk.FLAT,
                offrelief=tk.FLAT,
                overrelief=tk.FLAT,
            )

        cur_tool = self.tool_var.get() if hasattr(self, "tool_var") else "pan_zoom"
        for mode, rb in getattr(self, "tool_rbs", {}).items():
            is_act = (mode == cur_tool)
            rb.configure(
                bg=act_bg if is_act else inact_bg,
                fg=act_fg if is_act else inact_fg,
                selectcolor=act_bg,
                activebackground=act_bg,
                activeforeground=act_fg,
                highlightbackground=act_bd if is_act else inact_bd,
                relief=tk.FLAT,
                offrelief=tk.FLAT,
                overrelief=tk.FLAT,
            )

    def _build_main_panes(self) -> None:
        self.outer_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.outer_paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # 1. Left Sidebar: Sequence / Injections Tree + Overlay Toggles
        self.left_frame = ttk.Frame(self.outer_paned, width=310)
        self.outer_paned.add(self.left_frame, weight=0)

        self.lbl_seq = tk.Label(
            self.left_frame,
            text="Sequence Injections (.D)",
            font=("Segoe UI", 9, "bold"),
            bg=getattr(self.theme, "seq_header_bg", self.theme.subbar_bg),
            fg=getattr(self.theme, "seq_header_fg", self.theme.fg_app),
            anchor="w",
            padx=6,
            pady=4,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
        )
        self.lbl_seq.pack(fill=tk.X)

        tree_container = ttk.Frame(self.left_frame)
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

        self.inj_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.inj_tree.yview)
        self.inj_tree.configure(yscrollcommand=self.inj_scroll.set)
        self.inj_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inj_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.inj_tree.bind("<<TreeviewSelect>>", self._on_injection_selected)

        # Right PanedWindow (Chromatogram + Bottom Notebook)
        self.right_paned = ttk.PanedWindow(self.outer_paned, orient=tk.VERTICAL)
        self.outer_paned.add(self.right_paned, weight=1)

        # 2. Top-Right: Dual Stacked Chromatogram Viewer
        chrom_frame = ttk.Frame(self.right_paned)
        self.right_paned.add(chrom_frame, weight=3)

        self.chrom_canvas = DualChromatogramCanvas(
            chrom_frame,
            on_peak_selected=self._on_canvas_peak_selected,
            on_peaks_modified=self._on_canvas_peaks_modified,
        )
        self.chrom_canvas.pack(fill=tk.BOTH, expand=True)

        # Modern "Plot Overlays & Options" Card with Master Toggle + 5 Pill Toggle Switches (F9)
        card_bg = getattr(self.theme, "overlay_card_bg", self.theme.bg_frame)
        card_bd = getattr(self.theme, "overlay_card_border", self.theme.panel_border)
        self.ov_frame = tk.Frame(
            self.left_frame,
            bg=card_bg,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=card_bd,
            padx=8,
            pady=6,
        )
        self.ov_frame.pack(fill=tk.X, pady=2)

        self.ov_header_frame = tk.Frame(self.ov_frame, bg=card_bg)
        self.ov_header_frame.pack(fill=tk.X, pady=(0, 4))

        self.lbl_ov_title = tk.Label(
            self.ov_header_frame,
            text="Plot Overlays & Options",
            font=("Segoe UI", 9, "bold"),
            bg=card_bg,
            fg=self.theme.fg_app,
            anchor="w",
        )
        self.lbl_ov_title.pack(side=tk.LEFT)

        self.master_overlay_var = tk.BooleanVar(value=True)
        self.master_toggle_switch = PillToggleSwitch(
            self.ov_header_frame,
            variable=self.master_overlay_var,
            command=self._on_master_overlay_toggled,
            palette=self.theme,
        )
        self.master_toggle_switch.pack(side=tk.RIGHT)

        self.ov_sep = tk.Frame(self.ov_frame, bg=card_bd, height=1)
        self.ov_sep.pack(fill=tk.X, pady=(2, 4))

        overlay_defs = [
            ("Show Compound Names & RTs", self.chrom_canvas.show_compound_labels, self.chrom_canvas.redraw),
            ("Show RT Identification Windows", self.chrom_canvas.show_rt_windows, self.chrom_canvas.redraw),
            ("Show Timed Integration Events", self.chrom_canvas.show_timed_events, self.chrom_canvas.redraw),
            ("Show Baselines & Anchors", self.chrom_canvas.show_baselines, self.chrom_canvas.redraw),
            ("Snap Dragged Anchors to Curve", self.chrom_canvas.snap_anchors_to_trace, None),
        ]
        self.overlay_row_frames: List[tk.Frame] = []
        self.overlay_row_labels: List[tk.Label] = []
        self.overlay_toggle_switches: List[PillToggleSwitch] = []

        for label_text, bvar, cmd in overlay_defs:
            row_f = tk.Frame(self.ov_frame, bg=card_bg, pady=2)
            row_f.pack(fill=tk.X)
            lbl = tk.Label(
                row_f,
                text=f"✓ {label_text}",
                font=("Segoe UI", 8),
                bg=card_bg,
                fg=self.theme.fg_app,
                anchor="w",
                cursor="hand2",
            )
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            sw = PillToggleSwitch(
                row_f,
                variable=bvar,
                command=cmd,
                palette=self.theme,
            )
            sw.pack(side=tk.RIGHT, padx=(4, 0))
            lbl.bind("<Button-1>", lambda e, s=sw: s._on_click())
            self.overlay_row_frames.append(row_f)
            self.overlay_row_labels.append(lbl)
            self.overlay_toggle_switches.append(sw)

        # 3. Bottom-Right: Notebook with 4 Tabs
        bottom_frame = ttk.Frame(self.right_paned)
        self.right_paned.add(bottom_frame, weight=2)

        self.notebook = ttk.Notebook(bottom_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_tab_injection_peaks()
        self._build_tab_compound_table()
        self._build_tab_timed_events()
        self._build_tab_matrix_preview()

    def _on_master_overlay_toggled(self) -> None:
        state = bool(self.master_overlay_var.get())
        for bvar in (
            self.chrom_canvas.show_compound_labels,
            self.chrom_canvas.show_rt_windows,
            self.chrom_canvas.show_timed_events,
            self.chrom_canvas.show_baselines,
            self.chrom_canvas.snap_anchors_to_trace,
        ):
            bvar.set(state)
        self.chrom_canvas.redraw()

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

        self.tab2_btn_bar = tk.Frame(tab, bg=self.theme.bg_frame, pady=3)
        self.tab2_btn_bar.pack(side=tk.TOP, fill=tk.X, padx=6)

        self.tab2_lbl = tk.Label(
            self.tab2_btn_bar,
            text="Method Compounds (16) — Double-click to edit, click to highlight on plot:",
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.bg_frame,
            fg=self.theme.fg_app,
        )
        self.tab2_lbl.pack(side=tk.LEFT)

        ttk.Button(self.tab2_btn_bar, text="🛠 Open Method Editor...", command=self._open_method_editor_dialog).pack(side=tk.RIGHT, padx=3)
        ttk.Button(self.tab2_btn_bar, text="💾 Save Method (.json)", command=self._save_method_dialog).pack(side=tk.RIGHT, padx=3)
        ttk.Button(self.tab2_btn_bar, text="➖ Remove", command=self._remove_selected_compound).pack(side=tk.RIGHT, padx=3)
        ttk.Button(self.tab2_btn_bar, text="➕ Add", command=self._add_compound_dialog).pack(side=tk.RIGHT, padx=3)
        ttk.Button(self.tab2_btn_bar, text="✏ Edit Compound", command=self._edit_selected_compound_dialog).pack(side=tk.RIGHT, padx=3)

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

        self.tab4_top_bar = tk.Frame(tab, bg=self.theme.bg_frame, pady=4)
        self.tab4_top_bar.pack(side=tk.TOP, fill=tk.X, padx=6)

        self.tab4_lbl = tk.Label(
            self.tab4_top_bar,
            text="Live Preview of Single-Sheet Export (Rows = 16 Method Compounds | Columns = All Loaded Injections):",
            font=("Segoe UI", 9, "bold"),
            bg=self.theme.bg_frame,
            fg=self.theme.fg_app,
        )
        self.tab4_lbl.pack(side=tk.LEFT)

        self.preview_metric_var = tk.StringVar(value="area")
        for lbl, val in (("Area", "area"), ("Area %", "area_pct"), ("Height", "height"), ("RT (min)", "rt")):
            ttk.Radiobutton(
                self.tab4_top_bar,
                text=lbl,
                variable=self.preview_metric_var,
                value=val,
                command=self._refresh_matrix_preview,
            ).pack(side=tk.LEFT, padx=6)

        ttk.Button(
            self.tab4_top_bar,
            text="📊 Export Single-Sheet .xlsx...",
            command=self._export_excel_dialog,
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            self.tab4_top_bar,
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
            bg=self.theme.status_bg,
            fg=self.theme.status_fg,
            anchor="w",
            padx=10,
            pady=3,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
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
                        self.lbl_method_badge.configure(text=f"Method: {self.method.name} ⚙")
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
        dlg.configure(bg=self.theme.bg_frame)
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
        dlg.configure(padx=16, pady=12, bg=self.theme.bg_frame)

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
        self.lbl_method_badge.configure(text=f"Method: {self.method.name} ⚙")
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
        self._refresh_segmented_button_styles()
        self.chrom_canvas.set_channel_mode(m)
        self.update_idletasks()

    def _on_channel_view_changed(self) -> None:
        self.set_channel_view(self.channel_view_var.get())

    # ------------------------------------------------------------------
    # Theme Management & Toggle (F23 / R4 / F8–F11)
    # ------------------------------------------------------------------

    def _toggle_theme(self) -> None:
        """Toggle between Light and Dark themes."""
        new_theme = "dark" if self.current_theme_name == "light" else "light"
        self.set_theme(new_theme)

    def _style_menu_widget(self, menu_w: tk.Menu, palette: ThemePalette) -> None:
        try:
            menu_w.configure(
                bg=palette.bg_frame,
                fg=palette.fg_app,
                activebackground=palette.tree_selected_bg,
                activeforeground=palette.tree_selected_fg,
                bd=0,
                relief=tk.FLAT,
            )
        except Exception:
            pass

    def set_theme(self, theme_name: str) -> None:
        """Apply theme by name: 'light' or 'dark' across all toolbars, panels, switches, tabs, and tables."""
        norm = theme_name.lower().strip()
        palette = DARK_PALETTE if norm == "dark" else LIGHT_PALETTE
        self.current_theme_name = palette.name
        self.theme = palette

        self.configure(bg=palette.bg_app)

        # 1. Top Header Toolbar & Method Pill Badge (F8)
        if hasattr(self, "topbar_frame"):
            self.topbar_frame.configure(
                bg=palette.topbar_bg,
                highlightbackground=palette.panel_border,
            )
        if hasattr(self, "lbl_app_title"):
            self.lbl_app_title.configure(bg=palette.topbar_bg, fg=palette.topbar_fg)
        if hasattr(self, "lbl_method_badge"):
            self.lbl_method_badge.configure(
                bg=getattr(palette, "method_badge_bg", palette.topbar_btn_bg),
                fg=getattr(palette, "method_badge_fg", "#FBBF24"),
                highlightbackground=getattr(palette, "method_badge_border", palette.panel_border),
            )
        top_btn_bd = getattr(palette, "topbar_btn_border", palette.panel_border)
        for btn in getattr(self, "topbar_buttons", []):
            if btn is getattr(self, "btn_export_excel", None) and norm != "dark":
                btn.configure(
                    bg="#107C41",
                    fg="#FFFFFF",
                    activebackground="#0B5C2E",
                    activeforeground="#FFFFFF",
                    highlightbackground="#0B5C2E",
                )
            else:
                btn.configure(
                    bg=palette.topbar_btn_bg,
                    fg=palette.topbar_btn_fg,
                    activebackground=palette.tree_selected_bg,
                    activeforeground="#FFFFFF",
                    highlightbackground=top_btn_bd,
                    relief=tk.FLAT,
                )
        if hasattr(self, "btn_theme_toggle"):
            self.btn_theme_toggle.configure(
                text="☀️ Light Mode" if norm == "dark" else "🌙 Dark Mode",
                bg=palette.topbar_btn_bg,
                fg=palette.topbar_btn_fg,
                highlightbackground=top_btn_bd,
            )

        # 2. Second-Row Sub-Toolbar, Segmented Pills, Manual Action Buttons & Zoom Frame (F8)
        if hasattr(self, "subbar_frame"):
            self.subbar_frame.configure(
                bg=palette.subbar_bg,
                highlightbackground=palette.panel_border,
                relief=tk.FLAT,
            )
        if hasattr(self, "zoom_frame"):
            self.zoom_frame.configure(bg=palette.subbar_bg)
        for lbl in getattr(self, "subbar_labels", []):
            lbl.configure(bg=palette.subbar_bg, fg=palette.subbar_fg)

        sub_btn_bd = getattr(palette, "subbar_btn_border", palette.panel_border)
        del_fg = getattr(palette, "subbar_delete_fg", "#F87171")
        for btn in getattr(self, "subbar_action_buttons", []):
            fg_col = del_fg if btn is getattr(self, "btn_delete", None) else palette.subbar_btn_fg
            btn.configure(
                bg=palette.subbar_btn_bg,
                fg=fg_col,
                activebackground=palette.tree_selected_bg,
                activeforeground="#FFFFFF",
                highlightbackground=sub_btn_bd,
                relief=tk.FLAT,
            )
        self._refresh_segmented_button_styles()

        # 3. Left Sidebar Sequence Header & Plot Overlays Card + Pill Toggle Switches (F9)
        if hasattr(self, "lbl_seq"):
            self.lbl_seq.configure(
                bg=getattr(palette, "seq_header_bg", palette.subbar_bg),
                fg=getattr(palette, "seq_header_fg", palette.fg_app),
                highlightbackground=palette.panel_border,
            )
        card_bg = getattr(palette, "overlay_card_bg", palette.bg_frame)
        card_bd = getattr(palette, "overlay_card_border", palette.panel_border)
        if hasattr(self, "ov_frame"):
            self.ov_frame.configure(bg=card_bg, highlightbackground=card_bd)
        if hasattr(self, "ov_header_frame"):
            self.ov_header_frame.configure(bg=card_bg)
        if hasattr(self, "lbl_ov_title"):
            self.lbl_ov_title.configure(bg=card_bg, fg=palette.fg_app)
        if hasattr(self, "ov_sep"):
            self.ov_sep.configure(bg=card_bd)
        if hasattr(self, "master_toggle_switch"):
            self.master_toggle_switch.set_theme(palette)
        for rf in getattr(self, "overlay_row_frames", []):
            rf.configure(bg=card_bg)
        for rl in getattr(self, "overlay_row_labels", []):
            rl.configure(bg=card_bg, fg=palette.fg_app)
        for sw in getattr(self, "overlay_toggle_switches", []):
            sw.set_theme(palette)

        # 4. Tab 2 & Tab 4 Sub-bars (F11)
        if hasattr(self, "tab2_btn_bar"):
            self.tab2_btn_bar.configure(bg=palette.bg_frame)
        if hasattr(self, "tab2_lbl"):
            self.tab2_lbl.configure(bg=palette.bg_frame, fg=palette.fg_app)
        if hasattr(self, "tab4_top_bar"):
            self.tab4_top_bar.configure(bg=palette.bg_frame)
        if hasattr(self, "tab4_lbl"):
            self.tab4_lbl.configure(bg=palette.bg_frame, fg=palette.fg_app)

        # 5. Menu Bars
        for m in (
            getattr(self, "menubar", None),
            getattr(self, "file_menu", None),
            getattr(self, "int_menu", None),
            getattr(self, "view_menu", None),
            getattr(self, "chan_menu", None),
        ):
            if m is not None:
                self._style_menu_widget(m, palette)

        # 6. Comprehensive ttk.Style Configuration (F9, F11)
        style = ttk.Style(self)
        row_h = getattr(self, "_tree_row_height", 26)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TFrame", background=palette.bg_frame)
        style.configure("TPanedwindow", background=palette.bg_app)
        style.configure("Sash", sashthickness=4, background=palette.panel_border)
        style.configure("TSeparator", background=palette.panel_border)
        style.configure("TLabel", background=palette.bg_frame, foreground=palette.fg_app)
        style.configure(
            "TLabelframe",
            background=palette.bg_frame,
            foreground=palette.fg_app,
            bordercolor=palette.panel_border,
            relief="flat",
        )
        style.configure(
            "TLabelframe.Label",
            background=palette.bg_frame,
            foreground=palette.panel_title,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "TButton",
            background=palette.subbar_btn_bg,
            foreground=palette.subbar_btn_fg,
            bordercolor=sub_btn_bd,
            lightcolor=palette.subbar_btn_bg,
            darkcolor=palette.subbar_btn_bg,
            relief="flat",
            padding=(6, 2),
        )
        style.map(
            "TButton",
            background=[("active", palette.tree_selected_bg), ("pressed", palette.subbar_active_bg)],
            foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF")],
        )
        style.configure(
            "TRadiobutton",
            background=palette.bg_frame,
            foreground=palette.fg_app,
            indicatorbackground=palette.tree_bg,
            indicatorforeground=palette.trace_fid,
        )
        style.map(
            "TRadiobutton",
            background=[("active", palette.bg_frame)],
            foreground=[("active", palette.topbar_fg)],
        )
        style.configure(
            "TCheckbutton",
            background=palette.bg_frame,
            foreground=palette.fg_app,
        )
        style.configure(
            "TEntry",
            fieldbackground=palette.tree_bg,
            foreground=palette.tree_fg,
            insertcolor=palette.tree_fg,
            bordercolor=palette.panel_border,
            lightcolor=palette.panel_border,
            darkcolor=palette.panel_border,
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette.subbar_btn_bg,
            background=palette.subbar_btn_bg,
            foreground=palette.subbar_btn_fg,
            arrowcolor=palette.subbar_btn_fg,
            bordercolor=sub_btn_bd,
            lightcolor=palette.subbar_btn_bg,
            darkcolor=palette.subbar_btn_bg,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette.subbar_btn_bg)],
            selectbackground=[("readonly", palette.subbar_btn_bg)],
            selectforeground=[("readonly", palette.subbar_btn_fg)],
            background=[("readonly", palette.subbar_btn_bg)],
            foreground=[("readonly", palette.subbar_btn_fg)],
        )
        self.option_add("*TCombobox*Listbox.background", palette.tree_bg)
        self.option_add("*TCombobox*Listbox.foreground", palette.tree_fg)
        self.option_add("*TCombobox*Listbox.selectBackground", palette.tree_selected_bg)
        self.option_add("*TCombobox*Listbox.selectForeground", palette.tree_selected_fg)

        for s_orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(
                s_orient,
                gripcount=0,
                background="#263040" if norm == "dark" else palette.subbar_btn_bg,
                troughcolor="#11161F" if norm == "dark" else palette.tree_bg,
                bordercolor="#11161F" if norm == "dark" else palette.tree_bg,
                lightcolor="#263040" if norm == "dark" else palette.subbar_btn_bg,
                darkcolor="#263040" if norm == "dark" else palette.subbar_btn_bg,
                arrowcolor="#94A3B8" if norm == "dark" else palette.axis_text,
                arrowsize=11,
                relief="flat",
            )
            style.map(s_orient, background=[("active", "#3B82F6"), ("pressed", "#2563EB")])

        style.configure(
            "Treeview",
            font=("Segoe UI", 9),
            rowheight=row_h,
            background=palette.tree_bg,
            foreground=palette.tree_fg,
            fieldbackground=palette.tree_bg,
            bordercolor=palette.panel_border,
            lightcolor=palette.tree_bg,
            darkcolor=palette.tree_bg,
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", palette.tree_selected_bg)],
            foreground=[("selected", palette.tree_selected_fg)],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI", 9, "bold"),
            background=palette.tree_header_bg,
            foreground=palette.tree_header_fg,
            bordercolor=palette.panel_border,
            lightcolor=palette.tree_header_bg,
            darkcolor=palette.tree_header_bg,
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Treeview.Heading",
            background=[("active", palette.subbar_btn_bg)],
            foreground=[("active", palette.topbar_fg)],
        )

        # Notebook & Active Cyan/Teal Tab Styling (F11)
        tab_act_bg = getattr(palette, "tab_active_bg", "#0E4149")
        tab_act_fg = getattr(palette, "tab_active_fg", "#38BDF8")
        tab_inact_bg = getattr(palette, "tab_inactive_bg", palette.bg_frame)
        tab_inact_fg = getattr(palette, "tab_inactive_fg", palette.fg_app)
        style.configure(
            "TNotebook",
            background=palette.bg_app,
            bordercolor=palette.panel_border,
            lightcolor=palette.bg_app,
            darkcolor=palette.bg_app,
            borderwidth=0,
            relief="flat",
            tabmargins=(2, 2, 2, 0),
        )
        style.configure(
            "TNotebook.Tab",
            font=("Segoe UI", 9, "bold"),
            padding=(14, 6),
            background=tab_inact_bg,
            foreground=tab_inact_fg,
            bordercolor=palette.panel_border,
            lightcolor=tab_inact_bg,
            darkcolor=tab_inact_bg,
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", tab_act_bg), ("active", palette.subbar_btn_bg)],
            foreground=[("selected", tab_act_fg), ("active", palette.topbar_fg)],
        )

        if hasattr(self, "peak_tree"):
            self.peak_tree.tag_configure("identified", background=palette.tag_identified_bg, foreground=palette.tag_identified_fg, font=("Segoe UI", 9, "bold"))
            self.peak_tree.tag_configure("negative", background=palette.tag_negative_bg, foreground=palette.tag_negative_fg, font=("Segoe UI", 9, "bold"))
            self.peak_tree.tag_configure("unidentified", foreground=palette.tag_unidentified_fg)
        if hasattr(self, "comp_tree"):
            self.comp_tree.tag_configure("found", background=palette.tag_found_bg, foreground=palette.tree_fg)
            self.comp_tree.tag_configure("missing", foreground=palette.tag_missing_fg)
        if hasattr(self, "status_bar_lbl"):
            self.status_bar_lbl.configure(
                bg=palette.status_bg,
                fg=palette.status_fg,
                highlightbackground=palette.panel_border,
            )

        if hasattr(self, "chrom_canvas"):
            self.chrom_canvas.set_theme(palette)

        self.update_idletasks()

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
        self._refresh_segmented_button_styles()
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
        MethodEditorDialog(self, method=None, on_method_saved=self._on_method_saved_from_editor, theme=self.theme)

    def _open_method_editor_dialog(self) -> None:
        MethodEditorDialog(self, method=self.method, on_method_saved=self._on_method_saved_from_editor, theme=self.theme)

    def _on_method_saved_from_editor(self, updated_method: ProcessingMethod) -> None:
        self.method = updated_method
        self.lbl_method_badge.configure(text=f"Method: {self.method.name} ⚙")
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
        self._style_menu_widget(menu, self.theme)

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
            self._style_menu_widget(sub_comp, self.theme)
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
            self._style_menu_widget(sub_comp, self.theme)
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
                self._style_menu_widget(sub_l, self.theme)
                self._populate_compound_menu_items(sub_l, sname, p_left)
                menu.add_cascade(label=f"🏷 Assign Left Peak ({lbl_left})", menu=sub_l)
            if p_right:
                sub_r = tk.Menu(menu, tearoff=0)
                self._style_menu_widget(sub_r, self.theme)
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
        self._refresh_segmented_button_styles()
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
