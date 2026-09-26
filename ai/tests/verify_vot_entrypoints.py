"""Exercise the registered AI VOT tool through a real Praat.exe process.

Set PRAAT_EXE to the target build. Each environment.execute call starts that
executable with a fresh deterministic Sound and runs the exact native script
submitted by the registered local tool.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, tools  # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = Path(os.environ.get("PRAAT_EXE", str(PROJECT / "Praat.exe")))
SOUND = (
    'Create Sound from formula: "vot-entrypoint", 1, 0, 1, 44100, '
    '"if x < 0.3 then 0 else if x < 0.33 then '
    '0.3 * sin (2*pi*3000*x) else 0.5 * sin (2*pi*220*x) fi fi"'
)


def _decode_output(value: bytes) -> str:
    return value.decode("utf-16-le", "replace").replace("\x00", "").strip()


class TargetPraatEnvironment:
    def __init__(self, root: Path, sound_script: str = SOUND):
        self.runtime_directory = root / "runtime"
        self.runtime_directory.mkdir(parents=True, exist_ok=True)
        self.praat_executable = str(PRAAT)
        self.sound_script = sound_script
        self.cancelled = lambda: False
        self.calls = 0

    def execute(self, script: str) -> tuple[bool, list[str], str]:
        self.calls += 1
        case_directory = self.runtime_directory / f"native-call-{self.calls}"
        case_directory.mkdir(parents=True, exist_ok=False)
        script_path = case_directory / "entrypoint.praat"
        script_path.write_text(self.sound_script + "\n" + script, encoding="utf-8")
        completed = subprocess.run(
            [self.praat_executable, "--FULL-TRUST", "--run", str(script_path)],
            cwd=PROJECT,
            capture_output=True,
            timeout=90,
        )
        output = _decode_output(completed.stdout + completed.stderr)
        if completed.returncode:
            return False, [], output or f"Praat exited with {completed.returncode}"
        state_paths = [
            Path(re.findall(r'"([^"]+)"', line)[0])
            for line in script.splitlines()
            if line.startswith("appendFileLine:")
            and '"done"' in line
            and re.findall(r'"([^"]+)"', line)
        ]
        if state_paths and not state_paths[-1].is_file():
            return False, [], output or "Praat did not complete the native script."
        result_paths = [
            Path(re.findall(r'"([^"]+)"', line)[0])
            for line in script.splitlines()
            if line.startswith("appendFileLine:") and "chat_state" not in line
            and re.findall(r'"([^"]+)"', line)
        ]
        results: list[str] = []
        for path in result_paths:
            if path.is_file():
                results = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return True, results, ""


def run_ai_vot(
    arguments: dict[str, Any],
    context: tools.ToolContext,
    environment: TargetPraatEnvironment,
) -> dict[str, Any]:
    step = chat._execute_action(
        {"tool": "vot", "arguments": arguments},
        context,
        environment.execute,
        1,
        environment,
    )
    if not step.ok or not step.results:
        raise AssertionError(step.observation)
    try:
        return json.loads(step.results[0])
    except json.JSONDecodeError as error:
        raise AssertionError(f"AI vot returned non-JSON output: {step.results!r}") from error


def _same_result_without_execution_id(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("request_id", None)
    return result


def maximum_boundary_drift_ms(reference: dict[str, Any], comparison: dict[str, Any]) -> float:
    """Return the largest boundary movement for two complete native candidates."""

    if reference.get("status") != "candidate" or comparison.get("status") != "candidate":
        raise ValueError("selection stability requires a complete candidate from both runs")
    sample_rate = float(reference.get("sample_rate_hz", 0.0))
    if sample_rate <= 0.0 or float(comparison.get("sample_rate_hz", 0.0)) != sample_rate:
        raise ValueError("selection stability requires the same positive sample rate")
    boundary_names = ("burst_sample_index", "onset_sample_index")
    if any(reference.get(name) is None or comparison.get(name) is None for name in boundary_names):
        raise ValueError("selection stability requires a complete candidate from both runs")
    maximum_samples = max(
        abs(int(reference[name]) - int(comparison[name])) for name in boundary_names
    )
    return maximum_samples * 1000.0 / sample_rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio",
        type=Path,
        help="read the known 0.30 s burst / 0.33 s voiced fixture for repeatability and selection checks",
    )
    parser.add_argument("--report", type=Path, help="write a JSON report of the entrypoint evidence")
    args = parser.parse_args()
    if not PRAAT.is_file():
        print(f"VOT_ENTRYPOINT_FAIL: target Praat.exe not found: {PRAAT}")
        return 2
    if args.audio is not None and not args.audio.is_file():
        print(f"VOT_ENTRYPOINT_FAIL: audio fixture not found: {args.audio}")
        return 2
    with tempfile.TemporaryDirectory(prefix="praat-vot-entrypoints-") as raw:
        root = Path(raw)
        result_path = root / "chat-result.jsonl"
        state_path = root / "chat_state.txt"
        context = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\n1\tSound\tvot-entrypoint\t1\n"
            ),
            result_path,
            state_path,
        )
        sound_script = SOUND
        if args.audio is not None:
            audio_path = str(args.audio.resolve()).replace("\\", "/").replace('"', '""')
            sound_script = f'Read from file: "{audio_path}"'
        environment = TargetPraatEnvironment(root, sound_script)
        moved: dict[str, Any] | None = None
        clipped: dict[str, Any] | None = None
        drift_ms: float | None = None

        common = {
            "object": 1,
            "mode": "acoustic_only",
            "from": 0.25,
            "to": 0.5,
        }
        repeated = [run_ai_vot(common, context, environment) for _ in range(5)]
        first = repeated[0]
        for result in repeated[1:]:
            if result["request_hash"] != first["request_hash"]:
                raise AssertionError("identical AI VOT requests changed their canonical request hash")
            if _same_result_without_execution_id(first) != _same_result_without_execution_id(result):
                raise AssertionError(
                    "fresh target-Praat VOT executions returned different boundaries, VOT, status, or provenance"
                )
        if environment.calls != 15:
            raise AssertionError(f"expected 15 uncached native scripts, got {environment.calls}")
        print(
            "AI_NATIVE_REPEATABILITY_PASS: "
            + json.dumps(
                {
                    "request_hash": first["request_hash"],
                    "audio_hash": first["audio_hash"],
                    "status": first["status"],
                    "burst_sample_index": first["burst_sample_index"],
                    "onset_sample_index": first["onset_sample_index"],
                    "vot_ms": first["vot_ms"],
                    "fresh_runs": len(repeated),
                    "fresh_native_scripts": environment.calls,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        if args.audio is not None:
            moved = run_ai_vot(
                {**common, "from": 0.255, "to": 0.505}, context, environment
            )
            drift_ms = maximum_boundary_drift_ms(first, moved)
            if drift_ms > 5.0:
                raise AssertionError(f"same-target selection movement changed boundaries by {drift_ms:.3f} ms")
            print(f"AI_SELECTION_STABILITY_PASS: moved selection by 5 ms; max boundary drift {drift_ms:.3f} ms")

            clipped = run_ai_vot(
                {**common, "from": 0.31, "to": 0.32}, context, environment
            )
            if clipped["status"] not in {"failed", "ambiguous", "target_incomplete"} or any(
                clipped.get(key) is not None
                for key in ("burst_sample_index", "onset_sample_index", "vot_ms")
            ):
                raise AssertionError(f"clipped target produced a single VOT value: {clipped!r}")
            print(
                "AI_CLIPPED_TARGET_PASS: "
                + json.dumps(
                    {"status": clipped["status"], "failure_reason": clipped["failure_reason"]},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        manual_values = []
        for burst, voicing in ((0.3, 0.33), (0.3, 0.3), (0.33, 0.3)):
            manual_values.append(
                run_ai_vot(
                    {
                        **common,
                        "mode": "manual",
                        "burst": burst,
                        "voicing": voicing,
                    },
                    context,
                    environment,
                )
            )
        expected_manual = [(13229, 14553), (13229, 13229), (14553, 13229)]
        for result, (burst_sample, onset_sample) in zip(manual_values, expected_manual):
            expected_ms = (onset_sample - burst_sample) * 1000.0 / 44100.0
            if (
                result["status"] != "manual_confirmed"
                or result["burst_sample_index"] != burst_sample
                or result["onset_sample_index"] != onset_sample
                or abs(result["vot_ms"] - expected_ms) > 0.001
            ):
                raise AssertionError(f"manual sample-index formula changed: {result!r}")
        print("AI_MANUAL_ENTRYPOINT_PASS: positive, zero, and negative sample-index calculations")

        incomplete = run_ai_vot(
            {
                "object": 1,
                "mode": "model_assisted",
                "from": 0.25,
                "to": 0.5,
            },
            context,
            environment,
        )
        if incomplete["status"] != "requires_input" or "language" not in incomplete["failure_reason"]:
            raise AssertionError(f"missing model-alignment input was not explained: {incomplete!r}")
        print("AI_ALIGNMENT_INPUT_CHECK_PASS: model-assisted analysis asks for language and phonemes")

        if args.report is not None:
            report = {
                "schema_version": 1,
                "target_praat_executable": str(PRAAT.resolve()),
                "fixture": {
                    "kind": "wav_file" if args.audio is not None else "deterministic_synthetic_sound",
                    "path": str(args.audio.resolve()) if args.audio is not None else None,
                    "audio_hash": first["audio_hash"],
                },
                "entrypoints": {
                    "ai_vot": {
                        "status": "verified",
                        "dispatch": "chat._execute_action -> registered local vot -> VOTAnalysisService -> target Praat.exe",
                        "mode": "acoustic_only",
                        "request_hash": first["request_hash"],
                        "algorithm_version": first["algorithm_version"],
                        "detector_path": first["detector_path"],
                        "model_ids": first["model_ids"],
                        "model_versions": first["model_versions"],
                        "repeatability": {
                            "fresh_runs": len(repeated),
                            "fresh_native_scripts": 15,
                            "all_results_identical": True,
                            "status": first["status"],
                            "burst_sample_index": first["burst_sample_index"],
                            "onset_sample_index": first["onset_sample_index"],
                            "vot_ms": first["vot_ms"],
                        },
                        "selection_stability": {
                            "status": "verified" if moved is not None else "not_run",
                            "selection_shift_ms": 5.0 if moved is not None else None,
                            "maximum_boundary_drift_ms": drift_ms,
                        },
                        "clipped_target": {
                            "status": clipped["status"] if clipped is not None else "not_run",
                            "vot_ms": clipped["vot_ms"] if clipped is not None else None,
                            "failure_reason": clipped["failure_reason"] if clipped is not None else None,
                        },
                        "manual_results": [
                            {
                                "request_hash": result["request_hash"],
                                "burst_sample_index": result["burst_sample_index"],
                                "onset_sample_index": result["onset_sample_index"],
                                "vot_ms": result["vot_ms"],
                                "status": result["status"],
                                "burst_source": result["burst_source"],
                                "onset_source": result["onset_source"],
                            }
                            for result in manual_values
                        ],
                    },
                    "sound_editor_vot": {
                        "status": "not_verified",
                        "reason": (
                            "The Windows UI state API exposed the window tree but returned "
                            "'coordinate input geometry is unavailable' on click and timed out "
                            "capturing the target Praat window."
                        ),
                    },
                },
                "accuracy": {
                    "status": "not_verified",
                    "reason": "This run uses a synthetic fixture; no independently annotated real Japanese recording and adjudicated boundaries are available.",
                },
                "model_assisted": {
                    "status": incomplete["status"],
                    "reason": incomplete["failure_reason"],
                },
            }
            report_path = args.report.resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"VOT_ACCEPTANCE_REPORT: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
