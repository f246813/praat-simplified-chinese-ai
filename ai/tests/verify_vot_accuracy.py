"""Run both full VOT entry points and score them against human adjudication."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

AI_ROOT = Path(__file__).resolve().parents[1]
PROJECT = AI_ROOT.parent
sys.path.insert(0, str(AI_ROOT))
sys.path.insert(0, str(AI_ROOT / "tests"))

from praat_ai.sendpraat import CONSUMED_NOTE, message_file_path  # noqa: E402
from praat_ai.vot_accuracy import score_case, summarize_cases, validate_manifest  # noqa: E402


MODE_NAMES = {
    "model_assisted": "模型辅助自动",
    "acoustic_only": "纯声学候选",
    "manual": "人工确认",
}
MODE_LABELS = MODE_NAMES


def _praat_quote(value: str | Path) -> str:
    return '"' + str(value).replace("\\", "/").replace('"', '""') + '"'


def _time_for_sample(sample_index: int, sample_rate_hz: int) -> str:
    """Map a half-open range boundary to Praat's time axis."""
    return format(sample_index / sample_rate_hz, ".17g")


def _time_for_sample_center(sample_index: int, sample_rate_hz: int) -> str:
    """Map a zero-based sample index to Praat's sample-centre time."""
    return format((sample_index + 0.5) / sample_rate_hz, ".17g")


def _run_ai_entrypoint(case: dict[str, Any], audio_path: Path, praat_exe: Path, root: Path) -> dict[str, Any]:
    os.environ["PRAAT_EXE"] = str(praat_exe)
    from praat_ai import tools
    import verify_vot_entrypoints as entrypoint_harness

    entrypoint_harness.PRAAT = praat_exe

    sample_rate = int(case["sample_rate_hz"])
    target_start, target_end = case["target_selection_samples"]
    duration = int(case["sample_count"]) / sample_rate
    context_start = int(case.get("context_start_sample", 0)) / sample_rate
    context_end = int(case.get("context_end_sample", case["sample_count"])) / sample_rate
    audio_name = audio_path.stem
    context = tools.ToolContext(
        tools.parse_object_context(f"id\tclass\tname\tselected\n1\tSound\t{audio_name}\t1\n"),
        root / "ai-result.jsonl",
        root / "chat_state.txt",
    )
    script = f"Read from file: {_praat_quote(audio_path)}"
    environment = entrypoint_harness.TargetPraatEnvironment(root / "ai", script)
    mode = case.get("mode", "acoustic_only")
    arguments: dict[str, Any] = {
        "object": 1,
        "mode": mode,
        "from": target_start / sample_rate,
        "to": target_end / sample_rate,
        "context_from": context_start,
        "context_to": context_end,
        "language": case.get("language", "ja"),
        "transcript": case.get("transcript", ""),
        "phonemes": " ".join(case.get("phonemes", [])),
        "target_phone_index": case.get("target_phone_index", 0),
    }
    if mode == "manual":
        boundaries = case.get("manual_boundaries_samples")
        if not isinstance(boundaries, list) or len(boundaries) != 2:
            raise ValueError("manual cases require manual_boundaries_samples [burst, onset]")
        arguments["burst"] = _time_for_sample_center(int(boundaries[0]), sample_rate)
        arguments["voicing"] = _time_for_sample_center(int(boundaries[1]), sample_rate)
    arguments.update(case.get("parameters", {}))
    return entrypoint_harness.run_ai_vot(arguments, context, environment)


def _run_editor_entrypoint(
    case: dict[str, Any], audio_path: Path, praat_exe: Path, root: Path,
    config_path: Path, timeout_seconds: float
) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("the native SoundEditor entrypoint runner currently requires Windows")
    from praat_ai.sendpraat import deliver, list_windows

    project_dir = root / "editor-project"
    shutil.copytree(AI_ROOT / "praat_ai", project_dir / "praat_ai")
    shutil.copy2(AI_ROOT / "run_ai_control.py", project_dir / "run_ai_control.py")
    (project_dir / "runtime").mkdir()
    diagnostic_path = project_dir / "runtime" / "vot-editor-diagnostic.txt"
    appdata = root / "AppData" / "Roaming"
    appdata.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "APPDATA": str(appdata),
            "PRAAT_AI_PROJECT_DIR": str(project_dir),
            "PRAAT_AI_CONFIG_PATH": str(config_path),
            "PRAAT_AI_VOT_DIAGNOSTIC_FILE": str(diagnostic_path),
            "PYTHONPATH": str(AI_ROOT),
        }
    )
    process = subprocess.Popen(
        [str(praat_exe)], cwd=str(PROJECT), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
    )
    try:
        deadline = time.monotonic() + min(timeout_seconds, 30.0)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"target Praat.exe exited early with code {process.returncode}")
            if any(window.process_id == process.pid for window in list_windows()):
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("target Praat.exe did not open its native window")

        sample_rate = int(case["sample_rate_hz"])
        start_sample, end_sample = case["target_selection_samples"]
        mode = case.get("mode", "acoustic_only")
        if mode not in MODE_NAMES:
            raise ValueError("unsupported VOT mode")
        manual_boundaries = case.get("manual_boundaries_samples")
        if mode == "manual" and (
            not isinstance(manual_boundaries, list) or len(manual_boundaries) != 2
        ):
            raise ValueError("manual cases require manual_boundaries_samples [burst, onset]")
        if mode != "manual" and manual_boundaries is not None:
            raise ValueError("manual_boundaries_samples are only valid in manual mode")
        burst_time, onset_time = (
            (_time_for_sample_center(int(manual_boundaries[0]), sample_rate),
             _time_for_sample_center(int(manual_boundaries[1]), sample_rate))
            if mode == "manual"
            else ("undefined", "undefined")
        )
        parameters = case.get("parameters", {})
        threshold = float(parameters.get("burst_threshold_db", 6.0))
        pitch_floor = float(parameters.get("pitch_floor_hz", 75.0))
        name = audio_path.stem
        script_path = root / "editor-case.praat"
        completion_marker = root / "editor-script-returned.txt"
        script_path.write_text(
            f"Read from file: {_praat_quote(audio_path)}\nView & Edit\n",
            encoding="utf-8",
        )
        # Praat resolves its preference directory through the Windows shell API,
        # while sendpraat uses the caller's APPDATA environment. Keep the caller's
        # real APPDATA here so both sides address the same Message.txt; the Praat
        # child still gets isolated config/project directories below.
        delivered, error = deliver(AI_ROOT, script_path, process_id=process.pid)
        if not delivered:
            raise RuntimeError(error)
        # View & Edit holds the startup script at its event loop. Wait until
        # SoundEditor exists, then send the actual editor command separately.
        editor_title = f"Sound {name}"
        deadline = time.monotonic() + min(timeout_seconds, 30.0)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"target Praat.exe exited while opening SoundEditor (code {process.returncode})")
            if any(
                window.process_id == process.pid
                and editor_title.casefold() in window.title.casefold()
                for window in list_windows()
            ):
                break
            time.sleep(0.1)
        else:
            raise TimeoutError(f"SoundEditor window did not open for {name!r}")

        message_file = message_file_path()
        if message_file is None:
            raise RuntimeError("could not locate Praat sendpraat message file")
        previous_mtime = message_file.stat().st_mtime_ns if message_file.exists() else 0
        script_path.write_text(
            "\n".join(
                (
                    f"editor: {_praat_quote('Sound ' + name)}",
                    f"Select: {_time_for_sample(start_sample, sample_rate)}, {_time_for_sample(end_sample, sample_rate)}",
                    "VOT: "
                    f"{_time_for_sample(start_sample, sample_rate)}, "
                    f"{_time_for_sample(end_sample, sample_rate)}, {burst_time}, {onset_time}, "
                    f"{_praat_quote(MODE_LABELS[mode])}, "
                    f"{_time_for_sample(int(case.get('context_start_sample', 0)), sample_rate)}, "
                    f"{_time_for_sample(int(case.get('context_end_sample', case['sample_count'])), sample_rate)}, "
                    f"{_praat_quote(case.get('language', 'ja'))}, "
                    f"{_praat_quote(case.get('transcript', ''))}, "
                    f"{_praat_quote(' '.join(case.get('phonemes', [])))}, "
                    f"{int(case.get('target_phone_index', 0))}, {threshold:.17g}, {pitch_floor:.17g}",
                    "endeditor",
                    f"writeFileLine: {_praat_quote(completion_marker)}, \"VOT script returned\", info$",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        delivered, error = deliver(AI_ROOT, script_path, process_id=process.pid)
        if not delivered:
            raise RuntimeError(error)
        job_root = project_dir / "runtime" / "vot_jobs"
        deadline = time.monotonic() + timeout_seconds
        latest: Path | None = None
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            jobs = list(job_root.glob("vot-*") if job_root.exists() else [])
            if jobs:
                latest = max(jobs, key=lambda item: item.stat().st_mtime_ns)
                state_path = latest / "state.json"
                if state_path.is_file():
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if state.get("state") in {"completed", "failed", "cancelled"}:
                        break
            elif (
                message_file.exists()
                and message_file.stat().st_mtime_ns > previous_mtime
                and CONSUMED_NOTE in message_file.read_text(encoding="utf-8")
                and time.monotonic() + timeout_seconds - deadline > 5.0
            ):
                native_windows = [
                    window.title for window in list_windows()
                    if window.process_id == process.pid and window.title
                ]
                script_output = (
                    completion_marker.read_text(encoding="utf-8", errors="replace").strip()
                    if completion_marker.is_file()
                    else ""
                )
                native_error = (
                    diagnostic_path.read_text(encoding="utf-8", errors="replace").strip()
                    if diagnostic_path.is_file()
                    else "<native callback did not report a diagnostic>"
                )
                raise RuntimeError(
                    "SoundEditor VOT command was consumed without creating a job; "
                    "check its form arguments and target executable build; "
                    f"script_output={script_output!r}; native_error={native_error!r}; "
                    f"open native windows: {native_windows!r}"
                )
            time.sleep(0.1)
        if latest is None or not state:
            raise TimeoutError("SoundEditor did not create a VOT job")
        result = state.get("result")
        if result is None:
            raise RuntimeError(state.get("error") or "SoundEditor VOT job completed without a result")
        return result
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def run_full_entrypoints(
    case: dict[str, Any], audio_path: Path, praat_exe: Path, root: Path,
    config_path: Path, timeout_seconds: float
) -> dict[str, dict[str, Any]]:
    """Run the actual SoundEditor command and registered AI tool for one case."""

    results: dict[str, dict[str, Any]] = {}
    for name, runner in (
        (
            "editor",
            lambda: _run_editor_entrypoint(
                case, audio_path, praat_exe, root / "editor", config_path, timeout_seconds
            ),
        ),
        ("ai", lambda: _run_ai_entrypoint(case, audio_path, praat_exe, root / "ai-run")),
    ):
        try:
            results[name] = runner()
        except Exception as error:
            results[name] = {
                "status": "harness_failed",
                "failure_reason": f"{type(error).__name__}: {error}",
            }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--praat-exe", type=Path, required=True)
    parser.add_argument("--alignment-config", type=Path, default=AI_ROOT / "ai_config.json")
    parser.add_argument("--entrypoints", choices=("full",), default="full")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()
    if not args.manifest.is_file():
        print(f"VOT_ACCURACY_UNVERIFIED: gold manifest not found: {args.manifest}")
        return 2
    if not args.praat_exe.is_file():
        print(f"VOT_ACCURACY_FAIL: target Praat.exe not found: {args.praat_exe}")
        return 2
    if not args.alignment_config.is_file():
        print(f"VOT_ACCURACY_FAIL: alignment config not found: {args.alignment_config}")
        return 2
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_manifest(manifest, base_dir=args.manifest.resolve().parent, require_audio=True)
    if errors:
        print("VOT_ACCURACY_INVALID_MANIFEST: " + "; ".join(errors))
        return 2

    praat_exe = args.praat_exe.resolve()
    alignment_config = args.alignment_config.resolve()
    results: list[dict[str, Any]] = []
    consistent = True
    previous_config = os.environ.get("PRAAT_AI_CONFIG_PATH")
    os.environ["PRAAT_AI_CONFIG_PATH"] = str(alignment_config)
    try:
        with tempfile.TemporaryDirectory(prefix="praat-vot-accuracy-") as temporary:
            root = Path(temporary)
            for index, case in enumerate(manifest["cases"]):
                case_root = root / case["id"]
                case_root.mkdir(parents=True)
                audio_path = (args.manifest.resolve().parent / case["audio"]).resolve()
                entrypoints = run_full_entrypoints(
                    case, audio_path, praat_exe, case_root, alignment_config, args.timeout_seconds
                )
                scored = score_case(case, entrypoints)
                scored["audio"] = {
                    "path": case["audio"],
                    "sha256": case["audio_sha256"],
                    "sample_rate_hz": case["sample_rate_hz"],
                    "sample_count": case["sample_count"],
                }
                scored["results"] = entrypoints
                consistency = scored.get("entrypoint_consistency")
                consistent &= bool(consistency and consistency["consistent"])
                results.append(scored)
                print(f"VOT_ACCURACY_CASE {index + 1}/{len(manifest['cases'])}: {case['id']}")
    finally:
        if previous_config is None:
            os.environ.pop("PRAAT_AI_CONFIG_PATH", None)
        else:
            os.environ["PRAAT_AI_CONFIG_PATH"] = previous_config

    has_harness_failure = any(
        entrypoint.get("status") == "harness_failed"
        for scored_case in results
        for entrypoint in scored_case.get("results", {}).values()
    )
    report = {
        "schema_version": 1,
        "status": "entrypoint_harness_failed" if has_harness_failure else "measured",
        "target_praat_executable": str(praat_exe),
        "manifest": str(args.manifest.resolve()),
        "alignment_config": str(alignment_config),
        "annotation_protocol": manifest["annotation_protocol"],
        "thresholds": None,
        "threshold_note": "Raw errors are reported; no overall pass threshold has been agreed.",
        "entrypoints": ["native SoundEditor VOT command", "registered AI vot tool"],
        "entrypoints_consistent": consistent,
        "summary": summarize_cases(results),
        "cases": results,
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"VOT_ACCURACY_REPORT: {report_path}")
    return 0 if consistent and not has_harness_failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
