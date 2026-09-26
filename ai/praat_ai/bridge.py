from __future__ import annotations

import hashlib
import json
import math
import struct
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .vot import VOTAudioSnapshot


class PraatBridgeError(RuntimeError):
    pass


@dataclass(slots=True)
class SelectedObject:
    id: int
    name: str
    class_name: str
    file: Path
    object_version: str = ""

    @classmethod
    def from_praat(cls, value: dict[str, Any]) -> "SelectedObject":
        return cls(
            id=int(value.get("id", 0)),
            name=str(value.get("name", "")),
            class_name=str(value.get("class", "")),
            file=Path(str(value.get("file", ""))),
            object_version=str(value.get("version", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "class": self.class_name,
            "file": str(self.file),
        }


class PraatBridge:
    def __init__(self, helper: Any):
        self.helper = helper

    @classmethod
    def from_praat(cls) -> "PraatBridge":
        try:
            import praat as helper  # type: ignore[import-not-found]
        except ImportError as error:
            raise PraatBridgeError(
                "This script must run inside Praat's Python editor or another "
                "process where the generated `praat` helper module is available."
            ) from error
        return cls(helper)

    def selected_objects(self) -> list[SelectedObject]:
        values = self.helper.get_selected()
        if not isinstance(values, list):
            raise PraatBridgeError("praat.get_selected() did not return a list.")
        return [SelectedObject.from_praat(value) for value in values]

    def resolve_sound(self, reference: int | str) -> SelectedObject:
        objects = self.selected_objects()
        for item in objects:
            if item.class_name != "Sound":
                continue
            if isinstance(reference, int) and item.id == reference:
                return item
            if isinstance(reference, str) and item.name == reference:
                return item
        raise PraatBridgeError(f"Selected Sound object not found: {reference!r}")

    def resolve_audio_object(self, reference: int | str) -> SelectedObject:
        for item in self.selected_objects():
            if item.class_name not in {"Sound", "LongSound"}:
                continue
            if isinstance(reference, int) and item.id == reference:
                return item
            if isinstance(reference, str) and item.name == reference:
                return item
        raise PraatBridgeError(f"Selected Sound or LongSound object not found: {reference!r}")

    def create_vot_snapshot(
        self,
        object_id: int,
        snapshot_start_sample: int,
        snapshot_end_sample: int,
    ) -> VOTAudioSnapshot:
        if isinstance(object_id, bool) or not isinstance(object_id, int) or object_id <= 0:
            raise PraatBridgeError("VOT snapshot object ID must be a positive integer.")
        if isinstance(snapshot_start_sample, bool) or not isinstance(snapshot_start_sample, int):
            raise PraatBridgeError("VOT snapshot start must be an integer sample index.")
        if isinstance(snapshot_end_sample, bool) or not isinstance(snapshot_end_sample, int):
            raise PraatBridgeError("VOT snapshot end must be an integer sample index.")
        if snapshot_start_sample < 0 or snapshot_start_sample >= snapshot_end_sample:
            raise PraatBridgeError("VOT snapshot range must be increasing non-negative sample indices.")

        selected = self.resolve_audio_object(object_id)
        with tempfile.TemporaryDirectory(prefix="praat-vot-snapshot-") as temporary:
            root = Path(temporary)
            manifest_path = root / "snapshot.json"
            pcm_path = root / "snapshot.f64le"
            wav_path = root / "snapshot.wav"
            old_selection = [item.id for item in self.selected_objects()]
            try:
                self.select(object_id)
                self.call(
                    "Write VOT audio snapshot...",
                    str(manifest_path),
                    str(pcm_path),
                    str(wav_path),
                    snapshot_start_sample,
                    snapshot_end_sample,
                )
            finally:
                self._restore_selection(old_selection)

            if not manifest_path.is_file() or not pcm_path.is_file() or not wav_path.is_file():
                raise PraatBridgeError("Praat did not write every VOT snapshot artifact.")
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                pcm_bytes = pcm_path.read_bytes()
                sample_rate = float(manifest["sample_rate_hz"])
                channels = int(manifest["channels"])
                sample_count = int(manifest["sample_count"])
                manifest_start = int(manifest["snapshot_start_sample"])
                time_origin = float(manifest["time_origin_seconds"])
                source_kind = str(manifest["source_kind"])
                manifest_object_id = int(manifest["object_id"])
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                raise PraatBridgeError(f"Praat wrote an invalid VOT snapshot manifest: {error}") from error

            expected_samples = snapshot_end_sample - snapshot_start_sample
            if not math.isfinite(sample_rate) or sample_rate <= 0.0:
                raise PraatBridgeError("VOT snapshot sample rate must be finite and positive.")
            if not math.isfinite(time_origin):
                raise PraatBridgeError("VOT snapshot time origin must be finite.")
            if source_kind not in {"Sound", "LongSound"}:
                raise PraatBridgeError("VOT snapshot source kind must be Sound or LongSound.")
            if channels <= 0 or sample_count != expected_samples or manifest_start != snapshot_start_sample:
                raise PraatBridgeError("VOT snapshot dimensions do not match the requested sample range.")
            if manifest_object_id != object_id or source_kind != selected.class_name:
                raise PraatBridgeError("VOT snapshot identity does not match the selected audio object.")
            if len(pcm_bytes) != sample_count * channels * 8:
                raise PraatBridgeError("VOT snapshot PCM byte count does not match its manifest.")
            if len(pcm_bytes) % 8:
                raise PraatBridgeError("VOT snapshot PCM is not a sequence of float64 samples.")

            pcm_digest = hashlib.sha256(pcm_bytes).hexdigest()
            identity = {
                "schema_version": int(manifest.get("schema_version", 1)),
                "object_id": object_id,
                "source_kind": source_kind,
                "object_version": selected.object_version or f"pcm-sha256:{pcm_digest}",
                "sample_rate_hz": sample_rate,
                "channels": channels,
                "sample_count": sample_count,
                "snapshot_start_sample": manifest_start,
                "time_origin_seconds": time_origin,
            }
            canonical = json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            content_hash = hashlib.sha256(canonical + b"\0" + pcm_bytes).hexdigest()
            complete_manifest = {
                **identity,
                "pcm_sha256": pcm_digest,
                "content_hash": content_hash,
            }
            manifest_path.write_text(
                json.dumps(complete_manifest, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )

            # The artifacts outlive the temporary scope because the alignment and
            # acoustic stages consume the same immutable snapshot after return.
            persistent_root = self.output_dir() / "vot-snapshots" / uuid.uuid4().hex
            persistent_root.mkdir(parents=True, exist_ok=False)
            persistent_manifest = persistent_root / manifest_path.name
            persistent_pcm = persistent_root / pcm_path.name
            persistent_wav = persistent_root / wav_path.name
            persistent_manifest.write_bytes(manifest_path.read_bytes())
            persistent_pcm.write_bytes(pcm_bytes)
            persistent_wav.write_bytes(wav_path.read_bytes())

        return VOTAudioSnapshot(
            path=persistent_wav,
            content_hash=content_hash,
            object_id=str(object_id),
            object_version=identity["object_version"],
            source_kind=source_kind,
            sample_rate_hz=sample_rate,
            channels=channels,
            sample_count=sample_count,
            snapshot_start_sample=manifest_start,
            time_origin_seconds=time_origin,
            pcm_path=persistent_pcm,
            manifest_path=persistent_manifest,
        )

    def _restore_selection(self, object_ids: list[int]) -> None:
        if not object_ids:
            return
        self.select(object_ids[0])
        for object_id in object_ids[1:]:
            self.plus_select(object_id)

    def output_dir(self) -> Path:
        return Path(self.helper.get_output_dir()).resolve()

    def call(self, command: str, *arguments: Any) -> None:
        self.helper.call(command, *arguments)

    def run_praat_script(self, script: str) -> None:
        self.helper.run_praat_script(script)

    def select(self, object_id: int) -> None:
        self.helper.select(object_id)

    def plus_select(self, object_id: int) -> None:
        self.helper.plus_select(object_id)


def object_payload(objects: list[SelectedObject]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in objects]
