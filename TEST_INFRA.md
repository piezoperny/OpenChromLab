# OpenChromLab Test Infrastructure Specification (TEST_INFRA.md)

## 1. Architectural Overview

The OpenChromLab test harness is an independent, 4-tier opaque-box test framework designed to validate both core chromatography processing algorithms and the Tkinter desktop graphical user interface. The architecture guarantees non-regression of baseline requirements (R1–R4, Features F01–F18) while providing full-spectrum verification for the OpenChromLab enterprise enhancements (R1–R10, Features F19–F30).

```
tests/
├── run_e2e_tests.py                 # Master 4-tier test runner & aggregator
├── test_helpers.py                  # Headless Tkinter session fixtures & synthetic data builders
├── tier1_features/                  # Unit & Feature-level opaque-box coverage (>=5 tests per feature)
│   ├── test_r1_layout.py                    [Baseline R1: Window geometry, toolbar, trees, dialogs]
│   ├── test_r2_navigation.py                [Baseline R2: Box zoom, right-click scale, double-click reset]
│   ├── test_r3_core_engine.py               [Baseline R3: .ch binary parser, negative peaks, NaN guard]
│   ├── test_r4_batch_export.py              [Baseline R4: Batch sequence load, single-sheet Excel export]
│   ├── test_openchromlab_r1_renaming.py     [R1: OpenChromLab titles, headers, launcher, backwards alias]
│   ├── test_openchromlab_r2_channel_selection.py [R2: FID Only, TCD Only, Both split/stacked modes]
│   ├── test_openchromlab_r3_axis_navigation.py   [R3: Y/X axis gutter drag pan & right-click scale]
│   ├── test_openchromlab_r4_theme.py             [R4: Light default, Dark mode toggle, canvas styling]
│   ├── test_openchromlab_r5_method_editor.py     [R5: Scratch method creation, compound table, JSON I/O]
│   ├── test_openchromlab_r6_context_actions.py   [R6: Right-click hit-testing, delete, split, anchor]
│   ├── test_openchromlab_r7_shortcuts.py         [R7: Ctrl+Z undo stack, Entry shield, Esc tool cancel]
│   ├── test_openchromlab_r8_zoom_presets.py      [R8: Canvas zoom capture, method JSON preset serialization]
│   ├── test_openchromlab_r9_launcher_icon.py     [R9: Run_OpenChromLab.bat, multi-res .ico, .lnk shortcut]
│   └── test_openchromlab_r10_curve_events.py    [R10: 2.0px line thickness, timed integration events]
├── tier2_boundaries/                # Boundary, stress, and extreme edge conditions
│   ├── test_boundaries.py                   [Baseline: Zero/flat signals, co-eluting peaks, NaN noise]
│   └── test_openchromlab_boundaries.py      [R1–R10: Negative spans, extreme zooms, empty channels, rapid toggles]
├── tier3_combinations/              # Multi-feature interaction & cross-module workflows
│   ├── test_workflows.py                    [Baseline: Load -> integrate -> modify method -> export Excel]
│   └── test_openchromlab_combinations.py    [R1–R10: Dark theme + single channel + pan/scale; preset save/reload; split+undo]
└── tier4_real_world/                # End-to-end production laboratory workloads
    ├── test_real_dataset.py                 [Baseline: Full 11-injection sequence vs MPZ_Reaction_Summary.xlsx]
    └── test_openchromlab_analyst_workflow.py [R1–R10: 11-step analyst workflow covering launch, theme, method, integration, presets, batch export]
```

---

## 2. Test Execution Hierarchy & Tier Definitions

### Tier 1: Feature Coverage (86 Tests)
Validates individual functional specifications in isolation. Every requirement (R1 through R10) is assigned a dedicated suite containing at least 5 isolated test cases exercising:
- Happy paths with standard laboratory chromatography parameters.
- Contract adherence against data models (`ProcessingMethod`, `CompoundDef`, `ZoomPresetDef`, `ThemePalette`).
- Tkinter GUI component state, geometry allocations, and event dispatch.

### Tier 2: Boundary & Corner Cases (17 Tests)
Stresses the system at mathematical and topological extremes:
- Zero, negative, and inverted time/amplitude ranges.
- Ultra-high magnification (zoom span < 1e-4 min) and extreme canvas compression.
- Empty channels (e.g., TCD channel missing from `.ch` data when toggling channel modes).
- Rapid alternating theme toggles (stressing Tkinter widget color caches).
- Zero-compound methods and corrupted JSON schemas.

### Tier 3: Cross-Feature Combinations (9 Tests)
Simulates concurrent feature interactions:
- Combining Dark Theme with Single-Channel mode (FID or TCD) and Axis Gutter Panning/Scaling.
- Creating a method from scratch, capturing a custom zoom preset, saving to disk, reloading into the UI, and verifying combobox population.
- Performing right-click peak splits on shared extremes followed by `Ctrl+Z` undo stack restoration.
- Toggling channel views during active tool execution and cancelling with `Esc`.

### Tier 4: Real-World Scenarios (5 Tests)
Executes comprehensive end-to-end laboratory workloads:
- Full 11-injection real dataset processing (`MPZHY14_reaction_261015--120F.D` through `130F.D`), verifying area and retention time parity against `MPZ_Reaction_Summary.xlsx`.
- Complete 11-step analyst workflow:
  1. Application launch with initial light theme.
  2. Dark theme toggling and palette verification.
  3. Single-channel inspection (FID1A only full-height allocation).
  4. Custom method creation from scratch with compound table and calibration parameters.
  5. Navigation and custom zoom preset capture.
  6. Method JSON serialization and persistence to disk.
  7. Interactive peak integration and split peak manipulation.
  8. Keyboard undo (`Ctrl+Z`) of integration operations.
  9. Timed integration event configuration and automatic recalculation.
  10. Sequence loading and automated batch reprocessing.
  11. Multi-injection single-sheet Excel report generation (`openpyxl`).

---

## 3. Authoritative Sources of Truth

Every expected outcome in the test suite is strictly derived from authoritative specifications:
1. **Raw Binary Data**:
   - `test-set/MPZHY14_reaction_261015--*.D`: Real dual-channel (FID1A, TCD2B) Agilent ChemStation v179 chromatograms.
2. **Analytical Reference Standards**:
   - `test-set/MPZ_Reaction_Summary.xlsx`: Authoritative quantitative report containing peak retention times, baseline bounds, peak areas, and calculated mole fractions.
3. **Reference Method Schema**:
   - `MPZ_method-2.2.json` and `.pmx` files: Define baseline retention windows, integration threshold events, and compound definitions.
4. **Interface Contracts (`PROJECT.md`)**:
   - `CompoundDef` calibration parameters (`response_factor`, `calib_curve`, `amount_unit`, `calib_level`).
   - `ZoomPresetDef` dictionary structure (`name`, `time_min`, `time_max`, `y_ranges`).
   - `ThemePalette` color tokens (`bg_main`, `bg_canvas`, `trace_fid`, `trace_tcd`, `text_main`, etc.).
   - `DualChromatogramCanvas` spatial hit-testing types (`PEAK_BODY`, `ANCHOR`, `SHARED_EXTREME`).

---

## 4. Test Harness CLI Usage

The master test runner is located at `tests/run_e2e_tests.py`.

```powershell
# Run the entire 4-tier test suite (all 117 tests)
py -3 tests/run_e2e_tests.py

# Run a specific tier only (e.g., Tier 1)
py -3 tests/run_e2e_tests.py --tier 1
py -3 tests/run_e2e_tests.py --tier 2
py -3 tests/run_e2e_tests.py --tier 3
py -3 tests/run_e2e_tests.py --tier 4

# Run with verbose test-by-test output
py -3 tests/run_e2e_tests.py -v

# Milestone Integration Mode: Exit 0 even if pending milestone features fail
py -3 tests/run_e2e_tests.py --allow-pending
```

### Exit Codes:
- `0`: All executed tests passed successfully, OR `--allow-pending` was specified.
- `1`: One or more tests failed or encountered errors (used as CI/Milestone gate).

---

## 5. Progressive Testability & Milestone Integration Gate

The test harness is structured to support concurrent milestone execution without false blockers:
- **Baseline Integrity**: All 46 original baseline tests pass 100% under all conditions.
- **Milestone 5 (Data Models & Launcher)**: Tests in `test_openchromlab_r5_method_editor.py` and `test_openchromlab_r9_launcher_icon.py` validate backend models, icons, and batch scripts independently of the UI.
- **Milestone 6 (Canvas & Rendering)**: Tests in `test_openchromlab_r2_channel_selection.py`, `test_openchromlab_r3_axis_navigation.py`, `test_openchromlab_r6_context_actions.py`, and `test_openchromlab_r10_curve_events.py` validate the canvas directly via simulated Tkinter mouse/canvas events.
- **Milestone 7 (UI Integration & Shortcuts)**: Tests targeting main window wiring, dialog popups, and combobox sync serve as formal acceptance gates. Pending items in M7 produce isolated, descriptive assertion failures that guide final integration.
