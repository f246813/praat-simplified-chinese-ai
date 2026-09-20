"""手动回归：把每个对话工具模板放进真实 Praat 批处理里跑一遍。

用法（仓库根目录）：

    python ai/tests/verify_chat_templates.py

它不依赖 unittest，也不会被 ``unittest discover`` 收集；需要本机已经构建好
``Praat.exe``。每个用例都会新建一个 Sound，渲染模板，检查脚本是否写出
``chat_state.txt`` 和结果文件。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import tools   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"

CONTEXT = "id\tclass\tname\tselected\n1\tSound\tSound tone\t1\n"

CREATE_SOUND = (
    'Create Sound from formula: "tone", 1, 0, 1, 44100, ~ 0.5 * sin (2*pi*220*x)'
)

CASES: tuple[tuple[str, dict[str, object]], ...] = (
    ("duration", {}),
    ("formant_bandwidth", {"formant": 2}),
    ("formant_frequency", {"formant": 2, "time": 0.4}),
    ("pitch", {"time": 0.5}),
    ("intensity", {}),
    ("select_object", {}),
    ("rename_object", {"new_name": "改名测试"}),
)


def run_case(name: str, arguments: dict[str, object], directory: Path) -> bool:
    result_path = directory / f"{name}-result.tsv"
    state_path = directory / f"{name}-state.txt"
    context = tools.ToolContext(
        tools.parse_object_context(CONTEXT),
        result_path,
        state_path,
    )
    script_path = directory / f"{name}.praat"
    script_path.write_text(
        CREATE_SOUND + "\n" + tools.render(name, arguments, context),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [str(PRAAT), "--FULL-TRUST", "--run", str(script_path)],
        capture_output=True,
        timeout=120,
    )
    if state_path.is_file():
        text = result_path.read_text(encoding="utf-8").strip() or "(无结果行)"
        print(f"OK   {name}: {text}".replace("\n", " | "))
        return True
    output = (completed.stdout + completed.stderr).decode("utf-8", "ignore")
    print(f"FAIL {name}:\n{output.replace(chr(0), '').strip()[:400]}")
    return False


def main() -> int:
    if not PRAAT.is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    failures = 0
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        for name, arguments in CASES:
            if not run_case(name, arguments, directory):
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
