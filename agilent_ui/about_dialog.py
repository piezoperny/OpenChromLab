"""
OpenChromLab About Dialog
Presents application branding, version, beta status, technical architecture,
and university research credits in a sleek modal dialog matching the active theme.
"""

import os
import platform
import sys
import tkinter as tk
from typing import Optional

from agilent_ui.splash import APP_VERSION
from agilent_ui.theme import ThemePalette, apply_windows_dark_titlebar


class AboutDialog(tk.Toplevel):
    """
    Sleek, modern About modal for OpenChromLab with logo, version,
    beta badge, research context, and runtime environment details.
    """

    def __init__(self, parent: tk.Tk, theme: ThemePalette, on_open_shortcuts: Optional[callable] = None) -> None:
        super().__init__(parent)
        self.parent = parent
        self.theme = theme
        self.on_open_shortcuts = on_open_shortcuts

        self.title("About OpenChromLab")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        bg_main = getattr(theme, "bg_app", "#0F172A")
        fg_main = getattr(theme, "fg_app", "#FFFFFF")
        self.configure(bg=bg_main)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self._logo_img = None
        self._build_ui(repo_root, bg_main, fg_main)

        # Center on parent window
        self.update_idletasks()
        w = max(480, self.winfo_reqwidth())
        h = max(440, self.winfo_reqheight())
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")

        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()

    def _build_ui(self, repo_root: str, bg_main: str, fg_main: str) -> None:
        container = tk.Frame(self, bg=bg_main, padx=24, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        # 1. Header with Logo, Title, and Version Badges
        hdr_frame = tk.Frame(container, bg=bg_main)
        hdr_frame.pack(fill=tk.X, pady=(0, 12))

        logo_path = os.path.join(repo_root, "agilent_ui", "logo.png")
        if os.path.exists(logo_path):
            try:
                from PIL import Image, ImageTk
                pil_img = Image.open(logo_path).resize((56, 56), Image.Resampling.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(pil_img)
                lbl_logo = tk.Label(hdr_frame, image=self._logo_img, bg=bg_main)
                lbl_logo.pack(side=tk.LEFT, padx=(0, 14))
            except Exception:
                pass

        title_col = tk.Frame(hdr_frame, bg=bg_main)
        title_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title_row = tk.Frame(title_col, bg=bg_main)
        title_row.pack(anchor="w")

        lbl_app = tk.Label(
            title_row,
            text="OpenChromLab",
            font=("Segoe UI", 16, "bold"),
            fg=fg_main,
            bg=bg_main,
        )
        lbl_app.pack(side=tk.LEFT)

        lbl_ver = tk.Label(
            title_row,
            text=f"v{APP_VERSION}",
            font=("Segoe UI", 9, "bold"),
            fg="#38BDF8",
            bg=self.theme.canvas_bg,
            padx=6,
            pady=1,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
        )
        lbl_ver.pack(side=tk.LEFT, padx=(8, 4))

        is_dark = getattr(self.theme, "name", "").lower() == "dark"
        lbl_beta = tk.Label(
            title_row,
            text="BETA",
            font=("Segoe UI", 8, "bold"),
            fg="#F59E0B",
            bg="#2B1D0E" if is_dark else "#FEF3C7",
            padx=5,
            pady=1,
            bd=0,
            highlightthickness=1,
            highlightbackground="#D97706",
        )
        lbl_beta.pack(side=tk.LEFT)

        lbl_sub = tk.Label(
            title_col,
            text="Open-Source Desktop Chromatography Data System",
            font=("Segoe UI", 9),
            fg=getattr(self.theme, "fg_muted", self.theme.axis_text),
            bg=bg_main,
        )
        lbl_sub.pack(anchor="w", pady=(2, 0))

        # 2. Divider
        div1 = tk.Frame(container, height=1, bg=self.theme.panel_border)
        div1.pack(fill=tk.X, pady=(0, 12))

        # 3. Purpose & Architecture Card
        card = tk.Frame(
            container,
            bg=self.theme.canvas_bg,
            highlightthickness=1,
            highlightbackground=self.theme.panel_border,
            padx=14,
            pady=12,
        )
        card.pack(fill=tk.X, pady=(0, 12))

        lbl_desc = tk.Label(
            card,
            text=(
                "Tailored native substitute for Agilent OpenLab CDS Data Analysis (v2.7) "
                "designed for university reaction catalysis workflows.\n\n"
                "• ChemStation 12-Tone automatic integrator (valley drop, tangent skim, inverted peaks)\n"
                "• Draggable baseline anchors and synchronized shared drop lines\n"
                "• 60 FPS dual-signal canvas (FID1A + TCD2B) with collision-free labels\n"
                "• Single-sheet consolidated Excel export (Compound_vs_Injections)\n"
                "• Zero administrator privileges required, 100% self-contained portable runtime"
            ),
            font=("Segoe UI", 9),
            fg=fg_main,
            bg=self.theme.canvas_bg,
            justify=tk.LEFT,
            anchor="w",
        )
        lbl_desc.pack(fill=tk.X)

        # 4. Runtime Info
        info_frame = tk.Frame(container, bg=bg_main)
        info_frame.pack(fill=tk.X, pady=(0, 14))

        py_ver = platform.python_version()
        os_info = f"{platform.system()} {platform.release()}"
        tk_ver = tk.TkVersion

        lbl_env = tk.Label(
            info_frame,
            text=f"Environment: Python {py_ver} • Tk {tk_ver} • {os_info}",
            font=("Segoe UI", 8),
            fg=getattr(self.theme, "fg_muted", self.theme.axis_text),
            bg=bg_main,
        )
        lbl_env.pack(anchor="w")

        # 5. Bottom Actions
        act_frame = tk.Frame(container, bg=bg_main)
        act_frame.pack(fill=tk.X)

        if self.on_open_shortcuts:
            btn_sc = tk.Button(
                act_frame,
                text="⌨ Shortcuts...",
                command=self._handle_shortcuts,
                font=("Segoe UI", 9),
                bg=self.theme.topbar_btn_bg,
                fg=self.theme.topbar_btn_fg,
                activebackground=self.theme.canvas_bg,
                activeforeground=fg_main,
                bd=0,
                highlightthickness=1,
                highlightbackground=self.theme.panel_border,
                padx=10,
                pady=4,
                cursor="hand2",
            )
            btn_sc.pack(side=tk.LEFT)

        btn_close = tk.Button(
            act_frame,
            text="Close",
            command=self.destroy,
            font=("Segoe UI", 9, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            activeforeground="#FFFFFF",
            bd=0,
            padx=16,
            pady=4,
            cursor="hand2",
        )
        btn_close.pack(side=tk.RIGHT)

    def _handle_shortcuts(self) -> None:
        self.destroy()
        if self.on_open_shortcuts:
            self.on_open_shortcuts()
