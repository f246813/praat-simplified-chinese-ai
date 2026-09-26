"""Exercise native snapshot export and analysis actions in a real Praat build."""

from __future__ import annotations

import csv
import json
import math
import os
import struct
import subprocess
import tempfile
from pathlib import Path


PRAAT = Path(os.environ.get("PRAAT_EXE", "Praat.exe")).resolve()


def praat_quote(value: str | Path) -> str:
    return '"' + str(value).replace("\\", "/").replace('"', '""') + '"'


def run_praat(script: Path) -> None:
    process = subprocess.run(
        [str(PRAAT), "--FULL-TRUST", "--run", str(script)],
        capture_output=True,
        timeout=60,
    )
    output = (process.stdout + process.stderr).decode("utf-16-le", "replace").replace("\x00", "")
    if process.returncode:
        raise RuntimeError(f"Praat snapshot action regression failed:\n{output}")


def verify_snapshot_actions() -> None:
    if not PRAAT.is_file():
        raise RuntimeError(f"Praat executable is missing: {PRAAT}")
    with tempfile.TemporaryDirectory(prefix="praat-vot-snapshot-action-") as temporary:
        root = Path(temporary)
        manifest = root / "sound.json"
        pcm = root / "sound.f64le"
        wav = root / "sound.wav"
        result = root / "result.tsv"
        source_wav = root / "source.wav"
        long_manifest = root / "long.json"
        long_pcm = root / "long.f64le"
        long_wav = root / "long.wav"
        script = root / "snapshot.praat"
        script.write_text(
            "\n".join(
                (
                    'sound = Create Sound from formula: "snapshot-action-fixture", 1, 2, 2.5, 48000, ~ 0.2 * sin (2 * pi * 220 * x)',
                    f"Write VOT audio snapshot: {praat_quote(manifest)}, {praat_quote(pcm)}, {praat_quote(wav)}, 4800, 19200",
                    f"Analyse VOT audio snapshot: {praat_quote(manifest)}, {praat_quote(pcm)}, 9600, 14400, 7200, 16800, -1, -1, \"{{\"\"pitch_floor_hz\"\":75}}\", {praat_quote(result)}",
                    f"Save as WAV file: {praat_quote(source_wav)}",
                    f"longSound = Open long sound file: {praat_quote(source_wav)}",
                    f"Write VOT audio snapshot: {praat_quote(long_manifest)}, {praat_quote(long_pcm)}, {praat_quote(long_wav)}, 4800, 19200",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        run_praat(script)

        sound_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        if sound_manifest["source_kind"] != "Sound" or sound_manifest["snapshot_start_sample"] != 4800:
            raise AssertionError(f"Sound snapshot identity/range is wrong: {sound_manifest!r}")
        if sound_manifest["sample_rate_hz"] != 48000 or sound_manifest["channels"] != 1:
            raise AssertionError(f"Sound snapshot sampling metadata is wrong: {sound_manifest!r}")
        pcm_bytes = pcm.read_bytes()
        if len(pcm_bytes) != 14400 * 8:
            raise AssertionError(f"float64 PCM has the wrong byte count: {len(pcm_bytes)}")
        samples = struct.unpack("<" + "d" * 14400, pcm_bytes)
        first_time = sound_manifest["time_origin_seconds"]
        for offset, sample in enumerate(samples):
            expected = 0.2 * math.sin(2.0 * math.pi * 220.0 * (first_time + offset / 48000.0))
            if not math.isclose(sample, expected, rel_tol=0.0, abs_tol=1e-12):
                raise AssertionError(f"snapshot PCM changed sample {offset}: {sample!r} != {expected!r}")
        alignment_wav = wav.read_bytes()
        if not alignment_wav.startswith(b"RIFF"):
            raise AssertionError("the model-alignment snapshot is not a WAV file")
        if struct.unpack_from("<H", alignment_wav, 20)[0] != 3 or struct.unpack_from(
            "<H", alignment_wav, 34
        )[0] != 32:
            raise AssertionError("the model-alignment WAV must preserve samples as IEEE float32")

        with result.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        if not rows or rows[0].get("source_kind") != "Sound":
            raise AssertionError("native analysis action did not return a Sound result")
        if int(float(rows[0]["source_sample_rate_hz"])) != 48000:
            raise AssertionError("native analysis action changed the snapshot sample rate")
        expected_target_start = 2.0 + (9600 + 0.5) / 48000.0
        if not math.isclose(float(rows[0]["source_start_s"]), expected_target_start, abs_tol=1e-12):
            raise AssertionError("native result lost the source time origin or sample-index range")

        long_data = json.loads(long_manifest.read_text(encoding="utf-8"))
        expected_long_origin = (4800 + 0.5) / 48000.0
        if long_data["source_kind"] != "LongSound" or not math.isclose(
            long_data["time_origin_seconds"], expected_long_origin, abs_tol=1e-12
        ):
            raise AssertionError(f"LongSound snapshot lost its source offset: {long_data!r}")
        if long_data["sample_count"] != 14400 or len(long_pcm.read_bytes()) != 14400 * 8:
            raise AssertionError("LongSound snapshot dimensions do not match its source sample range")


if __name__ == "__main__":
    verify_snapshot_actions()
    print("VOT_SNAPSHOT_ACTION_PASS: Sound and LongSound exact sample snapshots")
