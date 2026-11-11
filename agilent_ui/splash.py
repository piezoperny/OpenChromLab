"""
OpenChromLab Splash Screen and Version Information
Displays a modern 2-second frameless loading screen with cute logo, version badge,
and progress animation before revealing the primary application window.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from agilent_ui.theme import DARK_PALETTE, apply_windows_dark_titlebar

APP_VERSION = "1.1.0"
APP_TITLE = "OpenChromLab"


class SplashScreen(tk.Toplevel):
    """
    Modern frameless splash screen displayed for ~2 seconds during startup.
    """

    def __init__(
        self,
        parent: tk.Tk,
        on_complete: Callable[[], None],
        duration_ms: int = 2000,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.on_complete = on_complete
        self.duration_ms = duration_ms

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#0F172A", highlightthickness=1, highlightbackground="#38BDF8")

        # Dimensions & Center on Screen
        w, h = 460, 290
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(repo_root, "OpenChromLab.ico")
        apply_windows_dark_titlebar(self, ico_path)

        self._logo_image = None
        self._build_ui(repo_root)

        # Progress animation steps
        self._step = 0
        self._total_steps = 40
        self._step_interval = max(20, duration_ms // self._total_steps)
        self._animate_progress()

    def _build_ui(self, repo_root: str) -> None:
        main_box = tk.Frame(self, bg="#0F172A", padx=20, pady=20)
        main_box.pack(fill=tk.BOTH, expand=True)

        # 1. Cute Logo
        logo_path = os.path.join(repo_root, "agilent_ui", "logo.png")
        if os.path.exists(logo_path):
            try:
                from PIL import Image, ImageTk
                pil_img = Image.open(logo_path).resize((96, 96), Image.Resampling.LANCZOS)
                self._logo_image = ImageTk.PhotoImage(pil_img)
                lbl_logo = tk.Label(main_box, image=self._logo_image, bg="#0F172A")
                lbl_logo.pack(pady=(4, 8))
            except Exception:
                self._draw_fallback_logo(main_box)
        else:
            self._draw_fallback_logo(main_box)

        # 2. App Title & Version Badge
        hdr_frame = tk.Frame(main_box, bg="#0F172A")
        hdr_frame.pack()

        lbl_title = tk.Label(
            hdr_frame,
            text=APP_TITLE,
            font=("Segoe UI", 16, "bold"),
            fg="#FFFFFF",
            bg="#0F172A",
        )
        lbl_title.pack(side=tk.LEFT)

        lbl_ver = tk.Label(
            hdr_frame,
            text=f"v{APP_VERSION}",
            font=("Segoe UI", 9, "bold"),
            fg="#38BDF8",
            bg="#1E293B",
            padx=6,
            pady=1,
            relief=tk.FLAT,
        )
        lbl_ver.pack(side=tk.LEFT, padx=(8, 0))

        # 3. Subtitle / Product description
        lbl_sub = tk.Label(
            main_box,
            text="Chromatography Data System • Fast Reaction GC",
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg="#0F172A",
        )
        lbl_sub.pack(pady=(2, 14))

        # 4. Status message
        self.lbl_status = tk.Label(
            main_box,
            text="Initializing ChemStation 12-Tone engine...",
            font=("Segoe UI", 8),
            fg="#CBD5E1",
            bg="#0F172A",
        )
        self.lbl_status.pack(anchor="w", padx=10, pady=(0, 4))

        # 5. Glowing progress bar
        self.progress_canvas = tk.Canvas(
            main_box,
            height=6,
            bg="#1E293B",
            highlightthickness=0,
            bd=0,
        )
        self.progress_canvas.pack(fill=tk.X, padx=10)

    def _draw_fallback_logo(self, parent: tk.Widget) -> None:
        cv = tk.Canvas(parent, width=80, height=80, bg="#0F172A", highlightthickness=0)
        cv.pack(pady=(4, 8))
        cv.create_line(10, 65, 70, 65, fill="#94A3B8", width=2)
        cv.create_line(15, 65, 30, 45, 40, 15, 50, 50, 65, 65, fill="#38BDF8", width=3, smooth=True)
        cv.create_oval(37, 10, 43, 16, fill="#F59E0B", outline="")

    def _animate_progress(self) -> None:
        if not self.winfo_exists():
            return
        self._step += 1
        pct = min(1.0, self._step / self._total_steps)

        # Update progress bar fill
        self.progress_canvas.delete("bar")
        cw = self.progress_canvas.winfo_width()
        if cw < 10:
            cw = 400
        bar_w = int(cw * pct)
        self.progress_canvas.create_rectangle(
            0, 0, bar_w, 6,
            fill="#38BDF8",
            outline="",
            tags="bar",
        )

        # Update loading status text
        if pct < 0.35:
            self.lbl_status.configure(text="Initializing ChemStation 12-Tone engine...")
        elif pct < 0.70:
            self.lbl_status.configure(text="Loading reaction methods and zoom presets...")
        elif pct < 0.95:
            self.lbl_status.configure(text="Configuring dual-channel chromatogram canvas...")
        else:
            self.lbl_status.configure(text="Ready!")

        if self._step < self._total_steps:
            self.after(self._step_interval, self._animate_progress)
        else:
            self.after(80, self._finish_splash)

    def _finish_splash(self) -> None:
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_complete:
            self.on_complete()


def launch_with_splash(
    app_factory: Callable[[], tk.Tk],
    show_splash: bool = True,
    duration_ms: int = 2000,
) -> None:
    """
    Launch the application with a 2-second splash screen, or launch immediately if splash is disabled.
    """
    if not show_splash or "--no-splash" in sys.argv:
        app = app_factory()
        app.mainloop()
        return

    # Create root initially withdrawn so splash can show cleanly
    root = tk.Tk()
    root.withdraw()

    # Pre-instantiate app hidden behind splash
    app_holder = []

    def _on_splash_done() -> None:
        root.destroy()
        main_app = app_factory()
        main_app.deiconify()
        main_app.mainloop()

    SplashScreen(root, on_complete=_on_splash_done, duration_ms=duration_ms)
    root.mainloop()
