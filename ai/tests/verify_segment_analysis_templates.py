"""Run generated VOT templates in Praat and verify the shared C++ TSV contract."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import tools  # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"
CORE_SCRIPT = PROJECT / "test/fon/segmentAcousticCore.praat"
VOT_SCRIPT = PROJECT / "test/fon/segmentAcousticVOT.praat"
COMPARISON_EDITOR_SOURCE = PROJECT / "foned/SegmentAcousticEditor.cpp"
SOUND_ANALYSIS_AREA_SOURCE = PROJECT / "foned/SoundAnalysisArea.cpp"
VOT_SOUND = (
    'Create Sound from formula: "vot-fixture", 1, 0, 0.6, 44100, '
    '~ if x < 0.30 then 0 else if x < 0.33 then 0.3 * randomGauss (0, 1) '
    'else 0.5 * sin (2 * pi * 220 * x) fi fi'
)


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
    expected_header = "schema_version\tanalysis_kind\tmetric_id\tvalue\tunit\tstatus\treason"
    if not lines or lines[0] != expected_header:
        raise AssertionError(f"{path.name}: unexpected or missing schema header")
    rows: dict[str, list[str]] = {}
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 7:
            raise AssertionError(f"{path.name}: malformed TSV row {line!r}")
        rows[fields[2]] = fields
    return rows


def assert_metric(rows: dict[str, list[str]], metric_id: str, *, unit: str) -> list[str]:
    if metric_id not in rows:
        raise AssertionError(f"missing metric {metric_id!r}")
    row = rows[metric_id]
    if row[0] != "1" or row[1] != "VOT" or row[4] != unit:
        raise AssertionError(f"wrong schema, analysis kind, or unit: {row!r}")
    return row


def verify_generated_template(root: Path, name: str, arguments: dict[str, object]) -> dict[str, list[str]]:
    context = tools.ToolContext(
        tools.parse_object_context("id\tclass\tname\tselected\n1\tSound\tvot-fixture\t1\n"),
        root / f"{name}-chat-result.tsv",
        root / f"{name}-chat-state.txt",
    )
    template = tools.render("vot", {"object": 1, **arguments}, context)
    if "Write VOT analysis to file" not in template or "readFile$" not in template:
        raise AssertionError(f"{name}: the template did not call and read the C++ result action")
    if "Filter (pass Hann band)" in template or "To Pitch (ac)" in template:
        raise AssertionError(f"{name}: Python still duplicates the acoustic estimator")
    script = root / f"{name}.praat"
    script.write_text(VOT_SOUND + "\n" + template, encoding="utf-8")
    run_praat(script, name)
    return read_rows(context.result_path.with_suffix(".vot.tsv"))


def verify_comparison_editor(root: Path) -> None:
    editor_source = COMPARISON_EDITOR_SOURCE.read_text(encoding="utf-8")
    sound_area_source = SOUND_ANALYSIS_AREA_SOURCE.read_text(encoding="utf-8")
    required_editor_contract = (
        "GuiFileSelect_getInfileNames",
        "LongSound_open",
        "Sound_readFromSoundFile",
        "classLongSound",
        "Data_copy",
        "GuiOptionMenu_addOption",
        "TargetReferenceSegment_clearReference",
        "TargetReferenceSegment_setTarget",
        "referenceMono = Sound_resample",
        "Spectrogram_paintInside",
        "Sound_draw",
        "TargetReferenceSegment_setReference",
    )
    missing = [fragment for fragment in required_editor_contract if fragment not in editor_source]
    if missing:
        raise AssertionError(f"comparison editor is missing required native operations: {missing!r}")
    if 'U"目标/参照比较..."' not in sound_area_source:
        raise AssertionError("Sound editor does not expose the target/reference comparison command")

    descriptor_script = root / "segmentComparisonDescriptor.praat"
    descriptor_script.write_text(
        'Praat test: "CheckSegmentComparisonDescriptor", "", "", "", ""\n',
        encoding="utf-8",
    )
    run_praat(descriptor_script, "target/reference Sound and LongSound isolation")


def main() -> None:
    core_output_dir = Path.home()
    core_prefix = f"praat-segment-acoustic-core-{uuid.uuid4().hex}"
    core_files = [core_output_dir / f"{core_prefix}-{name}.tsv" for name in ("zero", "negative", "candidates", "longsound")]
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
            run_praat(core_script, "C++ Sound/LongSound object actions")
            run_praat(VOT_SCRIPT, "C++ VOT acoustic regression")
            verify_comparison_editor(root)

            core_zero = read_rows(core_files[0])
            zero = assert_metric(core_zero, "vot_ms", unit="ms")
            if float(zero[3]) != 0.0 or zero[5] != "measured":
                raise AssertionError(f"explicit zero was not preserved: {zero!r}")

            core_negative = read_rows(core_files[1])
            negative = assert_metric(core_negative, "vot_ms", unit="ms")
            if abs(float(negative[3]) + 20.0) > 1e-8 or negative[5] != "measured":
                raise AssertionError(f"negative VOT was not preserved: {negative!r}")

            long_sound = read_rows(core_files[3])
            long_negative = assert_metric(long_sound, "vot_ms", unit="ms")
            if abs(float(long_negative[3]) + 20.0) > 1e-8:
                raise AssertionError(f"LongSound action changed absolute VOT: {long_negative!r}")

            core_candidate = read_rows(core_files[2])
            missing_candidate = assert_metric(core_candidate, "vot_candidate_ms", unit="ms")
            if missing_candidate[3] or missing_candidate[5] != "unavailable" or not missing_candidate[6]:
                raise AssertionError(f"missing candidate lacks an unavailable reason: {missing_candidate!r}")

            generated_zero = verify_generated_template(root, "template-zero", {"burst": 0.0, "voicing": 0.0})
            zero = assert_metric(generated_zero, "vot_ms", unit="ms")
            if float(zero[3]) != 0.0 or zero[5] != "measured":
                raise AssertionError(f"AI template lost explicit zero: {zero!r}")

            generated_negative = verify_generated_template(
                root, "template-negative", {"burst": 0.30, "voicing": 0.28}
            )
            negative = assert_metric(generated_negative, "vot_ms", unit="ms")
            if abs(float(negative[3]) + 20.0) > 1e-8 or negative[5] != "measured":
                raise AssertionError(f"AI template lost negative VOT: {negative!r}")

            generated_auto = verify_generated_template(root, "template-candidates", {})
            burst = assert_metric(generated_auto, "burst_time_candidate", unit="s")
            vot = assert_metric(generated_auto, "vot_candidate_ms", unit="ms")
            if burst[5] not in {"warning", "unavailable"} or vot[5] not in {"warning", "unavailable"}:
                raise AssertionError(f"candidate values are not marked for review: {burst!r}, {vot!r}")
            if (burst[5] == "unavailable" and not burst[6]) or (vot[5] == "unavailable" and not vot[6]):
                raise AssertionError(f"unavailable candidate has no reason: {burst!r}, {vot!r}")
        finally:
            for path in core_files:
                path.unlink(missing_ok=True)
            core_wave.unlink(missing_ok=True)

    print("SEGMENT_ANALYSIS_TEMPLATE_PASS: VOT contract, LongSound, and target/reference isolation")


if __name__ == "__main__":
    main()
