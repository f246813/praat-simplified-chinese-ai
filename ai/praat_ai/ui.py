from __future__ import annotations

import re
from dataclasses import dataclass

from .audio import read_wav
from .bridge import SelectedObject
from .models import AnalysisRequest, PhoneSpec


@dataclass(slots=True)
class TutorFormValues:
    request: AnalysisRequest | None


def _parse_phonemes(text: str) -> list[str]:
    return [
        item
        for item in re.split(r"[\s,，;；]+", text.strip())
        if item
    ]


def _equal_segments(phonemes: list[str], duration: float) -> list[PhoneSpec]:
    if not phonemes:
        return []
    step = duration / len(phonemes)
    return [
        PhoneSpec(
            ipa=phoneme,
            reference_start=index * step,
            reference_end=(index + 1) * step,
        )
        for index, phoneme in enumerate(phonemes)
    ]


def show_tutor_form(sound_objects: list[SelectedObject]) -> TutorFormValues:
    import tkinter as tk
    from tkinter import messagebox, ttk

    result = TutorFormValues(request=None)
    if len(sound_objects) < 2:
        raise ValueError("AI 纠音需要至少两个已选中的 Sound 对象。")

    root = tk.Tk()
    root.title("Praat 本地 AI 纠音")
    root.geometry("620x420")
    root.resizable(False, False)

    names = [f"{item.id}: {item.name}" for item in sound_objects]
    reference_name = tk.StringVar(value=names[0])
    learner_name = tk.StringVar(value=names[1])
    language = tk.StringVar(value="cmn")
    phoneme_text = tk.StringVar(value="m a n")
    transcript_text = tk.StringVar(value="")
    threshold = tk.StringVar(value="1.25")
    qwen_explain = tk.BooleanVar(value=True)
    qwen_vision = tk.BooleanVar(value=False)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="标准音范本").grid(row=0, column=0, sticky="w", pady=6)
    ttk.Combobox(
        frame,
        textvariable=reference_name,
        values=names,
        state="readonly",
        width=52,
    ).grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)

    ttk.Label(frame, text="学习者录音").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Combobox(
        frame,
        textvariable=learner_name,
        values=names,
        state="readonly",
        width=52,
    ).grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)

    ttk.Label(frame, text="目标语言").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=language, width=54).grid(
        row=2,
        column=1,
        columnspan=2,
        sticky="ew",
        pady=6,
    )

    ttk.Label(frame, text="目标音位").grid(row=3, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=phoneme_text, width=54).grid(
        row=3,
        column=1,
        columnspan=2,
        sticky="ew",
        pady=6,
    )
    ttk.Label(frame, text="用空格、逗号或分号分隔 IPA 音位").grid(
        row=4,
        column=1,
        columnspan=2,
        sticky="w",
    )

    ttk.Label(frame, text="参考文本").grid(row=5, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=transcript_text, width=54).grid(
        row=5,
        column=1,
        columnspan=2,
        sticky="ew",
        pady=6,
    )
    ttk.Label(frame, text="使用 MFA 词典时填写，例如 hello world").grid(
        row=6,
        column=1,
        columnspan=2,
        sticky="w",
    )

    ttk.Label(frame, text="错误阈值").grid(row=7, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=threshold, width=12).grid(
        row=7,
        column=1,
        sticky="w",
        pady=6,
    )

    ttk.Checkbutton(
        frame,
        text="使用 Qwen 生成解释",
        variable=qwen_explain,
    ).grid(row=8, column=1, sticky="w", pady=4)
    ttk.Checkbutton(
        frame,
        text="把对比图交给 Qwen 视觉模型解释",
        variable=qwen_vision,
    ).grid(row=9, column=1, sticky="w", pady=4)

    def analyze() -> None:
        by_label = {f"{item.id}: {item.name}": item for item in sound_objects}
        reference = by_label[reference_name.get()]
        learner = by_label[learner_name.get()]
        phonemes = _parse_phonemes(phoneme_text.get())
        if not phonemes:
            messagebox.showerror("错误", "至少输入一个 IPA 音位。")
            return
        try:
            error_threshold = float(threshold.get())
        except ValueError:
            messagebox.showerror("错误", "错误阈值必须是数字。")
            return

        reference_audio = read_wav(reference.file)
        result.request = AnalysisRequest(
            reference_object=reference.id,
            learner_object=learner.id,
            language=language.get().strip(),
            phonemes=_equal_segments(phonemes, reference_audio.duration),
            transcript=transcript_text.get().strip(),
            error_threshold=error_threshold,
            qwen_explain=qwen_explain.get(),
            qwen_vision=qwen_vision.get(),
        )
        root.destroy()

    button_row = ttk.Frame(frame)
    button_row.grid(row=10, column=0, columnspan=3, pady=18, sticky="e")
    ttk.Button(button_row, text="取消", command=root.destroy).pack(
        side="right",
        padx=6,
    )
    ttk.Button(button_row, text="开始分析", command=analyze).pack(side="right")

    frame.columnconfigure(1, weight=1)
    root.mainloop()
    return result
