"""手动回归：把每个对话工具模板放进真实 Praat 批处理里跑一遍。

用法（仓库根目录，需要本机已经构建好 ``Praat.exe``）：

    python ai/tests/verify_chat_templates.py

它不依赖 unittest，也不会被 ``unittest discover`` 收集。每个用例都会先用
``prefix`` 造出对象，再渲染模板，最后检查脚本是否写出 ``chat_state.txt``、
结果文件里是否出现期望文字。改 ``ai/praat_ai/tools.py`` 的模板后应该跑一遍，
因为「脚本语法对不对」只有真正的 Praat 才能回答。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import tools   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"

SOUND = 'Create Sound from formula: "tone", 1, 0, 1, 44100, ~ 0.5 * sin (2*pi*220*x)'
SILENT = 'Create Sound from formula: "silence", 1, 0, 1, 44100, ~ 0'
HALF_SILENT = (
    'Create Sound from formula: "half", 1, 0, 1, 44100, '
    '~ if x < 0.4 then 0 else 0.5 * sin (2*pi*220*x) fi'
)

ONE_SOUND = "id\tclass\tname\tselected\n1\tSound\tSound tone\t1\n"
TWO_SOUNDS = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
    "2\tSound\tSound tone2\t0\n"
)
TWO_SOUND_PREFIX = SOUND + "\n" + SOUND.replace('"tone"', '"tone2"')


@dataclass
class Case:
    name: str
    arguments: dict[str, object]
    prefix: str
    context: str
    expect: str = ""
    custom_script: str = ""
    tool: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


CASES: tuple[Case, ...] = (
    Case("duration", {}, SOUND, ONE_SOUND, "总时长"),
    Case("object_info", {}, SOUND, ONE_SOUND, "采样率"),
    Case("formant_bandwidth", {"formant": 2}, SOUND, ONE_SOUND, "共振峰带宽"),
    Case(
        "formant_frequency",
        {"formant": "1,2", "time": 0.4},
        SOUND,
        ONE_SOUND,
        "第 2 共振峰（",
    ),
    Case("pitch", {"time": 0.5}, SOUND, ONE_SOUND, "基频"),
    Case(
        "pitch-multi-times",
        {"time": "0.25,0.75"},
        SOUND,
        ONE_SOUND,
        "0.750 秒处",
        tool="pitch",
    ),
    Case("pitch_statistics", {}, SOUND, ONE_SOUND, "基频统计"),
    Case("intensity", {}, SOUND, ONE_SOUND, "强度"),
    Case("intensity_statistics", {}, SOUND, ONE_SOUND, "强度统计"),
    Case(
        "formant_statistics",
        {"formant": "1,2"},
        SOUND,
        ONE_SOUND,
        "第 2 共振峰平均",
    ),
    Case("harmonicity_statistics", {}, SOUND, ONE_SOUND, "谐噪比 HNR"),
    Case("spectrogram", {}, SOUND, ONE_SOUND, "已生成频谱图"),
    Case("select_object", {}, SOUND, ONE_SOUND, "已选中"),
    Case("rename_object", {"new_name": "改名测试"}, SOUND, ONE_SOUND, "已重命名"),
    Case("create_sound", {"duration": 0.5, "frequency": 220}, SOUND, ONE_SOUND, "已创建"),
    Case("duplicate_object", {}, SOUND, ONE_SOUND, "已复制为"),
    Case("resample_sound", {"rate": 16000}, SOUND, ONE_SOUND, "采样率"),
    Case("extract_part", {"start": 0.2, "end": 0.5}, SOUND, ONE_SOUND, "已截取片段"),
    Case("save_sound", {"path": "@WAV@"}, SOUND, ONE_SOUND, "已保存 WAV"),
    Case(
        "concatenate_sounds",
        {"object": 1, "object2": 2},
        TWO_SOUND_PREFIX,
        TWO_SOUNDS,
        "拼成",
    ),
    Case(
        "remove_object",
        {"object": 2},
        TWO_SOUND_PREFIX,
        TWO_SOUNDS,
        "已删除",
    ),
    Case(
        "custom_script",
        {},
        SOUND,
        ONE_SOUND,
        "自定义改名完成",
        custom_script=(
            'selectObject: 1\nRename: "自定义改名"\n'
            'appendFileLine: "@RESULT@", "自定义改名完成"'
        ),
    ),
    # 越界时间：应该被截断到对象末尾，而不是报错或者回一个 --undefined--。
    Case(
        "pitch-out-of-range",
        {"time": 5.0},
        SOUND,
        ONE_SOUND,
        "已按对象时长截断",
        tool="pitch",
    ),
    Case(
        "formant-out-of-range",
        {"formant": 2, "time": 5.0},
        SOUND,
        ONE_SOUND,
        "已按对象时长截断",
        tool="formant_bandwidth",
    ),
    Case(
        "intensity-out-of-range",
        {"time": 5.0},
        SOUND,
        ONE_SOUND,
        "已按对象时长截断",
        tool="intensity",
    ),
    # 静音段：Praat 返回 --undefined--，模板要换成中文说明。
    Case(
        "pitch-unvoiced",
        {"time": 0.2},
        HALF_SILENT,
        ONE_SOUND,
        "没有周期性声源",
        tool="pitch",
    ),
    Case(
        "pitch-statistics-silence",
        {},
        SILENT,
        ONE_SOUND,
        "没有周期性声源",
        tool="pitch_statistics",
    ),
)


def run_case(case: Case, directory: Path) -> tuple[bool, str]:
    result_path = directory / f"{case.name}-result.tsv"
    state_path = directory / f"{case.name}-state.txt"
    wav_path = directory / f"{case.name}.wav"
    arguments = {
        key: (
            str(value).replace("@WAV@", str(wav_path).replace("\\", "/"))
            if isinstance(value, str)
            else value
        )
        for key, value in case.arguments.items()
    }
    context = tools.ToolContext(
        tools.parse_object_context(case.context),
        result_path,
        state_path,
    )
    try:
        tool_name = case.tool or case.name
        if tool_name == tools.CUSTOM_SCRIPT_TOOL:
            rendered = tools.render(
                tool_name,
                arguments,
                context,
                custom_script=case.custom_script.replace(
                    "@RESULT@", str(result_path).replace("\\", "/")
                ),
            )
        else:
            rendered = tools.render(tool_name, arguments, context)
    except tools.ToolError as error:
        return False, f"渲染失败：{error}"
    script = case.prefix + "\n" + rendered
    script_path = directory / f"{case.name}.praat"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [str(PRAAT), "--FULL-TRUST", "--run", str(script_path)],
        capture_output=True,
        timeout=120,
    )
    output = (completed.stdout + completed.stderr).decode("utf-16-le", "replace")
    output = output.replace("\x00", "").strip().replace("\n", " | ")
    if not state_path.is_file():
        return False, output[:400] or "脚本没有写完 chat_state.txt"
    text = (
        result_path.read_text(encoding="utf-8").strip()
        if result_path.is_file()
        else "(没有结果行)"
    )
    if case.expect and case.expect not in text:
        return False, f"结果里没有出现「{case.expect}」：{text}"
    return True, text.replace("\n", " | ")


def main() -> int:
    if not PRAAT.is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    failures = 0
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        for case in CASES:
            ok, detail = run_case(case, directory)
            print(f"{'OK  ' if ok else 'FAIL'} {case.name}: {detail}")
            if not ok:
                failures += 1
    print(f"\n{len(CASES) - failures}/{len(CASES)} 个模板用例通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
