"""Verify the native VOT contract and run Sound/LongSound detector regressions."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import tools  # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = Path(os.environ.get("PRAAT_EXE", str(PROJECT / "Praat.exe")))
CORE_SCRIPT = PROJECT / "test/fon/segmentAcousticCore.praat"
VOT_SCRIPT = PROJECT / "test/fon/segmentAcousticVOT.praat"
CORE_ANALYSIS_HEADER = PROJECT / "fon/SegmentAcousticAnalysis.h"
CORE_ANALYSIS_SOURCE = PROJECT / "fon/SegmentAcousticAnalysis.cpp"
CORE_TEST_SOURCE = PROJECT / "fon/Praat_tests.cpp"
CORE_TEST_ENUMS = PROJECT / "fon/Praat_tests_enums.h"
TRANSLATION_SOURCE = PROJECT / "tools/generate_translation_map.py"
FONED_MAKEFILE = PROJECT / "foned/Makefile"
FONED_MESON = PROJECT / "foned/meson.build"
SOUND_ANALYSIS_AREA_SOURCE = PROJECT / "foned/SoundAnalysisArea.cpp"
SOUND_ACTION_SOURCE = PROJECT / "fon/praat_Sound.cpp"
SOUND_EDITOR_SOURCE = PROJECT / "foned/SoundEditor.cpp"
SOUND_EDITOR_HEADER = PROJECT / "foned/SoundEditor.h"
PRAAT_AI_CONTROL_SOURCE = PROJECT / "sys/PraatAiControl.cpp"
AI_TOOL_SOURCE = PROJECT / "ai/praat_ai/tools.py"
FUNCTION_EDITOR_SOURCE = PROJECT / "foned/FunctionEditor.cpp"
FUNCTION_EDITOR_HEADER = PROJECT / "foned/FunctionEditor.h"
PRAAT_TEST_SOURCE = PROJECT / "fon/Praat_tests.cpp"
PRAAT_TEST_ENUMS = PROJECT / "fon/Praat_tests_enums.h"
EDITOR_SOURCE = PROJECT / "foned/SegmentAcousticEditor.cpp"
EDITOR_HEADER = PROJECT / "foned/SegmentAcousticEditor.h"
def run_praat(script: Path, label: str) -> str:
    if not PRAAT.is_file():
        raise RuntimeError(f"Praat executable is missing: {PRAAT}")
    process = subprocess.run(
        [str(PRAAT), "--FULL-TRUST", "--run", str(script)],
        capture_output=True,
        timeout=60,
    )
    output = (process.stdout + process.stderr).decode("utf-16-le", "replace").replace("\x00", "")
    if process.returncode:
        raise RuntimeError(f"{label} failed with {process.returncode}:\n{output}")
    return output


def read_rows(path: Path) -> dict[str, list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    expected_header = (
        "schema_version\tpraat_version\tsource\tsource_object_id\tsource_file\tsource_start_s"
        "\tsource_end_s\tsource_duration_s\tsource_sample_rate_hz\tsource_channels\tsource_kind"
        "\tanalysis_kind\tparameters\tlanguage\tipa\tspeaker_id\tneighboring_vowel"
        "\tburst_time_s\tvoicing_time_s\tmetric_id\tvalue\tunit\tstatus\treason"
    )
    if not lines or lines[0] != expected_header:
        raise AssertionError(f"{path.name}: unexpected or missing schema header")
    rows: dict[str, list[str]] = {}
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 24:
            raise AssertionError(f"{path.name}: malformed TSV row {line!r}")
        rows[fields[19]] = fields
    return rows


def assert_metric(rows: dict[str, list[str]], metric_id: str, *, unit: str) -> list[str]:
    if metric_id not in rows:
        raise AssertionError(f"missing metric {metric_id!r}")
    row = rows[metric_id]
    if row[0] != "1" or row[11] != "VOT" or row[21] != unit:
        raise AssertionError(f"wrong schema, analysis kind, or unit: {row!r}")
    return row


def verify_comparison_editor_removed() -> None:
    if EDITOR_SOURCE.exists() or EDITOR_HEADER.exists():
        raise AssertionError("comparison editor files are still present")

    build_sources = FONED_MAKEFILE.read_text(encoding="utf-8") + FONED_MESON.read_text(encoding="utf-8")
    if "SegmentAcousticEditor.cpp" in build_sources:
        raise AssertionError("foned build files still register SegmentAcousticEditor")

    sound_area_source = SOUND_ANALYSIS_AREA_SOURCE.read_text(encoding="utf-8")
    removed_editor_items = ("SegmentAcousticEditor", "menu_cb_segmentVOT", "辅音分析", "目标/参照比较")
    remaining = [item for item in removed_editor_items if item in sound_area_source]
    if remaining:
        raise AssertionError(f"Sound editor still references comparison workflow: {remaining!r}")


def verify_vot_only_api() -> None:
    core_code = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CORE_ANALYSIS_HEADER, CORE_ANALYSIS_SOURCE)
    )
    removed_api = (
        "AnalysisKind",
        "compatibilityKeys",
        "ComparisonResult",
        "MetricComparison",
        "FrequencyOverlay",
        "TimeSeries",
        "FrequencySeries",
        "compareCompatibleMetrics",
        "normalizeTimeSeriesForOverlay",
        "interpolateCommonFrequencyGrid",
        "confirmVOTBoundaries",
        "TargetReferenceSegment",
        "SegmentAnalysisSelection",
    )
    remaining = [item for item in removed_api if item in core_code]
    if remaining:
        raise AssertionError(f"comparison/overlay API remains in the VOT core: {remaining!r}")

    required_vot_api = ("analyseVOT", "AnalysisResult_toTsv", "writeSegmentAnalysisTsvAtomically")
    missing = [item for item in required_vot_api if item not in core_code]
    if missing:
        raise AssertionError(f"VOT result APIs are missing from the core: {missing!r}")

    test_code = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CORE_TEST_SOURCE, CORE_TEST_ENUMS, VOT_SCRIPT)
    )
    if "CHECK_SEGMENT_COMPARISON" in test_code or "CheckSegmentComparison" in test_code:
        raise AssertionError("comparison-only C++ tests remain registered or invoked")


def verify_vot_action_contract() -> None:
    source = SOUND_ACTION_SOURCE.read_text(encoding="utf-8")
    compact = re.sub(r"\s+", " ", source)
    for object_class in ("Sound", "LongSound"):
        hidden = (
            f'praat_addAction1 (class{object_class}, 0, U"Write VOT analysis to file...", nullptr, '
            f'GuiMenu_DEPTH_1 | GuiMenu_HIDDEN, WRITE_ONE__{object_class}_VOT_TSV);'
        )
        if compact.count(hidden) != 1:
            raise AssertionError(f"{object_class} must register exactly one hidden AI TSV action")

    if 'U"VOT..."' in compact:
        raise AssertionError("the VOT form must be exposed from the SoundEditor toolbar, not the Objects menu")

    editor_source = SOUND_EDITOR_SOURCE.read_text(encoding="utf-8")
    editor_compact = re.sub(r"\s+", " ", editor_source)
    required_editor_registration = (
        'EditorMenu_addCommand (editMenu, U"VOT...", GuiMenu_HIDDEN, menu_cb_SoundEditor_VOT);'
    )
    if editor_compact.count(required_editor_registration) != 1:
        raise AssertionError("SoundEditor must register one hidden VOT command on its existing Edit menu")
    if 'Editor_addCommand (this, U"Query", U"VOT..."' in editor_compact:
        raise AssertionError("SoundEditor must not register VOT on a nonexistent Query menu")
    required_menu_dispatch = (
        'Editor_doMenuCommand (me, U"VOT...", 0, nullptr, nullptr, nullptr);'
    )
    if editor_compact.count(required_menu_dispatch) != 1:
        raise AssertionError("SoundEditor VOT menu entry must dispatch the hidden VOT command")

    function_editor_header = FUNCTION_EDITOR_HEADER.read_text(encoding="utf-8")
    function_editor_source = FUNCTION_EDITOR_SOURCE.read_text(encoding="utf-8")
    sound_editor_header = SOUND_EDITOR_HEADER.read_text(encoding="utf-8")
    sound_analysis_source = SOUND_ANALYSIS_AREA_SOURCE.read_text(encoding="utf-8")
    function_editor_header_compact = re.sub(r"\s+", " ", function_editor_header)
    if (
        "virtual void v_createMenusAfterFunctionAreas () { }" not in function_editor_header_compact
    ):
        raise AssertionError("FunctionEditor must expose an extension hook after function-area menus")
    menu_creation = function_editor_source.split("void structFunctionEditor :: v_createMenus ()", 1)[1]
    area_menus = menu_creation.find("area -> v_createMenus ();")
    extra_menus = menu_creation.find("our v_createMenusAfterFunctionAreas ();")
    ai_menus = menu_creation.find("createAiMenus (this);")
    ai_menu_builder = function_editor_source.split("void createAiMenus (FunctionEditor me)", 1)[1]
    alignment_menu = ai_menu_builder.find('window, U"Alignment"')
    if min(area_menus, extra_menus, ai_menus, alignment_menu) < 0 or not area_menus < extra_menus < ai_menus:
        raise AssertionError("SoundEditor menus must be created after Pulses and before Alignment")
    if 'Editor_addMenu (our functionEditor(), U"Pulses", 0)' not in re.sub(r"\s+", " ", sound_analysis_source):
        raise AssertionError("SoundAnalysisArea must provide the Pulses menu before the SoundEditor VOT hook")
    if "const int contentTop = Machine_getMenuBarBottom ();" not in function_editor_source:
        raise AssertionError("FunctionEditor drawing area must begin below the menu bar without a VOT toolbar row")
    if "void v_createMenusAfterFunctionAreas () override;" not in sound_editor_header:
        raise AssertionError("SoundEditor must add its VOT menu in the post-area menu hook")
    if (
        'Editor_addMenu (this, U"VOT", 0)' not in editor_compact
        or 'EditorMenu_addCommand (votMenu, U"VOT...", 0, menu_cb_SoundEditor_VOTMenu)' not in editor_compact
        or 'Editor_doMenuCommand (me, U"VOT...", 0, nullptr, nullptr, nullptr);' not in editor_compact
    ):
        raise AssertionError("VOT menu must dispatch the retained hidden Edit command")
    if any(token in function_editor_header + function_editor_source + sound_editor_header + editor_compact
           for token in ("votToolbar", "v_extraTopToolbarHeight", "v_createExtraTopToolbarButtons", "GuiControl_moveX")):
        raise AssertionError("VOT must be a menu-bar entry with no leftover toolbar-positioning code")

    if "AnalysisResult_toInfoSummary" not in CORE_ANALYSIS_HEADER.read_text(encoding="utf-8"):
        raise AssertionError("VOT Info summary formatter is not part of the core contract")
    if "CHECK_SEGMENT_VOT_INFO_SUMMARY" not in PRAAT_TEST_ENUMS.read_text(encoding="utf-8"):
        raise AssertionError("VOT Info summary regression is not registered")
    if "CHECK_SEGMENT_VOT_INFO_SUMMARY" not in PRAAT_TEST_SOURCE.read_text(encoding="utf-8"):
        raise AssertionError("VOT Info summary regression is missing")


def verify_vot_editor_form_contract() -> None:
    editor = re.sub(r"\s+", " ", SOUND_EDITOR_SOURCE.read_text(encoding="utf-8"))
    required_form_strings = (
        'U"Start time (s)"',
        'U"End time (s)"',
        'U"Burst/release time (s)"',
        'U"Voicing onset time (s)"',
        'U"Minimum burst rise (dB)"',
        'U"模型辅助自动"',
        'U"纯声学候选"',
        'U"人工确认"',
        'U"完整上下文音素序列（模型辅助必填，空格分隔）"',
        'U"固定上下文开始时间（s）"',
        'U"固定上下文结束时间（s）"',
        'U"语言代码（模型辅助必填）"',
        'U"目标音素序号（从 0 开始）"',
        'U"人工确认模式需要同时填写爆破释放时刻和起声时刻。"',
    )
    missing = [item for item in required_form_strings if item not in editor]
    if missing:
        raise AssertionError(f"VOT form is missing unified request inputs: {missing!r}")
    if 'BOOLEAN (manualConfirmed' in editor:
        raise AssertionError("VOT mode and manual confirmation must use the shared three-mode request")
    if "PraatAiControl_submitVOTJob" not in editor or "startVotEditorJob" not in editor:
        raise AssertionError("The editor must submit requests through PraatAiControl's shared VOT service")

    translations = TRANSLATION_SOURCE.read_text(encoding="utf-8")
    required_translations = {
        '"VOT analysis"': '"VOT 分析"',
        '"Burst/release time (s)"': '"爆破释放时刻（秒）"',
        '"Voicing onset time (s)"': '"起声时刻（秒）"',
        '"Minimum burst rise (dB)"': '"爆破增幅阈值（dB）"',
        '"Automatically estimated candidate"': '"自动计算的候选值"',
        '"requires manual review"': '"需要人工复核"',
    }
    missing_translations = [
        f"{english} -> {chinese}" for english, chinese in required_translations.items()
        if f"{english}: {chinese}" not in translations
    ]
    if missing_translations:
        raise AssertionError(f"VOT translations are missing from the canonical map: {missing_translations!r}")


def verify_vot_result_repopulation_contract() -> None:
    editor = re.sub(r"\s+", " ", SOUND_EDITOR_SOURCE.read_text(encoding="utf-8"))
    header = re.sub(r"\s+", " ", SOUND_EDITOR_HEADER.read_text(encoding="utf-8"))
    required_editor_items = (
        'MUTABLE_COMMENT (votValueText, U"VOT 值（ms）：尚未计算")',
        'MUTABLE_COMMENT (progressText, U"分析进度：尚未开始")',
        'PraatAiControl_pollVOTJob',
        'applyVotResultJson',
        '"burst_sample_index"',
        '"onset_sample_index"',
        '"vot_ms"',
        '"failure_reason"',
        'vot_gui_text_cb_changed',
        'my votStateSelectionStart',
        'my votStateSelectionEnd',
        'my votNeedsRecalculation',
        'my votFailureReason',
        'my votManualConfirmed',
    )
    missing = [item for item in required_editor_items if item not in editor]
    if missing:
        raise AssertionError(f"VOT calculation results are not fully retained or repopulated: {missing!r}")
    if "const bool sameSelection = my votStateHasSelection &&" not in editor or "if (! sameSelection)" not in editor:
        raise AssertionError("VOT state must be retained for the same selection and cleared for a new one")
    required_editor_state = (
        "votStateHasSelection",
        "votStateSelectionStart",
        "votStateSelectionEnd",
        "votAnalysisStartTime",
        "votAnalysisEndTime",
        "votBurstTime",
        "votVoicingTime",
        "votValueMs",
        "votCalculationAttempted",
        "votValueIsCandidate",
        "votNeedsRecalculation",
        "votFailureReason",
        "votManualConfirmed",
        "votBurstThresholdDb",
        "votPitchFloorHz",
    )
    missing_state = [item for item in required_editor_state if item not in header]
    if missing_state:
        raise AssertionError(f"SoundEditor does not retain per-editor VOT form state: {missing_state!r}")

    core_header = CORE_ANALYSIS_HEADER.read_text(encoding="utf-8")
    for item in (
        "struct VOTDisplayData",
        "AnalysisResult_toVOTDisplayData",
        "VOTBoundaryMode mode",
    ):
        if item not in core_header:
            raise AssertionError(f"Unified VOT display data contract is missing: {item}")

    core_tests = PRAAT_TEST_SOURCE.read_text(encoding="utf-8")
    for item in (
        'AnalysisResult_toVOTDisplayData (candidate, VOTBoundaryMode::estimateCandidates)',
        'AnalysisResult_toVOTDisplayData (partialCandidate,',
        'AnalysisResult_toVOTDisplayData (manualNegative, VOTBoundaryMode::manual)',
        'partialDisplay.failureReason == U"No stable voiced onset."',
        'missingBothDisplay.failureReason == U"No burst was detected.; No stable voiced onset."',
        'manualDisplay.valueMs.value() < 0.0',
    ):
        if item not in core_tests:
            raise AssertionError(f"VOT result-conversion regression is missing: {item}")


def verify_vot_open_calculation_contract() -> None:
    source = SOUND_EDITOR_SOURCE.read_text(encoding="utf-8")
    header = SOUND_EDITOR_HEADER.read_text(encoding="utf-8")
    match = re.search(r"static void menu_cb_SoundEditor_VOT \(.*?\n\}\n\nstatic void menu_cb_SoundEditor_VOTMenu", source, re.S)
    if not match:
        raise AssertionError("Could not isolate the VOT editor callback")
    callback = re.sub(r"\s+", " ", match.group(0))
    if "if (! hasSelection)" not in callback or "请先选择目标片段" not in callback:
        raise AssertionError("The editor VOT entrypoint must require a selected target")
    if "data -> xmin" in callback or "data -> xmax" in callback:
        raise AssertionError("VOT must never substitute the full recording for an absent target")
    if "runVotAnalysis" in source or "praat_Sound_analyseVOT (" in callback:
        raise AssertionError("The editor must not retain a separate synchronous VOT algorithm path")
    apply = callback.split("EDITOR_DO", 1)[1]
    display = source.split("static void appendVotDisplayText", 1)[1].split(
        "static void updateVotFormDisplay", 1
    )[0]
    for item in (
        'my votResultStatus == U"requires_input"',
        'U"需要补充输入"',
        'language is required for model-assisted VOT',
        'phoneme sequence is required for model-assisted VOT',
        "模型辅助自动需要语言代码",
        "模型辅助自动需要完整上下文音素序列",
    ):
        if item not in source:
            raise AssertionError(f"The editor must explain model-assisted VOT input requirements: {item}")
    if display.index('my votResultStatus == U"requires_input"') > display.index('U"需要补充输入"'):
        raise AssertionError("The shared requires_input status must be shown as an actionable prompt")
    control = PRAAT_AI_CONTROL_SOURCE.read_text(encoding="utf-8")
    for item in ("startVotEditorJob (me,", "editorSampleIndexAtTime", "my votMode = mode"):
        if item not in source:
            raise AssertionError(f"Shared VOT request input or snapshot behavior is missing: {item}")
    for item in (
        "praat_LongSound_writeVOTAudioSnapshot",
        "praat_Sound_writeVOTAudioSnapshot",
        "PraatAiControl_submitVOTJob",
		"target_range",
		"alignment_context_range",
		"manual_boundaries",
    ):
        if item not in control:
            raise AssertionError(f"Native VOT request snapshot contract is missing: {item}")
    if "startVotEditorJob (me," not in apply:
        raise AssertionError("Clicking Apply must submit the editor's request")
    if "PraatAiControl_submitVOTJob" not in source:
        raise AssertionError("Editor and AI must use the same request submission API")
    if "std::thread" not in source or "Gui_addWorkProc" not in source:
        raise AssertionError("Alignment must run asynchronously and update the VOT dialog on the UI thread")
    if "my votRequestGeneration != generation" not in source or \
            "my votCurrentJobId != jobId" not in source:
        raise AssertionError("Late VOT worker results must be discarded when a newer request is active")
    if "markVotResultStale" not in source or "PraatAiControl_cancelVOTJob" not in source:
        raise AssertionError("Audio and selection changes must cancel and stale pending VOT results")
    if "model_assisted" not in source or "acoustic_only" not in source or "manual" not in source:
        raise AssertionError("All three supported analysis modes must map into the common request")
    if "(onsetSample - burstSample) * 1000.0 * audio -> dx" not in source:
        raise AssertionError("Manual VOT preview must use the signed sample-index formula")
    if 'str32str (field -> stringValue.get(), U"VOT 值（ms）：")' not in source:
        raise AssertionError("The VOT result label must be located from its immutable form label")
    if "VOT_FORM_BURST_FIELD_INDEX = 3" not in source or \
            "VOT_FORM_VOICING_FIELD_INDEX = 4" not in source:
        raise AssertionError("VOT boundary fields must be addressed by their stable form roles")
    if "static UiField votFormBoundaryField (UiForm form, integer fieldIndex)" not in source:
        raise AssertionError("VOT boundary field lookup must not depend on translated label text")
    if "votFormLabelIs" in source or "votFormFieldWithLabel" in source:
        raise AssertionError("VOT field event routing must not depend on translated labels")
    vot_form_fields = source.split('EDITOR_FORM (U"VOT analysis"', 1)[1].split("EDITOR_OK", 1)[0]
    boundary_field_positions = [
        vot_form_fields.find('U"Start time (s)"'),
        vot_form_fields.find('U"End time (s)"'),
        vot_form_fields.find('U"Burst/release time (s)"'),
        vot_form_fields.find('U"Voicing onset time (s)"'),
    ]
    if min(boundary_field_positions) < 0 or boundary_field_positions != sorted(boundary_field_positions):
        raise AssertionError("VOT form field indices must stay aligned with the four range and boundary fields")
    if "if (field -> text)" not in source:
        raise AssertionError("Changed callbacks must cover all editable request fields")
    if "changedField == votFormBoundaryField (form, VOT_FORM_BURST_FIELD_INDEX)" not in source or \
            "changedField == votFormBoundaryField (form, VOT_FORM_VOICING_FIELD_INDEX)" not in source:
        raise AssertionError("Live updates must recognize boundaries by field identity")
    if "GuiDialog_setOwnerWindow (form -> d_dialogForm, static_cast <GuiWindow> (my windowForm))" not in source:
        raise AssertionError("The VOT form must stay above its SoundEditor while selecting audio")
    dialog_api = (PROJECT / "sys/GuiDialog.cpp").read_text(encoding="utf-8")
    dialog_header = (PROJECT / "sys/Gui.h").read_text(encoding="utf-8")
    if "GuiDialog_setOwnerWindow" not in dialog_header or \
            "SetWindowLongPtr (dialogWindow, GWLP_HWNDPARENT" not in dialog_api:
        raise AssertionError("VOT dialog ownership must be enforced on Windows")
    if "void v_updateText () override;" not in header or "void structSoundEditor :: v_updateText ()" not in source:
        raise AssertionError("Selection changes must invalidate the open VOT result")
    if "void structSoundEditor :: v1_dataChanged (Editor sender)" not in source:
        raise AssertionError("Audio changes must invalidate the open VOT result")
    for item in (
        "GuiText_setChangedCallback (field -> text, vot_gui_text_cb_changed, form)",
        "if (my votMode == 3 && changedBoundary)",
        "updateManualVotFromForm (form, me)",
        "setVotFormBoundaries (my votForm, me)",
    ):
        if item not in source:
            raise AssertionError(f"VOT live update hook is missing: {item}")


def verify_ai_vot_tool_contract() -> None:
    tool = tools.LOCAL_TOOLS.get("vot")
    if tool is None or not callable(getattr(tool, "run", None)):
        raise AssertionError("AI VOT must be registered as an executable local tool")
    if "vot" in tools.TOOL_MAP:
        raise AssertionError("AI VOT still routes through a generated script template")
    source = AI_TOOL_SOURCE.read_text(encoding="utf-8")
    required = (
        "VOTAnalysisService",
        "TSVVOTAcousticAnalyzer",
        "Write VOT audio snapshot:",
        "Analyse VOT audio snapshot:",
        "_request_from_payload",
        "use_cache=False",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise AssertionError(f"AI VOT no longer submits the shared request and native analyzer: {missing!r}")


def verify_vot_editor_context_contract() -> None:
    editor = re.sub(r"\s+", " ", SOUND_EDITOR_SOURCE.read_text(encoding="utf-8"))
    control = re.sub(r"\s+", " ", PRAAT_AI_CONTROL_SOURCE.read_text(encoding="utf-8"))
    if editor.count("PraatAiControl_noteEditorSelection (me, my data()") < 3:
        raise AssertionError("SoundEditor must publish its fixed VOT context on open, edit, and submit")
    if "PraatAiControl_clearEditorVOTContext (me, my data())" not in editor:
        raise AssertionError("Audio edits must clear the old fixed VOT context")
    if "context_start\\tcontext_end" not in control or "std::setprecision (17)" not in control:
        raise AssertionError("AI object context must preserve fixed VOT context at full time precision")
    if "std::optional<double> contextStart = {}" not in (PROJECT / "sys/PraatAiControl.h").read_text(encoding="utf-8"):
        raise AssertionError("PraatAiControl does not expose the optional fixed VOT context")


def main() -> None:
    verify_vot_action_contract()
    verify_vot_editor_form_contract()
    verify_vot_result_repopulation_contract()
    verify_vot_open_calculation_contract()
    verify_ai_vot_tool_contract()
    verify_vot_editor_context_contract()
    core_output_dir = Path.home()
    core_prefix = f"praat-segment-acoustic-core-{uuid.uuid4().hex}"
    core_files = [core_output_dir / f"{core_prefix}-{name}.tsv" for name in ("zero", "negative", "candidates", "longsound")]
    legacy_temp_path = Path(f"{core_files[0]}.tmp")
    core_wave = core_output_dir / f"{core_prefix}.wav"
    with tempfile.TemporaryDirectory(prefix="praat-segment-analysis-") as temporary:
        root = Path(temporary)
        core_script = root / "segmentAcousticCore.praat"
        core_script.write_text(
            CORE_SCRIPT.read_text(encoding="utf-8").replace(
                "praat-segment-acoustic-core", core_prefix
            ),
            encoding="utf-8",
        )
        try:
            core_files[0].write_text("previous successful result", encoding="utf-8")
            legacy_temp_path.write_text("unrelated pre-existing temp file", encoding="utf-8")
            run_praat(core_script, "C++ Sound/LongSound object actions")
            run_praat(VOT_SCRIPT, "C++ VOT acoustic regression")
            verify_comparison_editor_removed()
            verify_vot_only_api()

            core_zero = read_rows(core_files[0])
            zero = assert_metric(core_zero, "vot_ms", unit="ms")
            if float(zero[20]) != 0.0 or zero[22] != "measured":
                raise AssertionError(f"explicit zero was not preserved: {zero!r}")
            if not zero[2] or not zero[3] or zero[5:12] != ["0", "1", "1", "44100", "1", "Sound", "VOT"]:
                raise AssertionError(f"single-source export lost source identity or analysis range: {zero!r}")
            if zero[17:19] != ["0", "0"]:
                raise AssertionError(f"single-source export lost the explicit manual boundaries: {zero!r}")
            if legacy_temp_path.read_text(encoding="utf-8") != "unrelated pre-existing temp file":
                raise AssertionError("analysis export overwrote an unrelated pre-existing .tmp file")

            core_negative = read_rows(core_files[1])
            negative = assert_metric(core_negative, "vot_ms", unit="ms")
            if abs(float(negative[20]) + 20.0) > 1e-8 or negative[22] != "measured":
                raise AssertionError(f"negative VOT was not preserved: {negative!r}")

            long_sound = read_rows(core_files[3])
            long_negative = assert_metric(long_sound, "vot_ms", unit="ms")
            if abs(float(long_negative[20]) + 20.0) > 1e-8:
                raise AssertionError(f"LongSound action changed absolute VOT: {long_negative!r}")

            core_candidate = read_rows(core_files[2])
            missing_candidate = assert_metric(core_candidate, "vot_candidate_ms", unit="ms")
            if missing_candidate[20] or missing_candidate[22] not in {"unavailable", "ambiguous", "target_incomplete"} or not missing_candidate[23]:
                raise AssertionError(f"missing candidate lacks an unavailable reason: {missing_candidate!r}")

        finally:
            for path in core_files:
                path.unlink(missing_ok=True)
            legacy_temp_path.unlink(missing_ok=True)
            core_wave.unlink(missing_ok=True)

    print("SEGMENT_ANALYSIS_NATIVE_PASS: VOT contract and AI local-tool bridge")


if __name__ == "__main__":
    main()
