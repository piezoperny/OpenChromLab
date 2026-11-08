"""Empirical verification test suite for Milestone 3 (Round 3) Challenger 2.

Focus areas:
1. Default Dark Mode startup (OpenChromLabApp starts in dark mode by default).
2. Clam ttk style engine enforcement (never vista, winnative, or xpnative).
3. Widget styling & flat relief inspection (TNotebook.Tab, Vertical.TScrollbar, Treeview, Treeview.Heading).
4. Runtime theme toggling stability & bidirectional color freshness.
5. MethodEditorDialog inheritance and standalone dark theme defaults.
6. Windows 10/11 dark mode subsystem (enable_windows_dark_mode, enable_windows_dpi_awareness, DwmSetWindowAttribute) safety on all platforms.
"""

import ast
import ctypes
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk
from tkinter import ttk
from typing import List, Set

from agilent_ui.main_window import OpenChromLabApp
from agilent_ui.method_editor import MethodEditorDialog
from agilent_ui.theme import DARK_PALETTE, LIGHT_PALETTE, ThemePalette
import main as main_entry
from tests.test_helpers import get_workspace_root


FORBIDDEN_LIGHT_COLORS: Set[str] = {
    "#FFFFFF",
    "#F0F2F5",
    "#E9EDF4",
    "#D9E1F2",
    "#DCDAD5",
    "#E8EEF5",
    "#D9D9D9",
    "#F8F9FA",
    "#F5F5F5",
    "#FAFAFA",
    "WHITE",
}


def audit_dark_widget_tree(root_widget: tk.Widget) -> List[str]:
    """Recursively audits all descendant widgets for forbidden light backgrounds or 3D raised bevels."""
    issues = []
    stack = [root_widget]
    while stack:
        w = stack.pop()
        w_class = w.winfo_class()
        # Tkinter native widgets (non-ttk) expose 'bg' and 'relief'
        if not w_class.startswith("T") and not w_class.startswith("ttk::"):
            # Check bg
            try:
                bg = str(w.cget("bg")).strip().upper()
                if bg in FORBIDDEN_LIGHT_COLORS:
                    issues.append(f"LIGHT_BG: {w} ({w_class}) bg={bg}")
            except (tk.TclError, AttributeError):
                pass

            # Check relief (for non-Menu widgets, relief must not be raised)
            if not isinstance(w, tk.Menu):
                try:
                    relief = str(w.cget("relief")).strip().lower()
                    if relief == "raised":
                        issues.append(f"RAISED_RELIEF: {w} ({w_class}) relief={relief}")
                except (tk.TclError, AttributeError):
                    pass

        stack.extend(w.winfo_children())
    return issues


def clean_destroy_app(app: tk.Tk) -> None:
    """Cancels pending timer events to avoid Tcl errors on destruction."""
    try:
        for aid in app.tk.eval("after info").split():
            try:
                app.after_cancel(aid)
            except Exception:
                pass
    except Exception:
        pass
    try:
        app.destroy()
    except Exception:
        pass


class TestDefaultThemeStartup(unittest.TestCase):
    """1. Empirical verification that OpenChromLabApp starts in dark mode by default."""

    def setUp(self):
        self.workspace = get_workspace_root()
        self.app = OpenChromLabApp(initial_workspace=self.workspace)
        self.app.withdraw()
        self.app.update_idletasks()

    def tearDown(self):
        clean_destroy_app(self.app)

    def test_startup_theme_attributes(self):
        """Asserts app starts in dark mode by default."""
        self.assertEqual(self.app.current_theme_name, "dark")
        self.assertEqual(self.app.theme, DARK_PALETTE)
        self.assertEqual(self.app.theme.name, "dark")

    def test_startup_root_window_background(self):
        """Asserts root window and top frames match dark palette #0D1117."""
        root_bg = self.app.cget("bg").lower()
        self.assertEqual(root_bg, DARK_PALETTE.bg_app.lower())
        self.assertEqual(root_bg, "#0d1117")

        topbar_bg = self.app.topbar_frame.cget("bg").lower()
        self.assertEqual(topbar_bg, DARK_PALETTE.topbar_bg.lower())
        self.assertEqual(topbar_bg, "#151b26")

        subbar_bg = self.app.subbar_frame.cget("bg").lower()
        self.assertEqual(subbar_bg, DARK_PALETTE.subbar_bg.lower())
        self.assertEqual(subbar_bg, "#18202c")

    def test_startup_canvas_palette(self):
        """Asserts dual chromatogram canvas starts with dark palette."""
        canvas = self.app.chrom_canvas
        self.assertEqual(canvas.theme, DARK_PALETTE)
        self.assertEqual(canvas.theme.canvas_bg.lower(), "#0d1117")
        self.assertEqual(canvas.canvas.cget("bg").lower(), "#0d1117")

    def test_startup_theme_toggle_button_label(self):
        """When in dark mode, toggle button should offer switching to Light Mode."""
        self.assertIn("Light Mode", self.app.btn_theme_toggle.cget("text"))

    def test_launch_without_arguments_signature(self):
        """Tests whether OpenChromLabApp can be instantiated without arguments.
        
        The dispatch prompt states:
        'Launches OpenChromLabApp without arguments and asserts it starts in dark mode by default'
        If OpenChromLabApp.__init__() requires initial_workspace without a default, this test
        documents whether it succeeds or fails with TypeError.
        """
        try:
            no_arg_app = OpenChromLabApp()
            try:
                self.assertEqual(no_arg_app.current_theme_name, "dark")
            finally:
                clean_destroy_app(no_arg_app)
        except TypeError as err:
            self.fail(f"DEFECT: OpenChromLabApp() requires positional argument: {err}")


class TestClamTtkStyleEngineEnforcement(unittest.TestCase):
    """2. Empirical verification that clam ttk style engine is enforced unconditionally."""

    def setUp(self):
        self.workspace = get_workspace_root()
        self.app = OpenChromLabApp(initial_workspace=self.workspace)
        self.app.withdraw()
        self.app.update_idletasks()

    def tearDown(self):
        clean_destroy_app(self.app)

    def test_clam_engine_active_at_runtime(self):
        """Asserts style.theme_use() is 'clam'."""
        style = ttk.Style(self.app)
        current_theme = style.theme_use()
        self.assertEqual(current_theme, "clam", f"Expected 'clam' theme engine, got '{current_theme}'")

    def test_clam_engine_preserved_after_theme_toggle(self):
        """Asserts style engine remains 'clam' after toggling to light and back to dark."""
        style = ttk.Style(self.app)
        self.app.set_theme("light")
        self.assertEqual(style.theme_use(), "clam")
        self.app.set_theme("dark")
        self.assertEqual(style.theme_use(), "clam")

    def test_clam_replaces_retro_theme_if_previously_set(self):
        """Adversarial check: if a retro theme was active, _setup_styles forces 'clam'."""
        style = ttk.Style(self.app)
        available = style.theme_names()
        for alt_theme in ("alt", "classic", "default"):
            if alt_theme in available:
                style.theme_use(alt_theme)
                self.assertEqual(style.theme_use(), alt_theme)
                self.app._setup_styles()
                self.assertEqual(style.theme_use(), "clam", f"Failed to restore 'clam' from '{alt_theme}'")
                break

    def test_mock_windows_theme_names_never_selects_vista_or_winnative(self):
        """Adversarial check: mock Windows theme list containing vista and winnative."""
        mock_themes = ("winnative", "vista", "xpnative", "clam", "default", "classic")
        with patch.object(ttk.Style, "theme_names", return_value=mock_themes):
            with patch.object(ttk.Style, "theme_use") as mock_use:
                self.app._setup_styles()
                mock_use.assert_called_with("clam")
                called_args = [call.args[0] for call in mock_use.call_args_list if call.args]
                self.assertNotIn("vista", called_args)
                self.assertNotIn("winnative", called_args)
                self.assertNotIn("xpnative", called_args)

    def test_ast_codebase_scan_no_vista_or_winnative_calls(self):
        """Scans codebase to verify no calls to theme_use('vista') or theme_use('winnative') exist."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_files = [
            os.path.join(repo_root, "agilent_ui", "main_window.py"),
            os.path.join(repo_root, "agilent_ui", "theme.py"),
            os.path.join(repo_root, "agilent_ui", "method_editor.py"),
            os.path.join(repo_root, "main.py"),
        ]
        for fpath in target_files:
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=fpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "theme_use":
                        if node.args and isinstance(node.args[0], ast.Constant):
                            arg_val = str(node.args[0].value).lower()
                            self.assertNotIn(arg_val, ["vista", "winnative", "xpnative"],
                                             f"Forbidden theme '{arg_val}' called in {fpath}:{node.lineno}")


class TestWidgetStylingAndRelief(unittest.TestCase):
    """3. Empirical inspection of TNotebook.Tab, Vertical.TScrollbar, Treeview, and Treeview.Heading."""

    def setUp(self):
        self.workspace = get_workspace_root()
        self.app = OpenChromLabApp(initial_workspace=self.workspace)
        self.app.withdraw()
        self.app.update_idletasks()
        self.style = ttk.Style(self.app)

    def tearDown(self):
        clean_destroy_app(self.app)

    def test_notebook_tab_style(self):
        """Inspects TNotebook and TNotebook.Tab styles for flat borders and correct colors."""
        nb_cfg = self.style.configure("TNotebook")
        self.assertEqual(str(nb_cfg.get("relief", "")).lower(), "flat")
        self.assertEqual(int(nb_cfg.get("borderwidth", 0)), 0)

        tab_cfg = self.style.configure("TNotebook.Tab")
        self.assertEqual(str(tab_cfg.get("relief", "")).lower(), "flat")
        self.assertEqual(int(tab_cfg.get("borderwidth", 0)), 0)
        self.assertEqual(tab_cfg.get("background"), DARK_PALETTE.tab_inactive_bg)
        self.assertEqual(tab_cfg.get("foreground"), DARK_PALETTE.tab_inactive_fg)

        # Tab dynamic mappings for selected state (active cyan/teal highlight)
        tab_maps = dict(self.style.map("TNotebook.Tab"))
        bg_maps = dict(tab_maps.get("background", []))
        fg_maps = dict(tab_maps.get("foreground", []))

        self.assertEqual(bg_maps.get("selected"), DARK_PALETTE.tab_active_bg, "Selected tab must have active teal bg")
        self.assertEqual(fg_maps.get("selected"), DARK_PALETTE.tab_active_fg, "Selected tab must have active cyan fg")

    def test_scrollbar_styles(self):
        """Inspects Vertical.TScrollbar and Horizontal.TScrollbar for flat, gripcount=0, dark trough."""
        for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            sb_cfg = self.style.configure(orient)
            self.assertEqual(str(sb_cfg.get("relief", "")).lower(), "flat", f"{orient} relief not flat")
            self.assertEqual(int(sb_cfg.get("gripcount", 1)), 0, f"{orient} gripcount must be 0")
            self.assertEqual(sb_cfg.get("background"), "#263040", f"{orient} thumb background must be #263040")
            self.assertEqual(sb_cfg.get("troughcolor"), "#11161F", f"{orient} troughcolor must be #11161F")
            self.assertEqual(sb_cfg.get("bordercolor"), "#11161F", f"{orient} bordercolor must be #11161F")

            # Dynamic hover mapping
            sb_maps = dict(self.style.map(orient))
            bg_maps = dict(sb_maps.get("background", []))
            self.assertEqual(bg_maps.get("active"), "#3B82F6", f"{orient} active thumb must be royal blue #3B82F6")
            self.assertEqual(bg_maps.get("pressed"), "#2563EB", f"{orient} pressed thumb must be #2563EB")

    def test_treeview_styles(self):
        """Inspects Treeview style for flat borderless dark theme."""
        tv_cfg = self.style.configure("Treeview")
        self.assertEqual(str(tv_cfg.get("relief", "")).lower(), "flat")
        self.assertEqual(int(tv_cfg.get("borderwidth", 1)), 0)
        self.assertEqual(tv_cfg.get("background"), DARK_PALETTE.tree_bg)
        self.assertEqual(tv_cfg.get("foreground"), DARK_PALETTE.tree_fg)
        self.assertEqual(tv_cfg.get("fieldbackground"), DARK_PALETTE.tree_bg)

        # Selection map
        tv_maps = dict(self.style.map("Treeview"))
        bg_maps = dict(tv_maps.get("background", []))
        fg_maps = dict(tv_maps.get("foreground", []))
        self.assertEqual(bg_maps.get("selected"), DARK_PALETTE.tree_selected_bg)
        self.assertEqual(fg_maps.get("selected"), DARK_PALETTE.tree_selected_fg)

    def test_treeview_heading_styles(self):
        """Inspects Treeview.Heading style for flat relief and dark header background."""
        th_cfg = self.style.configure("Treeview.Heading")
        self.assertEqual(str(th_cfg.get("relief", "")).lower(), "flat")
        self.assertEqual(int(th_cfg.get("borderwidth", 1)), 0)
        self.assertEqual(th_cfg.get("background"), DARK_PALETTE.tree_header_bg)
        self.assertEqual(th_cfg.get("foreground"), DARK_PALETTE.tree_header_fg)

        th_maps = dict(self.style.map("Treeview.Heading"))
        bg_maps = dict(th_maps.get("background", []))
        self.assertEqual(bg_maps.get("active"), DARK_PALETTE.subbar_btn_bg)

    def test_recursive_widget_tree_audit_dark_mode(self):
        """Audits main application widget tree: zero forbidden light backgrounds, zero raised bevels."""
        issues = audit_dark_widget_tree(self.app)
        self.assertEqual(issues, [], f"Found forbidden light colors or raised bevels in Dark Mode:\n" + "\n".join(issues))

    def test_menu_border_and_relief_inspection(self):
        """Inspects menubar and submenus for border width and background."""
        menus = [self.app.menubar, self.app.file_menu, self.app.int_menu, self.app.view_menu, self.app.chan_menu]
        for m in menus:
            self.assertEqual(int(m.cget("bd")), 0, f"Menu {m} has non-zero border: {m.cget('bd')}")
            self.assertEqual(str(m.cget("bg")).upper(), DARK_PALETTE.bg_frame.upper())


class TestRuntimeThemeToggling(unittest.TestCase):
    """4. Empirical testing of runtime toggling between light and dark modes."""

    def setUp(self):
        self.workspace = get_workspace_root()
        self.app = OpenChromLabApp(initial_workspace=self.workspace)
        self.app.withdraw()
        self.app.update_idletasks()

    def tearDown(self):
        clean_destroy_app(self.app)

    def test_toggle_light_and_dark_cycles(self):
        """Cycles dark -> light -> dark -> light -> dark and asserts complete color updates."""
        for cycle in range(3):
            # Switch to Light Mode
            self.app.set_theme("light")
            self.app.update_idletasks()
            self.assertEqual(self.app.current_theme_name, "light")
            self.assertEqual(self.app.theme, LIGHT_PALETTE)
            self.assertEqual(self.app.cget("bg").lower(), LIGHT_PALETTE.bg_app.lower())
            self.assertEqual(self.app.topbar_frame.cget("bg").lower(), LIGHT_PALETTE.topbar_bg.lower())
            self.assertEqual(self.app.subbar_frame.cget("bg").lower(), LIGHT_PALETTE.subbar_bg.lower())
            self.assertEqual(self.app.chrom_canvas.theme, LIGHT_PALETTE)
            self.assertEqual(self.app.chrom_canvas.canvas.cget("bg").lower(), LIGHT_PALETTE.canvas_bg.lower())
            self.assertIn("Dark Mode", self.app.btn_theme_toggle.cget("text"))

            # Switch back to Dark Mode
            self.app.set_theme("dark")
            self.app.update_idletasks()
            self.assertEqual(self.app.current_theme_name, "dark")
            self.assertEqual(self.app.theme, DARK_PALETTE)
            self.assertEqual(self.app.cget("bg").lower(), DARK_PALETTE.bg_app.lower())
            self.assertEqual(self.app.topbar_frame.cget("bg").lower(), DARK_PALETTE.topbar_bg.lower())
            self.assertEqual(self.app.subbar_frame.cget("bg").lower(), DARK_PALETTE.subbar_bg.lower())
            self.assertEqual(self.app.chrom_canvas.theme, DARK_PALETTE)
            self.assertEqual(self.app.chrom_canvas.canvas.cget("bg").lower(), DARK_PALETTE.canvas_bg.lower())
            self.assertIn("Light Mode", self.app.btn_theme_toggle.cget("text"))

    def test_rapid_oscillation_stress(self):
        """Stress-test 30 consecutive theme switches without layout corruption or memory faults."""
        for i in range(30):
            target = "light" if i % 2 == 0 else "dark"
            self.app.set_theme(target)
        self.app.set_theme("dark")
        self.app.update_idletasks()
        self.assertEqual(self.app.current_theme_name, "dark")
        # Ensure widget audit is completely clean after rapid stress
        issues = audit_dark_widget_tree(self.app)
        self.assertEqual(issues, [])

    def test_tag_colors_update_on_theme_toggle(self):
        """Verifies treeview tag configurations update correctly on theme change."""
        self.app.set_theme("light")
        id_bg_light = self.app.peak_tree.tag_configure("identified", "background")
        self.assertEqual(str(id_bg_light).upper(), LIGHT_PALETTE.tag_identified_bg.upper())

        self.app.set_theme("dark")
        id_bg_dark = self.app.peak_tree.tag_configure("identified", "background")
        self.assertEqual(str(id_bg_dark).upper(), DARK_PALETTE.tag_identified_bg.upper())


class TestMethodEditorDialogTheming(unittest.TestCase):
    """5. Empirical inspection of MethodEditorDialog theming and flat styling."""

    def setUp(self):
        self.workspace = get_workspace_root()
        self.app = OpenChromLabApp(initial_workspace=self.workspace)
        self.app.withdraw()
        self.app.update_idletasks()

    def tearDown(self):
        clean_destroy_app(self.app)

    def test_dialog_inherits_dark_theme_from_parent(self):
        """Dialog with parent=app inherits dark theme and flat styling."""
        dlg = MethodEditorDialog(parent=self.app)
        dlg.withdraw()
        dlg.update_idletasks()
        try:
            self.assertEqual(dlg.theme, DARK_PALETTE)
            self.assertEqual(dlg.theme.name, "dark")
            self.assertEqual(dlg.cget("bg").lower(), DARK_PALETTE.bg_app.lower())

            issues = audit_dark_widget_tree(dlg)
            self.assertEqual(issues, [], f"Found forbidden colors or bevels in MethodEditorDialog:\n" + "\n".join(issues))
        finally:
            dlg.destroy()

    def test_dialog_standalone_defaults_to_dark_theme(self):
        """Standalone dialog without parent or explicit theme defaults to DARK_PALETTE."""
        dlg = MethodEditorDialog(parent=None, theme=None)
        dlg.withdraw()
        dlg.update_idletasks()
        try:
            self.assertEqual(dlg.theme, DARK_PALETTE)
            self.assertEqual(dlg.theme.name, "dark")
            self.assertEqual(dlg.cget("bg").lower(), DARK_PALETTE.bg_app.lower())
        finally:
            dlg.destroy()

    def test_dialog_explicit_light_theme(self):
        """Dialog with explicit LIGHT_PALETTE renders with light palette."""
        dlg = MethodEditorDialog(parent=self.app, theme=LIGHT_PALETTE)
        dlg.withdraw()
        dlg.update_idletasks()
        try:
            self.assertEqual(dlg.theme, LIGHT_PALETTE)
            self.assertEqual(dlg.theme.name, "light")
            self.assertEqual(dlg.cget("bg").lower(), LIGHT_PALETTE.bg_app.lower())
        finally:
            dlg.destroy()


class TestWindowsDarkModeSubsystem(unittest.TestCase):
    """6. Empirical verification of Windows 10/11 dark mode subsystem functions."""

    def test_native_platform_execution_safety(self):
        """Calling enable_windows_dark_mode and enable_windows_dpi_awareness on Linux never throws."""
        try:
            main_entry.enable_windows_dark_mode()
            main_entry.enable_windows_dpi_awareness()
        except Exception as e:
            self.fail(f"Native platform execution raised unexpected exception: {e}")

    def test_windows_emulation_success_path(self):
        """Emulates Windows win32 platform where uxtheme and shcore succeed."""
        mock_uxtheme = MagicMock()
        mock_shcore = MagicMock()
        mock_user32 = MagicMock()

        mock_windll = MagicMock()
        mock_windll.uxtheme = mock_uxtheme
        mock_windll.shcore = mock_shcore
        mock_windll.user32 = mock_user32

        with patch("sys.platform", "win32"), patch("ctypes.windll", mock_windll, create=True):
            main_entry.enable_windows_dark_mode()
            # Verify ordinal 135 called with 2 (ForceDark)
            mock_uxtheme.__getitem__.assert_called_with(135)
            mock_uxtheme[135].assert_called_with(2)

            main_entry.enable_windows_dpi_awareness()
            mock_shcore.SetProcessDpiAwareness.assert_called_with(1)

    def test_windows_emulation_exception_safety(self):
        """Emulates Windows win32 platform where uxtheme/shcore raise exceptions (older Windows, wine)."""
        mock_uxtheme = MagicMock()
        mock_uxtheme.__getitem__.side_effect = OSError("Ordinal 135 not found")

        mock_shcore = MagicMock()
        mock_shcore.SetProcessDpiAwareness.side_effect = AttributeError("No SetProcessDpiAwareness")

        mock_user32 = MagicMock()
        mock_user32.SetProcessDPIAware.side_effect = OSError("SetProcessDPIAware failed")

        mock_windll = MagicMock()
        mock_windll.uxtheme = mock_uxtheme
        mock_windll.shcore = mock_shcore
        mock_windll.user32 = mock_user32

        with patch("sys.platform", "win32"), patch("ctypes.windll", mock_windll, create=True):
            try:
                main_entry.enable_windows_dark_mode()
                main_entry.enable_windows_dpi_awareness()
            except Exception as e:
                self.fail(f"Windows exception handler failed to swallow error: {e}")

    def test_windows_dwm_dark_titlebar_in_app_init(self):
        """Tests that DwmSetWindowAttribute is invoked safely under sys.platform == 'win32'."""
        mock_dwmapi = MagicMock()
        mock_user32 = MagicMock()
        mock_user32.GetParent.return_value = 12345

        mock_windll = MagicMock()
        mock_windll.dwmapi = mock_dwmapi
        mock_windll.user32 = mock_user32

        with patch("sys.platform", "win32"), patch("ctypes.windll", mock_windll, create=True):
            workspace = get_workspace_root()
            app = OpenChromLabApp(initial_workspace=workspace)
            app.withdraw()
            try:
                # DwmSetWindowAttribute(hwnd, 20, byref(val), 4)
                mock_dwmapi.DwmSetWindowAttribute.assert_called()
                call_args = mock_dwmapi.DwmSetWindowAttribute.call_args[0]
                self.assertEqual(call_args[0], 12345)
                self.assertEqual(call_args[1], 20)  # DWMWA_USE_IMMERSIVE_DARK_MODE
                self.assertEqual(call_args[3], 4)   # sizeof(c_int)
            finally:
                clean_destroy_app(app)


if __name__ == "__main__":
    unittest.main()
