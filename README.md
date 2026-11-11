# OpenChromLab

[![Version](https://img.shields.io/badge/version-1.1.0-orange.svg)]()
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey.svg)]()
[![Status](https://img.shields.io/badge/tests-133%2F133%20passing-brightgreen.svg)]()

> **A high-performance, open-source Windows desktop substitute for Agilent OpenLab CDS Data Analysis (v2.7)** tailored for heterogeneous catalysis and reaction gas chromatography workflows (dual-channel FID1A + TCD2B).

---

## ⚡ Highlights & Key Capabilities

- **Fluid 60 FPS Chromatogram Navigation**: Custom level-of-detail (LOD) downsampling algorithm, spatial hash indexing, and transient label suppression during active dragging make panning and zooming silky smooth even with 100,000+ raw data points.
- **Native Immersive Dark & Light Themes**: Sleek graphical interface with modern carbon styling, native Windows 10/11 dark titlebars (`DWMWA_USE_IMMERSIVE_DARK_MODE` and dark caption colors), and instant theme toggling.
- **2-Second Modern Splash Screen**: Cute loading screen with animated progress bar and high-res application artwork while initializing ChemStation engine and user settings.
- **Fast Sequence Review (Keep Zoom View)**: Move between sequence injections with `PageDown` / `PageUp` (or `]` / `[`) without losing your active zoom position. Perfect for reviewing a specific product peak across 40+ runs in seconds.
- **Customizable Shortcuts & Remapping**: Inspect and rebind any application shortcut through the built-in `⌨ Shortcuts` dialog, saved to `openchromlab_shortcuts.json`.
- **Modular Workspace Panels**: Toggle visibility of the Left Sequence Tree, Bottom-Left Plot Overlays card, and Bottom Data Tables directly from the **View** menu. Press `F10` to maximize the chromatogram plot to 100% of the window.
- **ChemStation 12-Tone Integration & Math Engine**:
  - Full support for slope sensitivity, peak width, area/height reject thresholds, and timed events (`IntegrationOn`/`Off`, `BaselineNow`).
  - Automatic valley-drop splitting for co-eluting peaks (`unknown #1`, `CH4`, `C2H4`, `C2H6`).
  - Tangent-skimming for rider peaks on tailing reactants (e.g. `C4H10` on `CH3OH`).
  - Inverted/negative peak integration with polarity-aware matching (calculates positive area for `H2` on `TCD2B` while preventing Argon confusion).
- **Interactive Manual Integration Ribbon**:
  - **Add Peak (`draw_peak`)**: Click and drag baseline. Hold `Shift` to constrain to a perfectly horizontal baseline.
  - **Split Peak (`split_peak`)**: Click on any peak valley or baseline to split co-eluting compounds.
  - **Anchor Adjust Tool (`drag_anchor`)**: Click and drag start/end baseline anchors. Recalculates area, height, baseline codes (`BB`, `BV`), and drop lines in real-time. Hold `Shift` for horizontal baseline lock, or `Alt` for freeform positioning.
  - **Delete Peak**: Delete misidentified or noise peaks with a single keypress (`Delete`).
  - **Undo Stack (`Ctrl+Z`)**: Multi-step undo for all manual integration modifications.
  - Automatic per-injection persistence to `openlab_sub_manual.json`.
- **Method-Tied Zoom Presets**: Custom zoom presets are saved directly inside the analytical method `.json`, so switching reactions automatically loads that reaction's specific retention time windows.
- **Single-Sheet Consolidated Excel Exporter**: Batch exports all sequence runs into a single `Compound_vs_Injections` matrix sheet with dynamic `=SUM()` formulas ready for instant charting in Excel.

---

## 🚀 Quick Start

### 1. Requirements & Portability
* **Windows 10 or 11 (64-bit)**
* **Zero administrator privileges required**: OpenChromLab is 100% portable and self-contained.
* **Auto-Contained Python**: If Python is already installed, OpenChromLab runs immediately using standard library modules. If Python is not detected on a lab computer, double-clicking [`OpenChromLab.bat`](file:///home/antigravity/piezoperny/OpenChromLab/OpenChromLab.bat) automatically sets up an isolated, portable user-space runtime with no admin prompts.

### 2. Launching OpenChromLab
You can launch the program in any of the following ways:

* **Desktop Shortcut**: Double-click [`OpenChromLab.lnk`](file:///home/antigravity/piezoperny/OpenChromLab/OpenChromLab.lnk) (custom high-resolution squircle icon).
* **Double-Click Batch Launcher**: Double-click [`OpenChromLab.bat`](file:///home/antigravity/piezoperny/OpenChromLab/OpenChromLab.bat) (runs cleanly with `pythonw`/`pyw` without a console window).
* **Command line**:
  ```bash
  python main.py
  ```
  *(To bypass the 2-second splash screen: `python main.py --no-splash`)*

---

## ⌨ Keyboard Shortcuts Reference

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| `PageDown` or `]` or `Ctrl+Down` | **Next Injection** | Moves to the next sequence injection while preserving active zoom coordinates |
| `PageUp` or `[` or `Ctrl+Up` | **Previous Injection** | Moves to the previous sequence injection while preserving active zoom coordinates |
| `F10` | **Maximize Plot** | Toggles full-screen chromatogram view (hides sequence and tables) |
| `Ctrl + E` | **Export Excel** | Batch export all sequence injections to a single consolidated Excel sheet |
| `Ctrl + S` | **Save Overrides** | Save current manual integration adjustments to `openlab_sub_manual.json` |
| `Ctrl + Z` | **Undo** | Revert the most recent manual baseline or peak adjustment |
| `Delete` | **Delete Peak** | Remove the selected peak and recalculate baseline |
| `Escape` | **Cancel / Deselect** | Cancel active manual drawing tool or deselect selected peak |
| `Home` | **Full Chromatogram** | Zoom time axis out to full run (0–40 min) |
| `End` | **Auto-Scale Y** | Scale vertical axes to visible peak extremes |
| `Shift` *(Hold while drawing)* | **Level Baseline** | Locks dragged baseline or anchor to a level horizontal line |
| `Alt` *(Hold while dragging)* | **Freeform Anchor** | Bypasses trace snapping for freeform anchor positioning |

*All shortcuts can be remapped anytime via the **`⌨ Shortcuts`** button in the topbar or **`View ▾` -> `Keyboard Shortcuts & Remap...`**.*

---

## 📁 Repository Structure

```
OpenChromLab/
├── OpenChromLab.bat            # Self-contained zero-admin launcher
├── OpenChromLab.ico            # Multi-resolution application icon (16-256px)
├── OpenChromLab.lnk            # Windows desktop shortcut
├── main.py                     # Application entry point & DPI awareness
│
├── agilent_core/               # Chromatography & Math Core Engines
│   ├── ch_reader.py            # Binary .ch parser & OpenLab .rx ground truth reader
│   ├── method_model.py         # Processing method engine (.pmx & .json) & presets
│   ├── integrator.py           # 12-Tone ChemStation engine & manual overrides
│   └── exporter.py             # Single-Sheet consolidated Excel exporter
│
├── agilent_ui/                 # User Interface & Rendering Engine
│   ├── main_window.py          # Primary desktop window & workspace layout
│   ├── chrom_canvas.py         # 60 FPS dual-channel stacked chromatogram canvas
│   ├── theme.py                # Native Windows dark titlebars & color palettes
│   ├── method_editor.py        # Method creation and editing dialog
│   ├── shortcut_dialog.py      # Keyboard shortcut manager & remapping modal
│   ├── about_dialog.py         # Application info, version, and architecture modal
│   ├── splash.py               # 2-second frameless loading splash screen
│   └── logo.png                # High-res cute application logo artwork
│
├── docs/                       # Architecture, test plans & specification docs
│   ├── PROJECT.md              # Complete design specifications & requirements
│   ├── ORIGINAL_REQUEST.md     # Baseline project requirements
│   ├── TEST_INFRA.md           # 4-tier test framework documentation
│   ├── TEST_READY.md           # Verification checklist
│   └── scripts/                # Icon and shortcut automation utilities
│
├── test-set/                   # Real-world validation dataset
│   ├── MPZ_method-2.2.json     # Reference catalysis processing method
│   ├── MPZ_Reaction_Summary.xlsx # Ground-truth reference Excel summary
│   └── MPZHY14_reaction_*.D    # 11 authentic Agilent GC reaction runs
│
└── tests/                      # Automated 4-Tier Test Suite (133 E2E tests)
```

---

## 🧪 Testing & Verification

OpenChromLab includes a comprehensive 4-tier end-to-end verification suite:

```bash
# Run full E2E test suite (133 tests)
python tests/run_e2e_tests.py
```

* **Tier 1 (Feature Coverage):** Tests canvas mouse navigation, ChemStation 12-Tone engine, negative peak detection, zoom presets, theme switching, and Excel export.
* **Tier 2 (Boundary Cases):** Tests zero-peak regions, extreme noisy baselines, and negative peak edge cases.
* **Tier 3 (Combinations):** Tests interactions between manual overrides, auto-integration, and method switching.
* **Tier 4 (Real-World Parity):** Verifies 100% numerical and retention time parity against Agilent OpenLab CDS v2.7 ground truth across real catalysis sequence runs.