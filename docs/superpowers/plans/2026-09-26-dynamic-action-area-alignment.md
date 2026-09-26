# Dynamic Action Area Alignment Plan

> **For agentic workers:** Implement this plan task by task in the current authorized session. Keep unrelated working-tree changes untouched.

**Goal:** Make Windows dynamic submenu controls fill their action rows and keep their icon, title, and disclosure arrow in fixed columns.

**Architecture:** Keep outer action-row sizing and spacing unchanged. Give only `dynamicSubmenuBar` zero inner offset and fixed geometry, then use a Windows cascade-button paint flag to draw the existing icon, unpadded title, and disclosure arrow in separate fixed regions.

**Tech Stack:** C++17, Praat Motif emulator/Win32 controls, Windows live-GUI verification with Python `ctypes`.

**Spec:** User-provided requirements for the main window dynamic action area; preserve its outer row height and 5px spacing, avoid global `RowColumn` changes, use fixed icon/title/arrow alignment, retain default-action emphasis.

## Global Constraints

- Change only the dynamic action area path; preserve other `RowColumn` layout behavior.
- Keep native buttons, callbacks, and input behavior.
- Do not change outer action row spacing or default-button emphasis.
- Preserve unrelated pre-existing working-tree changes.

## Review Focus

- Ordinary rows and unrelated row-column widgets: preserve existing geometry; the live check covers parent/button bounds for each dynamic menu row.
- Long and localized submenu names: retain the whole title while keeping the disclosure arrow in a fixed right column; inspect a live screenshot.
- Focused and disabled cascade controls: keep existing interaction and sensitivity; inspect after the layout change.
- Default action button: leave its bold/blue flag and paint path unchanged.
- Window resize: keep each menu button matched to its row; rerun the live geometry check after resizing.

### Task 1: Add a live geometry regression check

**Files:**
- Create: `ai/tests/verify_dynamic_action_layout_live.py`
- Test against: `Praat.exe` and visible Windows child-window bounds

- [x] Enumerate visible child controls under the Praat Objects window and identify `Button` children of visible `rowColumn` controls.
- [x] Assert that each dynamic menu button has exactly the same screen rectangle as its containing row-column.
- [x] Run against the current executable and confirm the expected failure: the button begins at `(+2,+2)` and is 4px narrower than its container.

### Task 2: Correct only the dynamic submenu container geometry

**Files:**
- Modify: `sys/motifEmulator.cpp`, `_motif_manage` and cascade-button creation
- Modify: `sys/GuiMenu.cpp`, Windows/Motif dynamic submenu construction

- [x] Initialize the layout cursor to `(0,0)` only for the `dynamicSubmenuBar` row-column.
- [x] Skip child-driven auto-resize for that named bar and place its cascade child over the complete bar width and height.
- [x] Rerun the live regression check and confirm row and button bounds match; verify other row-column geometry is unchanged.

### Task 3: Draw dynamic cascade content in fixed columns

**Files:**
- Modify: `sys/Gui.h`, private button paint flag
- Modify: `sys/GuiMenu.cpp`, remove alignment-space title mutation on the Windows/Motif path
- Modify: `sys/motifEmulator.cpp`, set the paint flag only for dynamic submenu children
- Modify: `sys/GuiButton.cpp`, draw the cascade icon, title, and arrow separately
- Extend: `ai/tests/verify_dynamic_action_layout_live.py`

- [x] Assert the live child-window title has no alignment-space prefix or embedded trailing `>` marker.
- [x] Reserve one icon column and one right arrow column; left-align every title from a fixed coordinate.
- [x] Preserve the current regular-button rendering and default/attractive emphasis flags.
- [x] Capture and inspect the action area, then rerun geometry and the normal Windows build.

**Verification:** `ai/tests/verify_dynamic_action_layout_live.py` passed at initial size and after resize (10 cascade buttons matched their row bounds; action rows remained 20px high with 5px gaps). The Windows clang build completed successfully. The screenshot at `ai/runtime/dynamic_action_area.png` was visually inspected for fixed icon/title/arrow columns and unchanged default-action emphasis.
