from __future__ import annotations

import json
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from praat_ai.bridge import PraatBridge
from praat_ai.vot import VOTAlignedPhone, VOTAnalysisRequest, VOTAudioSnapshot, VOTMode, VOTStatus
from praat_ai.vot_bridge import PraatVOTAcousticAnalyzer, _parse_parameters


class FakePraatHelper:
    def __init__(self, root: Path, *, source_kind: str = "Sound", start_sample: int = 12000):
        self.root = root
        self.source_kind = source_kind
        self.start_sample = start_sample
        self.selected = [{"id": 7, "name": "edited", "class": source_kind, "file": ""}]
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.selected_ids: list[int] = []

    def get_selected(self):
        return self.selected

    def get_output_dir(self):
        return str(self.root)

    def select(self, object_id: int):
        self.selected_ids = [object_id]

    def plus_select(self, object_id: int):
        self.selected_ids.append(object_id)

    def call(self, command: str, *arguments: object):
        self.calls.append((command, arguments))
        if command == "Write VOT audio snapshot...":
            manifest_path, pcm_path, wav_path, start_sample, end_sample = arguments
            start = int(start_sample)
            end = int(end_sample)
            pcm = struct.pack("<" + "d" * ((end - start) * 2), *range((end - start) * 2))
            Path(str(pcm_path)).write_bytes(pcm)
            Path(str(wav_path)).write_bytes(b"RIFF mock wav")
            manifest = {
                "schema_version": 1,
                "object_id": 7,
                "source_kind": self.source_kind,
                "sample_rate_hz": 48000,
                "channels": 2,
                "sample_count": end - start,
                "snapshot_start_sample": start,
                "time_origin_seconds": 10.0 + start / 48000.0,
            }
            Path(str(manifest_path)).write_text(json.dumps(manifest), encoding="utf-8")
        elif command == "Analyse VOT audio snapshot...":
            manifest = json.loads(Path(str(arguments[0])).read_text(encoding="utf-8"))
            result_path = Path(str(arguments[-1]))
            result_path.write_text(
                _candidate_tsv(float(manifest["time_origin_seconds"])), encoding="utf-8"
            )


def _candidate_tsv(time_origin: float) -> str:
    header = (
        "schema_version\tpraat_version\tsource\tsource_object_id\tsource_file\tsource_start_s\t"
        "source_end_s\tsource_duration_s\tsource_sample_rate_hz\tsource_channels\tsource_kind\t"
        "analysis_kind\tparameters\tlanguage\tipa\tspeaker_id\tneighboring_vowel\tburst_time_s\t"
        "voicing_time_s\tmetric_id\tvalue\tunit\tstatus\treason\n"
    )
    base = "1\t9.0\tedited\t7\t\t22\t22.2\t.2\t48000\t2\tLongSound\tVOT\t"
    parameters = "algorithmVersion=context-pair-v5; burstDetectionPath=high-band; burstDetectionBand=high-band; burstDetectionFallbackReason="
    rows = []
    for metric, value, unit, status, reason in (
        ("burst_time_candidate", repr(time_origin + 55 / 48000), "s", "warning", "Candidate from high-band."),
        ("voicing_time_candidate", repr(time_origin + 65 / 48000), "s", "warning", "Stable onset candidate."),
        ("vot_candidate_ms", "0.208333333333", "ms", "warning", "Difference of estimated candidates."),
        ("negative_vot_prevoicing_evidence", "0", "boolean", "measured", "No negative prevoicing was used."),
    ):
        rows.append(base + parameters + "\t\t\t\t\t\t\t" + metric + "\t" + value + "\t" + unit + "\t" + status + "\t" + reason + "\n")
    return header + "".join(rows)


class VOTBridgeTests(unittest.TestCase):
    def test_parameter_parser_preserves_semicolons_inside_provenance(self) -> None:
        parameters = _parse_parameters(
            "algorithmVersion=context-pair-v5; "
            "burstDetectionFallbackReason=Nyquist low; secondary fallback reason; "
            "burstDetectionPath=full-band"
        )

        self.assertEqual(
            parameters["burstDetectionFallbackReason"],
            "Nyquist low; secondary fallback reason",
        )
        self.assertEqual(parameters["burstDetectionPath"], "full-band")

    def test_snapshot_rejects_invalid_object_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bridge = PraatBridge(FakePraatHelper(Path(temporary)))

            for invalid_id in (0, -7, True, "7"):
                with self.subTest(object_id=invalid_id), self.assertRaisesRegex(
                    RuntimeError, "object ID must be a positive integer"
                ):
                    bridge.create_vot_snapshot(invalid_id, 1, 2)

    def test_sound_snapshot_contains_current_samples_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            helper = FakePraatHelper(Path(temporary))
            bridge = PraatBridge(helper)

            first = bridge.create_vot_snapshot(7, 12345, 12349)
            second = bridge.create_vot_snapshot(7, 12345, 12349)

            self.assertEqual(first.pcm_path.read_bytes(), struct.pack("<8d", *range(8)))
            self.assertEqual(first.sample_rate_hz, 48000)
            self.assertEqual(first.channels, 2)
            self.assertEqual(first.sample_count, 4)
            self.assertEqual(first.content_hash, second.content_hash)
            self.assertTrue(first.path.exists())
            self.assertTrue(first.manifest_path.exists())
            manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
            identity = {key: value for key, value in manifest.items() if key not in {"content_hash", "pcm_sha256"}}
            canonical = json.dumps(
                identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            expected_hash = hashlib.sha256(canonical + b"\0" + first.pcm_path.read_bytes()).hexdigest()
            self.assertEqual(first.content_hash, expected_hash)

    def test_longsound_snapshot_preserves_absolute_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            helper = FakePraatHelper(Path(temporary), source_kind="LongSound")
            bridge = PraatBridge(helper)

            snapshot = bridge.create_vot_snapshot(7, 480000, 480096)

            self.assertEqual(snapshot.source_kind, "LongSound")
            self.assertEqual(snapshot.snapshot_start_sample, 480000)
            self.assertAlmostEqual(snapshot.time_origin_seconds, 20.0)
            self.assertAlmostEqual(snapshot.absolute_sample_to_seconds(480048), 20.001)
            self.assertEqual(snapshot.seconds_to_absolute_sample(20.001), 480048)

    def test_snapshot_sample_ranges_are_not_rounded_to_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            helper = FakePraatHelper(Path(temporary))
            bridge = PraatBridge(helper)

            bridge.create_vot_snapshot(7, 12345, 12349)

            command, arguments = helper.calls[0]
            self.assertEqual(command, "Write VOT audio snapshot...")
            self.assertEqual(arguments[-2:], (12345, 12349))
            self.assertTrue(all(isinstance(value, int) for value in arguments[-2:]))

    def test_acoustic_bridge_returns_the_cpp_result_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            helper = FakePraatHelper(Path(temporary), source_kind="LongSound")
            bridge = PraatBridge(helper)
            snapshot = bridge.create_vot_snapshot(7, 480000, 480096)
            vot = VOTAnalysisRequest(
                request_id="request-1",
                audio_snapshot=snapshot,
                target_range=(480024, 480072),
                acoustic_context_range=(480012, 480084),
                alignment_context_range=(480000, 480096),
                language="Japanese",
                transcript="か",
                phonemes=("k",),
                target_phone_index=0,
                mode=VOTMode.ACOUSTIC_ONLY,
                parameters={"burst_threshold_db": 6.0},
            )

            result = PraatVOTAcousticAnalyzer(bridge).analyze(
                vot, VOTAlignedPhone(1, "k", 480024, 480072, "mfa", 0.85)
            )

            self.assertEqual(result.status, VOTStatus.CANDIDATE)
            self.assertEqual(result.burst_sample_index, 480055)
            self.assertEqual(result.onset_sample_index, 480065)
            self.assertEqual(result.detector_path, "high-band")
            command, arguments = helper.calls[-1]
            self.assertEqual(command, "Analyse VOT audio snapshot...")
            self.assertEqual(arguments[2:8], (480024, 480072, 480012, 480084, 480024, 480072))
            analyzer = PraatVOTAcousticAnalyzer(bridge)
            analyzer.analyze(vot, VOTAlignedPhone(1, "k", 480024, 480072, "mfa", 0.85))
            repeated_command, repeated_arguments = helper.calls[-1]
            self.assertEqual((command, arguments[:-1]), (repeated_command, repeated_arguments[:-1]))


if __name__ == "__main__":
    unittest.main()
