# VOT editor toolbar regression repair plan (superseded by menu-bar correction)

> The toolbar-row approach documented below was superseded after the user clarified that VOT must be in the same menu-bar row between Pulses and Alignment. The current implementation and verification are recorded at the end of this document and in `ai/HANDOFF.md` §7.4.

**Goal:** Restore Sound and LongSound editor creation after the VOT toolbar change, keep the editor toolbar action working, preserve the hidden AI TSV bridge, and make source checks and GUI acceptance agree with the intended behavior.

**Known-good reference:** Use local ref public/modern at commit 2f699d8a5382a3965adf364c9e6561a1bcc90291 (2026-09-24 14:19 +0800) as the pre-VOT/C++ baseline. Compare it with 40f2918e2, which introduced the VOT analysis series, and b20d54cee, which moved the action into the SoundEditor toolbar. Do not reset or check out the shared main worktree to the baseline; it contains unrelated user changes. The ref is a historical comparison point only.

**Root cause:** In the toolbar worktree, SoundEditor::v_createMenus called Editor_addCommand(this, U"Query", ...) although the SoundEditor parent does not create a Query menu. Editor_addCommand reports the missing menu and throws; SoundEditor_create then reports “Sound window not created,” so View & Edit fails before the editor opens. The toolbar callback dispatches the hidden VOT command by title, so it does not require a visible menu item.

## Implementation status

The isolated branch fix/vot-editor-toolbar registers the hidden VOT command with EditorMenu_addCommand(editMenu, ...); Sound and LongSound share this SoundEditor class. The layout correction adds a dedicated row below the menu bar, reserves its button height and vertical margins in SoundEditor only, and moves the drawing area down. FunctionEditor defaults to zero extra toolbar height, so other editor layouts stay unchanged. VOT is removed from the bottom zoom toolbar. The source verifier checks this layout contract along with hidden-command registration, toolbar dispatch, and the hidden AI TSV actions. The VOT-only spec and branch handoff describe the same behavior. The LongSound GUI script now uses its View action and checks Editor type: SoundEditor and Object type: LongSound.

The horizontal-placement correction is committed as f1069b815 and merged into modern. It positions the VOT button midway between the live Pulses and Alignment menu-title bounds, and retries after first draw if the toolkit has not allocated menu geometry yet. The button keeps its toolbar-row y coordinate.

The menu-registration fix was merged as cd33f94c4; the top-toolbar layout correction was fast-forwarded into modern as fb9f3d2998c803ac224364687122b374107befcc. The main Praat.exe was rebuilt with `make PRAAT_COMPILER=clang -j16`; the build exited 0. In the main checkout, verify_segment_analysis_templates.py passed, the Python suite passed 544/544, verify_chat_templates.py passed 100/100, and git diff --check passed. The rebuilt executable SHA-256 is D5AE66989169B1739B09DE3BE0EDBCFCE25552922DB86B09F5B7CD64DAF97112; the pre-rebuild executable is backed up at D:\Praat-work\Praat-before-top-vot-toolbar-20260925.exe (SHA-256 B693A6E4BECAE0A5DCDA1881C2F7EE2D7429FE675911D74491C184D882FDF131). The earlier broad Praat batch suite has a recorded relative-path failure in test/fon/texio.praat for texio99.TextGrid.

The main Praat.exe was launched, but the current desktop automation session returned no native app windows (`apps: []`). Consequently, no live visual inspection or toolbar click was possible; top position, resizing/zoom-window visibility, high-DPI visibility, selection defaults, cancel behavior, and Info result display remain unverified in a usable GUI session. The corrected executable was rebuilt successfully (SHA-256 EEED625E0A3BEDF45793FC5A65B2785B6C44187210B51A6F57699ACEC8CFC3F4) and staged at D:\Praat-work\Praat-after-vot-menu-position-20260925.exe. Replacing the main Praat.exe is pending because process 5832 currently has that image loaded; the previous binary is backed up at D:\Praat-work\Praat-before-vot-menu-position-20260925.exe (SHA-256 D5AE66989169B1739B09DE3BE0EDBCFCE25552922DB86B09F5B7CD64DAF97112). Do not stop the running app automatically because it may contain user object state.

## Scope and constraints

- Implement in the isolated VOT toolbar worktree; keep the main checkout and its local changes untouched.
- Preserve the user-requested VOT toolbar behavior for Sound and LongSound.
- Do not create a Query menu or suppress the menu-registration exception.
- Keep the existing Objects-menu VOT action removal and the hidden AI TSV bridge, unless review against the pre-VOT baseline exposes a separate regression.
- Keep the existing unrelated uncommitted changes in the main checkout and worktree intact. The user authorized merging this fix and rebuilding the main Praat.exe; the pre-rebuild binary is backed up outside the repository.

## Repair tasks

1. Correct hidden command registration in foned/SoundEditor.cpp. Keep SoundEditor_Parent::v_createMenus(); register VOT... against the existing Edit menu object (editMenu) using EditorMenu_addCommand and GuiMenu_HIDDEN. Keep the registered callback menu_cb_SoundEditor_VOT and its dispatch by command title. Confirm SoundEditor initialization no longer throws when the toolbar action is registered.
2. Apply the same menu-registration pattern to LongSoundEditor if its toolbar registration uses the nonexistent Query menu. Confirm the parent-created menu object is the correct menu for both editor classes.
3. Update ai/tests/verify_segment_analysis_templates.py. Remove stale expectations that VOT remains a visible Sound/LongSound Objects-menu form or that no VOT command exists in the editor. Assert instead that both editor toolbar callbacks and hidden command registrations exist, and that each object type retains its hidden Write VOT analysis to file... action. Keep the core and generated-template checks.
4. Resolve documentation drift before merge. Current VOT spec says the editor VOT form should be removed and the Objects-menu form retained, while the current user-requested target is the editor toolbar. Update the spec and ai/HANDOFF.md to one behavior contract after the repair is reviewed; preserve the internal TSV bridge description.
5. Add or update focused regression coverage so a source check fails on registration into a nonexistent menu and passes for hidden Edit-menu registration. GUI scripts are excluded from runAllTests_batch.praat, so report their outcome separately.

## Acceptance

### Source and build

- Build Praat from the isolated worktree with the project’s clang build command.
- Run ai/tests/verify_segment_analysis_templates.py and the relevant C++ segment-analysis tests.
- Run the Python unit suite and broad Praat batch suite. Record unrelated known failures separately: test/fon/texio.praat has a relative-path lookup failure for texio99.TextGrid, and test/kar/unicode.praat has an output-string mismatch. Compare against the existing baseline logs; do not attribute these to the menu-registration change without evidence.
- Ensure the source verifier checks both the public editor command and the internal hidden TSV actions; confirm TSV bridge output remains machine-readable and temporary.

### GUI

- Run SoundEditor_GUI_.praat and a LongSound GUI script explicitly opening only LongSound via its View action and asserting Editor type: SoundEditor plus Object type: LongSound. Sound and LongSound use the shared SoundEditor class. The existing batch runner skips GUI-named scripts, so execute them explicitly in a GUI-enabled Praat session. Current execution environment did not expose native windows, so this live acceptance remains pending.
- In both editors, verify View & Edit opens, waveform and spectrogram render, the VOT toolbar action is present, and repeated open/close does not fail.
- Verify VOT selection defaults for full-sound and selected-range cases, cancellation, positive/zero/negative measurements, undefined burst or voicing boundaries, threshold validation, and auto-candidate output labeled for human review.
- Repeat the launch/action smoke test with Chinese and English UI.
- Use real manually annotated Mandarin recordings for scientific review; synthetic samples establish software-path behavior only.

### Artifact provenance

- Record git commit, build command, and SHA-256 for the tested executable. The main target was rebuilt from fb9f3d299 with `make PRAAT_COMPILER=clang -j16`; SHA-256 D5AE66989169B1739B09DE3BE0EDBCFCE25552922DB86B09F5B7CD64DAF97112.
- The replaced main executable is backed up at D:\Praat-work\Praat-before-top-vot-toolbar-20260925.exe (SHA-256 B693A6E4BECAE0A5DCDA1881C2F7EE2D7429FE675911D74491C184D882FDF131).

## Out of scope

- Reworking VOT detection or thresholds without evidence from annotated real recordings.
- Restoring removed comparison editors, comparison APIs, dual-segment TSV output, or unrelated segment measurements.
- Fixing the independent texio and Unicode batch failures as part of this menu regression.

## Menu-bar correction (2026-09-25)

The previous horizontal-position patch searched for Alignment through `Editor_getMenu`, which searches only Editor's registered menu collection. FunctionEditor creates Alignment directly with `GuiMenu_createInWindow`, so that search always returned null. Even with a valid handle, the previous VOT control was still a button in a separate row below the menu bar.

The corrected implementation adds a no-op `FunctionEditor::v_createMenusAfterFunctionAreas` extension point. SoundEditor overrides it to create a native top-level `VOT` menu after SoundAnalysisArea has created Pulses and before FunctionEditor creates Alignment. The visible VOT menu item dispatches the existing hidden Edit command; the menu shares the existing Sound/LongSound VOT form and C++ analysis core. The dedicated toolbar row, plot offset, runtime coordinate lookup, and now-unused GUI positioning helpers have been removed.

The updated source regression failed on the old implementation because the post-area hook was missing, then passed with the corrected menu. The main checkout is on `modern`, commit `b44c24f62`. A CLANG64 build with `make PRAAT_COMPILER=clang -j16` exited 0. The rebuilt `Praat.exe` SHA-256 is `E3955447A6E5E8A2EC70A2E44505219CF1CBEAA1AB24E2A8C8B32407E07CDFEA`; the replaced executable remains backed up at `D:\Praat-work\Praat-before-vot-menu-position-20260925.exe` (SHA-256 `D5AE66989169B1739B09DE3BE0EDBCFCE25552922DB86B09F5B7CD64DAF97112`). The VOT bridge verifier passed, the Python suite passed 544/544, the general chat-template verifier passed 100/100, and `git diff --check` passed.

The rebuilt main program starts and responds with the Praat Objects window. Live menu placement, Sound/LongSound interaction, DPI and resizing, selection defaults, cancellation, and Info output remain visually unverified: the desktop screenshot helper failed twice with `SetIsBorderRequired` / `0x80004002`. Do not report those UI checks as passing.
