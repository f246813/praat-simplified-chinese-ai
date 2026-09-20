from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .models import AnalysisResult, PronunciationError


def write_json(result: AnalysisResult, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _escape_textgrid(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def write_textgrid(result: AnalysisResult, path: str | Path) -> None:
    errors_by_phone: dict[int, list[PronunciationError]] = defaultdict(list)
    for error in result.errors:
        errors_by_phone[error.phone_index].append(error)

    intervals: list[tuple[float, float, str]] = []
    for phone in result.learner_phones:
        phone_errors = errors_by_phone.get(phone.phone_index, [])
        label = "正常" if not phone_errors else "；".join(
            error.message for error in phone_errors
        )
        intervals.append((phone.start, phone.end, label))

    if not intervals:
        intervals.append((0.0, result.duration, "无可用音素区间"))
    intervals.sort(key=lambda item: item[0])
    intervals[0] = (0.0, intervals[0][1], intervals[0][2])
    intervals[-1] = (intervals[-1][0], result.duration, intervals[-1][2])

    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0",
        f"xmax = {result.duration:.6f}",
        "tiers? <exists>",
        "size = 2",
        "item []:",
        "    item [1]:",
        '        class = "IntervalTier"',
        '        name = "AI_Errors"',
        "        xmin = 0",
        f"        xmax = {result.duration:.6f}",
        f"        intervals: size = {len(intervals)}",
    ]
    for index, (start, end, label) in enumerate(intervals, start=1):
        lines.extend(
            [
                f"        intervals [{index}]:",
                f"            xmin = {start:.6f}",
                f"            xmax = {end:.6f}",
                f"            text = {_escape_textgrid(label)}",
            ]
        )

    lines.extend(
        [
            "    item [2]:",
            '        class = "PointTier"',
            '        name = "AI_ErrorFeatures"',
            "        xmin = 0",
            f"        xmax = {result.duration:.6f}",
            f"        points: size = {len(result.errors)}",
        ]
    )
    for index, error in enumerate(result.errors, start=1):
        mark = f"/{error.ipa}/ {error.feature} {error.direction}"
        center = (error.start + error.end) / 2.0
        lines.extend(
            [
                f"        points [{index}]:",
                f"            number = {center:.6f}",
                f"            mark = {_escape_textgrid(mark)}",
            ]
        )

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_overlay_png(result: AnalysisResult, path: str | Path) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    width = 1280
    row_height = 150
    header_height = 60
    selected_errors = result.errors[:6]
    height = header_height + max(1, len(selected_errors)) * row_height + 30
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)
    draw.text((20, 18), "Praat AI pronunciation comparison", fill="#f9fafb")

    reference_by_index = {item.phone_index: item for item in result.reference_phones}
    learner_by_index = {item.phone_index: item for item in result.learner_phones}

    if not selected_errors:
        draw.text((20, header_height + 20), "No threshold violations.", fill="#86efac")
        image.save(path)
        return True

    for row, error in enumerate(selected_errors):
        top = header_height + row * row_height
        bottom = top + row_height - 18
        draw.rectangle((15, top, width - 15, bottom), fill="#1f2937")
        draw.text(
            (25, top + 8),
            f"/{error.ipa}/ {error.feature} score={error.score:.2f} {error.direction}",
            fill="#fca5a5",
        )
        reference_phone = reference_by_index.get(error.phone_index)
        learner_phone = learner_by_index.get(error.phone_index)
        if not reference_phone or not learner_phone:
            continue
        reference_track = reference_phone.tracks.get(error.feature)
        learner_track = learner_phone.tracks.get(error.feature)
        if not reference_track or not learner_track:
            continue

        all_values = reference_track.values + learner_track.values
        minimum = min(all_values)
        maximum = max(all_values)
        value_range = max(maximum - minimum, 1e-9)

        def points(track_values: list[float], start: float, end: float) -> list[tuple[int, int]]:
            if len(track_values) == 1:
                times = [start, end]
                track_values = track_values * 2
            else:
                times = [
                    start + (end - start) * index / (len(track_values) - 1)
                    for index in range(len(track_values))
                ]
            total = max(result.duration, 1e-9)
            return [
                (
                    int(40 + (time / total) * (width - 80)),
                    int(bottom - 20 - ((value - minimum) / value_range) * (bottom - top - 55)),
                )
                for time, value in zip(times, track_values)
            ]

        reference_points = points(
            reference_track.values,
            reference_phone.start,
            reference_phone.end,
        )
        learner_points = points(
            learner_track.values,
            learner_phone.start,
            learner_phone.end,
        )
        if len(reference_points) > 1:
            draw.line(reference_points, fill="#60a5fa", width=3)
        if len(learner_points) > 1:
            draw.line(learner_points, fill="#f59e0b", width=3)

        total = max(result.duration, 1e-9)
        left = int(40 + (error.start / total) * (width - 80))
        right = int(40 + (error.end / total) * (width - 80))
        draw.rectangle((left, top + 30, right, bottom - 5), outline="#ef4444", width=3)
        draw.text((width - 260, top + 8), "reference  learner", fill="#d1d5db")

    image.save(path)
    return True
