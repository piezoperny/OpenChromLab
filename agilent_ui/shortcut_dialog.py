"""
OpenChromLab - Keyboard Shortcut Management & Configuration Dialog
Allows inspecting, remapping, and persisting application keybindings.
"""

import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, List, Optional

from agilent_ui.theme import DARK_PALETTE, ThemePalette, apply_windows_dark_titlebar

CONFIG_FILENAME = "openchromlab_shortcuts.json"

DEFAULT_SHORTCUTS = {
    "next_injection": {
        "name": "Next Injection",
        "description": "Navigate to next injection while preserving current zoom coordinates",
        "keys": ["<Page_Down>", "<bracketright>", "<Control-Down>"],
        "display": "PageDown / ] / Ctrl+Down",
    },
    "prev_injection": {
        "name": "Previous Injection",
        "description": "Navigate to previous injection while preserving current zoom coordinates",
        "keys": ["<Page_Up>", "<bracketleft>", "<Control-Up>"],
        "display": "PageUp / [ / Ctrl+Up",
    },
    "export_excel": {
        "name": "Export Single-Sheet Excel",
        "description": "Batch export all injections to consolidated Compound_vs_Injections sheet",
        "keys": ["<Control-e>", "<Control-E>"],
        "display": "Ctrl+E",
    },
    "save_manual": {
        "name": "Save Manual Overrides",
        "description": "Save manual integration overrides for current injection to JSON",
        "keys": ["<Control-s>", "<Control-S>"],
        "display": "Ctrl+S",
    },
    "undo": {
        "name": "Undo Integration Change",
        "description": "Revert the most recent manual integration modification",
        "keys": ["<Control-z>", "<Control-Z>"],
        "display": "Ctrl+Z",
    },
    "delete_peak": {
        "name": "Delete Selected Peak",
        "description": "Remove currently selected peak and recalculate baseline",
        "keys": ["<Delete>"],
        "display": "Delete",
    },
    "toggle_maximize": {
        "name": "Maximize / Restore Plot",
        "description": "Hide/restore left sequence panel and bottom data tables for full-screen chromatogram",
        "keys": ["<F10>"],
        "display": "F10",
    },
    "zoom_full": {
        "name": "Zoom Full Chromatogram",
        "description": "Reset time axis to 0–40 min full run",
        "keys": ["<Home>"],
        "display": "Home",
    },
    "autoscale_y": {
        "name": "Auto-Scale Y Axes",
        "description": "Fit FID and TCD vertical scales to currently visible peak extremes",
        "keys": ["<End>"],
        "display": "End",
    },
    "escape": {
        "name": "Cancel / Deselect",
        "description": "Cancel active manual drawing tool or deselect current peak",
        "keys": ["<Escape>"],
        "display": "Escape",
    },
}


def get_shortcuts_config_path() -> str:
    # First look next to main script
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, CONFIG_FILENAME)


def load_shortcuts() -> Dict[str, Dict[str, Any]]:
    path = get_shortcuts_config_path()
    shortcuts = {k: dict(v) for k, v in DEFAULT_SHORTCUTS.items()}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_data = json.load(f)
            for k, v in user_data.items():
                if k in shortcuts:
                    if "keys" in v:
                        shortcuts[k]["keys"] = v["keys"]
                    if "display" in v:
                        shortcuts[k]["display"] = v["display"]
        except Exception:
            pass
    return shortcuts


def save_shortcuts(shortcuts: Dict[str, Dict[str, Any]]) -> bool:
    path = get_shortcuts_config_path()
    try:
        data_to_save = {}
        for k, v in shortcuts.items():
            data_to_save[k] = {
                "name": v.get("name", k),
                "keys": v.get("keys", []),
                "display": v.get("display", ""),
            }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2)
        return True
    except Exception:
        return False


class ShortcutSettingsDialog(tk.Toplevel):
    """
    Dedicated modal dialog for viewing, editing, and remapping keyboard shortcuts.
    """

    def __init__(
        self,
        parent: tk.Tk,
        theme: ThemePalette = DARK_PALETTE,
        on_shortcuts_updated: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.on_shortcuts_updated = on_shortcuts_updated
        self.title("Keyboard Shortcuts & Navigation Settings — OpenChromLab")
        self.geometry("760x520")
        self.minsize(680, 420)
        self.configure(bg=self.theme.bg_frame)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self.shortcuts = load_shortcuts()

        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self) -> None:
        # Header banner
        hdr = tk.Frame(self, bg=self.theme.subbar_bg, padx=14, pady=10)
        hdr.pack(fill=tk.X)

        tk.Label(
            hdr,
            text="⌨  Keyboard Shortcuts & Fast Sequence Navigation",
            font=("Segoe UI", 12, "bold"),
            bg=self.theme.subbar_bg,
            fg=self.theme.fg_app,
        ).pack(anchor="w")

        tk.Label(
            hdr,
            text="Double-click an action or select and click 'Remap Shortcut' to customize keybindings.",
            font=("Segoe UI", 9),
            bg=self.theme.subbar_bg,
            fg=getattr(self.theme, "fg_muted", getattr(self.theme, "axis_text", "#9CA3AF")),
        ).pack(anchor="w", pady=(2, 0))

        # Main tree container
        tree_frame = ttk.Frame(self, padding=12)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("action", "key", "desc")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=12,
        )
        self.tree.heading("action", text="Action / Command")
        self.tree.heading("key", text="Assigned Shortcut")
        self.tree.heading("desc", text="Description")

        self.tree.column("action", width=180, anchor="w", stretch=False)
        self.tree.column("key", width=180, anchor="center", stretch=False)
        self.tree.column("desc", width=340, anchor="w", stretch=True)

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda e: self._on_remap_clicked())

        self._populate_tree()

        # Action button bar
        btn_bar = tk.Frame(self, bg=self.theme.bg_frame, padx=14, pady=10)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM)

        btn_remap = tk.Button(
            btn_bar,
            text="⚡ Remap Selected...",
            font=("Segoe UI", 9, "bold"),
            bg="#2563EB",
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=12,
            pady=4,
            command=self._on_remap_clicked,
            cursor="hand2",
        )
        btn_remap.pack(side=tk.LEFT, padx=(0, 8))

        btn_reset = tk.Button(
            btn_bar,
            text="↺ Reset to Defaults",
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.fg_app,
            activebackground=self.theme.topbar_btn_bg,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=10,
            pady=4,
            command=self._on_reset_defaults,
            cursor="hand2",
        )
        btn_reset.pack(side=tk.LEFT)

        btn_close = tk.Button(
            btn_bar,
            text="Close",
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.fg_app,
            activebackground=self.theme.topbar_btn_bg,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=12,
            pady=4,
            command=self.destroy,
            cursor="hand2",
        )
        btn_close.pack(side=tk.RIGHT)

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for act_id, info in self.shortcuts.items():
            self.tree.insert(
                "",
                tk.END,
                iid=act_id,
                values=(info["name"], info["display"], info["description"]),
            )

    def _on_remap_clicked(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select Shortcut", "Please select an action to remap.", parent=self)
            return
        act_id = sel[0]
        curr_info = self.shortcuts[act_id]

        dlg = _KeyCaptureDialog(self, curr_info["name"], self.theme)
        self.wait_window(dlg)
        if dlg.captured_key:
            tk_seq, display_str = dlg.captured_key
            self.shortcuts[act_id]["keys"] = [tk_seq]
            self.shortcuts[act_id]["display"] = display_str
            save_shortcuts(self.shortcuts)
            self._populate_tree()
            if self.on_shortcuts_updated:
                self.on_shortcuts_updated()

    def _on_reset_defaults(self) -> None:
        if messagebox.askyesno(
            "Reset Shortcuts",
            "Are you sure you want to restore all default keyboard shortcuts?",
            parent=self,
        ):
            self.shortcuts = {k: dict(v) for k, v in DEFAULT_SHORTCUTS.items()}
            save_shortcuts(self.shortcuts)
            self._populate_tree()
            if self.on_shortcuts_updated:
                self.on_shortcuts_updated()


class _KeyCaptureDialog(tk.Toplevel):
    """Small popup modal that captures the next key combination."""

    def __init__(self, parent: tk.Toplevel, action_name: str, theme: ThemePalette) -> None:
        super().__init__(parent)
        self.theme = theme
        self.title("Press New Key Combination")
        self.geometry("420x200")
        self.resizable(False, False)
        self.configure(bg=self.theme.bg_frame, padx=16, pady=16)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self.captured_key: Optional[tuple] = None

        tk.Label(
            self,
            text=f"Remap: {action_name}",
            font=("Segoe UI", 11, "bold"),
            bg=self.theme.bg_frame,
            fg=self.theme.fg_app,
        ).pack(anchor="center", pady=(4, 8))

        self.lbl_status = tk.Label(
            self,
            text="Press any key or combination...\n(e.g., PageDown, Ctrl+N, F4, ])",
            font=("Segoe UI", 10),
            bg=self.theme.bg_frame,
            fg="#60A5FA",
            justify="center",
        )
        self.lbl_status.pack(expand=True, fill=tk.BOTH)

        tk.Button(
            self,
            text="Cancel",
            font=("Segoe UI", 9),
            bg=self.theme.subbar_btn_bg,
            fg=self.theme.fg_app,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            command=self.destroy,
        ).pack(side=tk.BOTTOM)

        self.bind("<KeyPress>", self._on_key)
        self.focus_set()
        self.transient(parent)
        self.grab_set()

    def _on_key(self, event: tk.Event) -> None:
        keysym = event.keysym
        if keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R"):
            return

        ctrl = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        alt = bool(event.state & 0x0008 or event.state & 0x0080)

        parts = []
        if ctrl:
            parts.append("Control")
        if alt:
            parts.append("Alt")
        if shift and len(keysym) > 1:
            parts.append("Shift")
        parts.append(keysym)

        tk_seq = f"<{'-'.join(parts)}>"

        # Human-readable display string
        disp_parts = []
        if ctrl:
            disp_parts.append("Ctrl")
        if alt:
            disp_parts.append("Alt")
        if shift and len(keysym) > 1:
            disp_parts.append("Shift")
        disp_parts.append(keysym)
        display_str = "+".join(disp_parts)

        self.captured_key = (tk_seq, display_str)
        self.destroy()
