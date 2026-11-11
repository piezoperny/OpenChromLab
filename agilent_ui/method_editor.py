"""
Dedicated Method Editor Dialog for OpenChromLab.
Allows creating new analytical methods from scratch and modifying existing methods,
including compound tables, tolerance windows, calibration parameters, detector channel
integration settings, and timed integration events.
"""

import copy
import ctypes
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, List, Optional, Tuple

from agilent_core.method_model import (
    CompoundDef,
    ProcessingMethod,
    SignalMethodConfig,
    TimedEvent,
    build_default_mpz_method,
)
from agilent_ui.theme import DARK_PALETTE, LIGHT_PALETTE, ThemePalette, apply_windows_dark_titlebar


class MethodEditorDialog(tk.Toplevel):
    """Full-featured modal/non-modal dialog for method creation and editing."""

    def __init__(
        self,
        parent: Optional[tk.Widget] = None,
        method: Optional[ProcessingMethod] = None,
        on_method_saved: Optional[Callable[[ProcessingMethod], None]] = None,
        theme: Optional[ThemePalette] = None,
    ) -> None:
        super().__init__(parent)
        self.theme: ThemePalette = theme if theme is not None else getattr(parent, "theme", DARK_PALETTE)
        self.configure(bg=self.theme.bg_app)
        self.title("Method Editor — OpenChromLab")
        self.geometry("980x680")
        self.minsize(850, 550)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self.on_method_saved = on_method_saved

        if method is not None:
            self.method = copy.deepcopy(method)
        else:
            self.method = ProcessingMethod(name="New_Method")
            self.method.signals["FID1A"] = SignalMethodConfig(signal_name="FID1A")
            self.method.signals["TCD2B"] = SignalMethodConfig(signal_name="TCD2B")

        # Ensure signals exist
        if "FID1A" not in self.method.signals:
            self.method.signals["FID1A"] = SignalMethodConfig(signal_name="FID1A")
        if "TCD2B" not in self.method.signals:
            self.method.signals["TCD2B"] = SignalMethodConfig(signal_name="TCD2B")

        self._build_header_toolbar()
        self._build_notebook_tabs()
        self._build_footer()

        self._load_method_data_into_ui()

        # Keyboard shortcuts
        self.bind("<Control-s>", lambda e: self._on_save_method())
        self.bind("<Escape>", lambda e: self.destroy())

    # ------------------------------------------------------------------
    # UI Layout Construction
    # ------------------------------------------------------------------

    def _build_header_toolbar(self) -> None:
        hdr_frame = tk.Frame(self, bg=self.theme.topbar_bg, padx=10, pady=8)
        hdr_frame.pack(side=tk.TOP, fill=tk.X)

        tk.Label(
            hdr_frame,
            text="Method Name:",
            font=("Segoe UI", 10, "bold"),
            fg=self.theme.topbar_fg,
            bg=self.theme.topbar_bg,
        ).pack(side=tk.LEFT, padx=(0, 6))

        self.method_name_var = tk.StringVar(value=self.method.name)
        self.ent_method_name = ttk.Entry(hdr_frame, textvariable=self.method_name_var, width=28, font=("Segoe UI", 9))
        self.ent_method_name.pack(side=tk.LEFT, padx=(0, 15))

        tk.Button(
            hdr_frame,
            text="📄 New Method (Blank)",
            command=self._on_new_method,
            font=("Segoe UI", 9),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            activebackground=self.theme.subbar_active_bg,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.topbar_btn_border,
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=3)

        tk.Button(
            hdr_frame,
            text="📂 Open JSON...",
            command=self._on_open_json,
            font=("Segoe UI", 9),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            activebackground=self.theme.subbar_active_bg,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.topbar_btn_border,
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=3)

        tk.Button(
            hdr_frame,
            text="💾 Save",
            command=self._on_save_method,
            font=("Segoe UI", 9, "bold"),
            bg="#107C41",
            fg="#FFFFFF",
            activebackground="#0B5C2E",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=2,
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            hdr_frame,
            text="💾 Save As...",
            command=self._on_save_as_method,
            font=("Segoe UI", 9),
            bg=self.theme.topbar_btn_bg,
            fg=self.theme.topbar_btn_fg,
            activebackground=self.theme.subbar_active_bg,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.topbar_btn_border,
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=3)

    def _build_notebook_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Tab 1: Compound Table & Calibration
        self.tab_compounds = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.tab_compounds, text="  Compound Identification & Calibration  ")
        self._build_tab_compounds()

        # Tab 2: Channel Integration Parameters
        self.tab_integration = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_integration, text="  Channel Integration Parameters  ")
        self._build_tab_integration()

        # Tab 3: Timed Integration Events
        self.tab_timed_events = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.tab_timed_events, text="  Timed Integration Events  ")
        self._build_tab_timed_events()

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, padding=(8, 6))
        footer.pack(side=tk.BOTTOM, fill=tk.X)

        self.lbl_status = ttk.Label(footer, text="Ready", font=("Segoe UI", 9, "italic"))
        self.lbl_status.pack(side=tk.LEFT)

        ttk.Button(footer, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(footer, text="Apply & Save", command=self._on_save_method).pack(side=tk.RIGHT, padx=4)

    # ------------------------------------------------------------------
    # Tab 1: Compounds
    # ------------------------------------------------------------------

    def _build_tab_compounds(self) -> None:
        btn_bar = ttk.Frame(self.tab_compounds)
        btn_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        ttk.Button(btn_bar, text="➕ Add Compound", command=self._on_add_compound).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="✏ Edit Selected", command=self._on_edit_compound).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="➖ Remove Selected", command=self._on_remove_compound).pack(side=tk.LEFT, padx=2)
        ttk.Separator(btn_bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(btn_bar, text="⬆ Move Up", command=lambda: self._on_move_compound(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="⬇ Move Down", command=lambda: self._on_move_compound(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="↕ Sort by RT", command=self._on_sort_compounds_by_rt).pack(side=tk.LEFT, padx=2)

        # Treeview
        columns = (
            "index", "name", "signal", "rt", "abs_win", "rel_win",
            "rf", "curve", "unit", "match", "polarity"
        )
        tree_container = ttk.Frame(self.tab_compounds)
        tree_container.pack(fill=tk.BOTH, expand=True)

        self.comp_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        col_defs = [
            ("index", "#", 40, "center"),
            ("name", "Compound Name", 140, "w"),
            ("signal", "Signal", 70, "center"),
            ("rt", "Exp RT [min]", 85, "e"),
            ("abs_win", "Abs Win [min]", 85, "e"),
            ("rel_win", "Rel Win [%]", 80, "e"),
            ("rf", "Response Factor", 100, "e"),
            ("curve", "Curve Type", 90, "center"),
            ("unit", "Amount Unit", 80, "center"),
            ("match", "Match Mode", 85, "center"),
            ("polarity", "Polarity", 75, "center"),
        ]

        for cid, heading, width, align in col_defs:
            self.comp_tree.heading(cid, text=heading)
            self.comp_tree.column(cid, width=width, anchor=align)

        v_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.comp_tree.yview)
        h_scroll = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.comp_tree.xview)
        self.comp_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.comp_tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)

        self.comp_tree.bind("<Double-1>", lambda e: self._on_edit_compound())
        self.comp_tree.bind("<Delete>", lambda e: self._on_remove_compound())

    # ------------------------------------------------------------------
    # Tab 2: Channel Integration Parameters
    # ------------------------------------------------------------------

    def _build_tab_integration(self) -> None:
        panes = ttk.PanedWindow(self.tab_integration, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        self.param_vars: Dict[str, Dict[str, tk.Variable]] = {}

        for sname, title in [("FID1A", "FID1A Channel Integration Parameters"),
                             ("TCD2B", "TCD2B Channel Integration Parameters")]:
            lf = ttk.LabelFrame(panes, text=f"  {title}  ", padding=12)
            panes.add(lf, weight=1)

            cfg = self.method.signals.get(sname, SignalMethodConfig(signal_name=sname))
            p_dict: Dict[str, tk.Variable] = {
                "slope": tk.StringVar(value=str(cfg.slope_sensitivity)),
                "width": tk.StringVar(value=str(cfg.peak_width)),
                "area_reject": tk.StringVar(value=str(cfg.area_reject)),
                "height_reject": tk.StringVar(value=str(cfg.height_reject)),
                "shoulders": tk.StringVar(value=cfg.shoulders_mode),
                "area_pct_reject": tk.StringVar(value=str(cfg.area_pct_reject)),
            }
            self.param_vars[sname] = p_dict

            rows = [
                ("Slope Sensitivity (counts/min):", p_dict["slope"], None),
                ("Peak Width (min):", p_dict["width"], None),
                ("Area Reject (counts*min):", p_dict["area_reject"], None),
                ("Height Reject (counts):", p_dict["height_reject"], None),
                ("Shoulders Mode:", p_dict["shoulders"], ["OFF", "TANGENT", "SKIM"]),
                ("Area % Reject (%):", p_dict["area_pct_reject"], None),
            ]

            for r_idx, (label_txt, var, options) in enumerate(rows):
                ttk.Label(lf, text=label_txt, font=("Segoe UI", 9)).grid(
                    row=r_idx, column=0, sticky="w", pady=6, padx=(0, 8)
                )
                if options:
                    cb = ttk.Combobox(lf, textvariable=var, values=options, state="readonly", width=14)
                    cb.grid(row=r_idx, column=1, sticky="w", pady=6)
                else:
                    ent = ttk.Entry(lf, textvariable=var, width=16)
                    ent.grid(row=r_idx, column=1, sticky="w", pady=6)

    # ------------------------------------------------------------------
    # Tab 3: Timed Integration Events
    # ------------------------------------------------------------------

    def _build_tab_timed_events(self) -> None:
        panes = ttk.PanedWindow(self.tab_timed_events, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        self.event_trees: Dict[str, ttk.Treeview] = {}

        for sname in ["FID1A", "TCD2B"]:
            frame = ttk.LabelFrame(panes, text=f"  {sname} Timed Integration Events  ", padding=6)
            panes.add(frame, weight=1)

            btn_row = ttk.Frame(frame)
            btn_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

            ttk.Button(
                btn_row,
                text="➕ Add Event",
                command=lambda s=sname: self._on_add_timed_event(s),
            ).pack(side=tk.LEFT, padx=2)
            ttk.Button(
                btn_row,
                text="✏ Edit Event",
                command=lambda s=sname: self._on_edit_timed_event(s),
            ).pack(side=tk.LEFT, padx=2)
            ttk.Button(
                btn_row,
                text="➖ Delete Event",
                command=lambda s=sname: self._on_delete_timed_event(s),
            ).pack(side=tk.LEFT, padx=2)

            cols = ("time", "event", "value", "enabled")
            t_tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse", height=12)
            t_tree.heading("time", text="Time [min]")
            t_tree.heading("event", text="Integration Event")
            t_tree.heading("value", text="Value")
            t_tree.heading("enabled", text="Enabled")

            t_tree.column("time", width=80, anchor="e")
            t_tree.column("event", width=140, anchor="w")
            t_tree.column("value", width=70, anchor="center")
            t_tree.column("enabled", width=65, anchor="center")

            sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=t_tree.yview)
            t_tree.configure(yscrollcommand=sb.set)

            t_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)

            t_tree.bind("<Double-1>", lambda e, s=sname: self._on_edit_timed_event(s))
            t_tree.bind("<Delete>", lambda e, s=sname: self._on_delete_timed_event(s))

            self.event_trees[sname] = t_tree

    # ------------------------------------------------------------------
    # Data Sync & UI Updates
    # ------------------------------------------------------------------

    def _load_method_data_into_ui(self) -> None:
        self.method_name_var.set(self.method.name)
        self._refresh_compounds_tree()
        self._refresh_timed_events_trees()

        # Update integration parameter inputs
        for sname, p_dict in self.param_vars.items():
            cfg = self.method.signals.get(sname)
            if cfg:
                p_dict["slope"].set(str(cfg.slope_sensitivity))
                p_dict["width"].set(str(cfg.peak_width))
                p_dict["area_reject"].set(str(cfg.area_reject))
                p_dict["height_reject"].set(str(cfg.height_reject))
                p_dict["shoulders"].set(str(cfg.shoulders_mode))
                p_dict["area_pct_reject"].set(str(cfg.area_pct_reject))

    def _refresh_compounds_tree(self) -> None:
        for item in self.comp_tree.get_children():
            self.comp_tree.delete(item)

        for comp in self.method.compounds:
            pol_str = "Negative (-)" if comp.is_negative_peak else "Positive (+)"
            self.comp_tree.insert(
                "",
                tk.END,
                values=(
                    comp.index,
                    comp.name,
                    comp.signal,
                    f"{comp.exp_rt_min:.3f}",
                    f"{comp.abs_window_min:.3f}",
                    f"{comp.rel_window_pct:.2f}",
                    f"{getattr(comp, 'response_factor', 1.0):.4f}",
                    getattr(comp, "calib_curve", "Linear"),
                    getattr(comp, "amount_unit", "%"),
                    comp.peak_match,
                    pol_str,
                ),
            )

    def _refresh_timed_events_trees(self) -> None:
        for sname, tree in self.event_trees.items():
            for item in tree.get_children():
                tree.delete(item)
            cfg = self.method.signals.get(sname)
            if not cfg:
                continue
            for ev in cfg.timed_events:
                tree.insert(
                    "",
                    tk.END,
                    values=(
                        f"{ev.time_min:.3f}",
                        ev.event_type,
                        ev.value,
                        "Yes" if ev.enabled else "No",
                    ),
                )

    # ------------------------------------------------------------------
    # Compound Actions
    # ------------------------------------------------------------------

    def _on_add_compound(self) -> None:
        next_idx = len(self.method.compounds) + 1
        default_comp = CompoundDef(
            index=next_idx,
            name=f"Compound_{next_idx}",
            signal="FID1A",
            exp_rt_min=5.0,
            abs_window_min=0.04,
            rel_window_pct=1.0,
            response_factor=1.0,
            calib_curve="Linear",
            amount_unit="%",
            calib_level=1,
            peak_match="Closest",
            is_negative_peak=False,
        )
        comp_edit_dlg = _CompoundEditSubDialog(self, default_comp, is_new=True)
        self.wait_window(comp_edit_dlg)
        if comp_edit_dlg.result:
            self.method.compounds.append(comp_edit_dlg.result)
            self._reindex_compounds()
            self._refresh_compounds_tree()
            self.lbl_status.configure(text=f"Added compound '{comp_edit_dlg.result.name}'.")

    def _on_edit_compound(self) -> None:
        sel = self.comp_tree.selection()
        if not sel:
            return
        idx = self.comp_tree.index(sel[0])
        if idx >= len(self.method.compounds):
            return
        curr_comp = self.method.compounds[idx]
        comp_edit_dlg = _CompoundEditSubDialog(self, curr_comp, is_new=False)
        self.wait_window(comp_edit_dlg)
        if comp_edit_dlg.result:
            self.method.compounds[idx] = comp_edit_dlg.result
            self._refresh_compounds_tree()
            self.lbl_status.configure(text=f"Updated compound '{comp_edit_dlg.result.name}'.")

    def _on_remove_compound(self) -> None:
        sel = self.comp_tree.selection()
        if not sel:
            return
        idx = self.comp_tree.index(sel[0])
        if idx >= len(self.method.compounds):
            return
        comp_name = self.method.compounds[idx].name
        if messagebox.askyesno("Remove Compound", f"Remove compound '{comp_name}'?", parent=self):
            self.method.compounds.pop(idx)
            self._reindex_compounds()
            self._refresh_compounds_tree()
            self.lbl_status.configure(text=f"Removed compound '{comp_name}'.")

    def _on_move_compound(self, delta: int) -> None:
        sel = self.comp_tree.selection()
        if not sel:
            return
        idx = self.comp_tree.index(sel[0])
        new_idx = idx + delta
        if 0 <= new_idx < len(self.method.compounds):
            self.method.compounds[idx], self.method.compounds[new_idx] = (
                self.method.compounds[new_idx],
                self.method.compounds[idx],
            )
            self._reindex_compounds()
            self._refresh_compounds_tree()
            children = self.comp_tree.get_children()
            if children:
                self.comp_tree.selection_set(children[new_idx])

    def _on_sort_compounds_by_rt(self) -> None:
        self.method.compounds.sort(key=lambda c: (c.signal, c.exp_rt_min))
        self._reindex_compounds()
        self._refresh_compounds_tree()
        self.lbl_status.configure(text="Sorted compounds by retention time.")

    def _reindex_compounds(self) -> None:
        for i, c in enumerate(self.method.compounds, start=1):
            c.index = i

    # ------------------------------------------------------------------
    # Timed Events Actions
    # ------------------------------------------------------------------

    def _on_add_timed_event(self, sname: str) -> None:
        self._open_timed_event_subdialog(sname, None)

    def _on_edit_timed_event(self, sname: str) -> None:
        tree = self.event_trees.get(sname)
        if not tree:
            return
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        self._open_timed_event_subdialog(sname, idx)

    def _on_delete_timed_event(self, sname: str) -> None:
        tree = self.event_trees.get(sname)
        if not tree:
            return
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        cfg = self.method.signals.get(sname)
        if cfg and 0 <= idx < len(cfg.timed_events):
            ev = cfg.timed_events.pop(idx)
            self._refresh_timed_events_trees()
            self.lbl_status.configure(text=f"Deleted timed event '{ev.event_type}' on {sname}.")

    def _open_timed_event_subdialog(self, sname: str, event_idx: Optional[int]) -> None:
        cfg = self.method.signals.get(sname)
        if not cfg:
            return
        is_new = (event_idx is None or event_idx >= len(cfg.timed_events))
        curr_ev = TimedEvent(time_min=1.0, event_type="IntegrationOn", value="", enabled=True) if is_new else cfg.timed_events[event_idx]

        sub_dlg = _TimedEventEditSubDialog(self, sname, curr_ev, is_new=is_new)
        self.wait_window(sub_dlg)
        if sub_dlg.result:
            if is_new:
                cfg.timed_events.append(sub_dlg.result)
            else:
                cfg.timed_events[event_idx] = sub_dlg.result
            cfg.timed_events.sort(key=lambda e: e.time_min)
            self._refresh_timed_events_trees()
            self.lbl_status.configure(text=f"{'Added' if is_new else 'Updated'} timed event on {sname}.")

    # ------------------------------------------------------------------
    # Method File Operations & Validation
    # ------------------------------------------------------------------

    def _sync_inputs_to_model(self) -> bool:
        """Validate all UI inputs and sync back to self.method."""
        name = self.method_name_var.get().strip()
        if not name:
            messagebox.showerror("Validation Error", "Method name cannot be empty.", parent=self)
            return False
        self.method.name = name

        # Validate channel integration parameters
        for sname, p_dict in self.param_vars.items():
            cfg = self.method.signals.get(sname)
            if not cfg:
                cfg = SignalMethodConfig(signal_name=sname)
                self.method.signals[sname] = cfg
            try:
                slope = float(p_dict["slope"].get().strip())
                width = float(p_dict["width"].get().strip())
                area_rej = float(p_dict["area_reject"].get().strip())
                h_rej = float(p_dict["height_reject"].get().strip())
                area_pct_rej = float(p_dict["area_pct_reject"].get().strip())
                if slope <= 0 or width <= 0 or area_rej < 0 or h_rej < 0 or area_pct_rej < 0:
                    raise ValueError("Numeric parameters must be positive or non-negative.")
            except ValueError as exc:
                messagebox.showerror(
                    "Validation Error",
                    f"Invalid integration parameters on {sname}: {exc}",
                    parent=self,
                )
                return False

            cfg.slope_sensitivity = slope
            cfg.peak_width = width
            cfg.area_reject = area_rej
            cfg.height_reject = h_rej
            cfg.shoulders_mode = p_dict["shoulders"].get().strip()
            cfg.area_pct_reject = area_pct_rej

        # Validate compounds
        for comp in self.method.compounds:
            if comp.exp_rt_min <= 0:
                messagebox.showerror(
                    "Validation Error",
                    f"Compound '{comp.name}' has invalid retention time {comp.exp_rt_min}. Must be > 0.",
                    parent=self,
                )
                return False
            if comp.abs_window_min < 0 or comp.rel_window_pct < 0:
                messagebox.showerror(
                    "Validation Error",
                    f"Compound '{comp.name}' has negative tolerance windows.",
                    parent=self,
                )
                return False
            if getattr(comp, "response_factor", 1.0) <= 0:
                messagebox.showerror(
                    "Validation Error",
                    f"Compound '{comp.name}' has non-positive response factor.",
                    parent=self,
                )
                return False

        return True

    def _on_new_method(self) -> None:
        if messagebox.askyesno("New Method", "Create a new blank method? Unsaved changes will be discarded.", parent=self):
            self.method = ProcessingMethod(name="Untitled_Method")
            self.method.signals["FID1A"] = SignalMethodConfig(signal_name="FID1A")
            self.method.signals["TCD2B"] = SignalMethodConfig(signal_name="TCD2B")
            self._load_method_data_into_ui()
            self.lbl_status.configure(text="Created new blank method.")

    def _on_open_json(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open Method JSON",
            filetypes=[("Method JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            loaded = ProcessingMethod.load_json(path)
            self.method = loaded
            self._load_method_data_into_ui()
            self.lbl_status.configure(text=f"Loaded method from '{os.path.basename(path)}'.")
        except Exception as exc:
            messagebox.showerror("Error Opening Method", f"Failed to load method JSON:\n{exc}", parent=self)

    def _on_save_method(self) -> None:
        if not self._sync_inputs_to_model():
            return

        if not self.method.source_path or not os.path.exists(os.path.dirname(os.path.abspath(self.method.source_path))):
            self._on_save_as_method()
            return

        try:
            self.method.save_json(self.method.source_path)
            self.lbl_status.configure(text=f"Method saved to '{os.path.basename(self.method.source_path)}'.")
            if self.on_method_saved:
                self.on_method_saved(self.method)
            messagebox.showinfo("Method Saved", f"Method successfully saved to:\n{self.method.source_path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save method:\n{exc}", parent=self)

    def _on_save_as_method(self) -> None:
        if not self._sync_inputs_to_model():
            return

        init_name = f"{self.method.name}.json" if not self.method.name.endswith(".json") else self.method.name
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Method As JSON",
            defaultextension=".json",
            initialfile=init_name,
            filetypes=[("Method JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            self.method.save_json(path)
            self.lbl_status.configure(text=f"Method saved as '{os.path.basename(path)}'.")
            if self.on_method_saved:
                self.on_method_saved(self.method)
            messagebox.showinfo("Method Saved", f"Method successfully saved to:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save method:\n{exc}", parent=self)


class _CompoundEditSubDialog(tk.Toplevel):
    """Modal sub-dialog for adding or modifying a single compound row."""

    def __init__(self, parent: tk.Widget, compound: CompoundDef, is_new: bool = False) -> None:
        super().__init__(parent)
        self.title("Add Compound" if is_new else f"Edit Compound — {compound.name}")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        p_theme = getattr(parent, "theme", DARK_PALETTE)
        self.configure(padx=16, pady=12, bg=p_theme.bg_frame)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self.compound = compound
        self.result: Optional[CompoundDef] = None

        self.name_var = tk.StringVar(value=compound.name)
        self.signal_var = tk.StringVar(value=compound.signal)
        self.rt_var = tk.StringVar(value=f"{compound.exp_rt_min:.3f}")
        self.abs_win_var = tk.StringVar(value=f"{compound.abs_window_min:.3f}")
        self.rel_win_var = tk.StringVar(value=f"{compound.rel_window_pct:.2f}")
        self.rf_var = tk.StringVar(value=f"{getattr(compound, 'response_factor', 1.0):.4f}")
        self.curve_var = tk.StringVar(value=getattr(compound, "calib_curve", "Linear"))
        self.unit_var = tk.StringVar(value=getattr(compound, "amount_unit", "%"))
        self.match_var = tk.StringVar(value=compound.peak_match)
        self.pol_var = tk.StringVar(value="Negative (-)" if compound.is_negative_peak else "Positive (+)")

        fields = [
            ("Compound Name:", self.name_var, None),
            ("Detector Signal:", self.signal_var, ["FID1A", "TCD2B"]),
            ("Expected RT (min):", self.rt_var, None),
            ("Absolute Window (min):", self.abs_win_var, None),
            ("Relative Window (%):", self.rel_win_var, None),
            ("Response Factor:", self.rf_var, None),
            ("Calibration Curve:", self.curve_var, ["Linear", "PointToPoint", "Quadratic"]),
            ("Amount Unit:", self.unit_var, ["%", "ppm", "mmol/g", "mg/L", "area%"]),
            ("Match Mode:", self.match_var, ["Closest", "First", "Highest"]),
            ("Polarity:", self.pol_var, ["Positive (+)", "Negative (-)"]),
        ]

        for r_idx, (label_txt, var, options) in enumerate(fields):
            ttk.Label(self, text=label_txt, font=("Segoe UI", 9)).grid(row=r_idx, column=0, sticky="w", pady=4, padx=(0, 8))
            if options:
                cb = ttk.Combobox(self, textvariable=var, values=options, state="readonly", width=18)
                cb.grid(row=r_idx, column=1, sticky="w", pady=4)
            else:
                ent = ttk.Entry(self, textvariable=var, width=20)
                ent.grid(row=r_idx, column=1, sticky="w", pady=4)

        btn_row = ttk.Frame(self)
        btn_row.grid(row=len(fields), column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_row, text="Save Compound", command=self._on_save).pack(side=tk.RIGHT, padx=4)

        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Invalid Input", "Compound name cannot be blank.", parent=self)
            return

        try:
            rt = float(self.rt_var.get().strip())
            abs_w = float(self.abs_win_var.get().strip())
            rel_w = float(self.rel_win_var.get().strip())
            rf = float(self.rf_var.get().strip())
            if rt <= 0 or abs_w < 0 or rel_w < 0 or rf <= 0:
                raise ValueError("RT and RF must be > 0. Windows must be >= 0.")
        except ValueError as exc:
            messagebox.showerror("Invalid Input", f"Invalid numeric parameter: {exc}", parent=self)
            return

        self.result = CompoundDef(
            index=self.compound.index,
            name=name,
            signal=self.signal_var.get().strip(),
            exp_rt_min=rt,
            abs_window_min=abs_w,
            rel_window_pct=rel_w,
            response_factor=rf,
            calib_curve=self.curve_var.get().strip(),
            amount_unit=self.unit_var.get().strip(),
            calib_level=getattr(self.compound, "calib_level", 1),
            peak_match=self.match_var.get().strip(),
            is_negative_peak=(self.pol_var.get().strip() == "Negative (-)"),
        )
        self.destroy()


class _TimedEventEditSubDialog(tk.Toplevel):
    """Modal sub-dialog for adding or modifying a timed integration event."""

    def __init__(self, parent: tk.Widget, signal_name: str, event: TimedEvent, is_new: bool = False) -> None:
        super().__init__(parent)
        self.title(f"{'Add' if is_new else 'Edit'} Timed Event — {signal_name}")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        p_theme = getattr(parent, "theme", DARK_PALETTE)
        self.configure(padx=16, pady=12, bg=p_theme.bg_frame)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self.event = event
        self.result: Optional[TimedEvent] = None

        self.time_var = tk.StringVar(value=f"{event.time_min:.3f}")
        event_types = [
            "IntegrationOn", "IntegrationOff", "BaselineNow",
            "NegativePeakOn", "NegativePeakOff",
            "SlopeSensitivity", "PeakWidth", "AreaReject", "HeightReject",
            "Integration", "Baseline Now", "Negative Peak"
        ]
        self.type_var = tk.StringVar(value=event.event_type)
        self.val_var = tk.StringVar(value=event.value or "")
        self.en_var = tk.BooleanVar(value=event.enabled)

        ttk.Label(self, text="Retention Time (min):", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(self, textvariable=self.time_var, width=16).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(self, text="Integration Event:", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        cb = ttk.Combobox(self, textvariable=self.type_var, values=event_types, width=20)
        cb.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(self, text="Event Value (Optional):", font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(self, textvariable=self.val_var, width=16).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(self, text="Status:", font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Checkbutton(self, text="Enabled", variable=self.en_var).grid(row=3, column=1, sticky="w", pady=4)

        btn_row = ttk.Frame(self)
        btn_row.grid(row=4, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_row, text="Save Event", command=self._on_save).pack(side=tk.RIGHT, padx=4)

        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_save(self) -> None:
        try:
            t = float(self.time_var.get().strip())
            if t < 0:
                raise ValueError("Time must be >= 0.")
        except ValueError as exc:
            messagebox.showerror("Invalid Input", f"Invalid retention time: {exc}", parent=self)
            return

        ev_type = self.type_var.get().strip()
        if not ev_type:
            messagebox.showerror("Invalid Input", "Event type cannot be blank.", parent=self)
            return

        self.result = TimedEvent(
            time_min=t,
            event_type=ev_type,
            value=self.val_var.get().strip(),
            enabled=self.en_var.get(),
        )
        self.destroy()
