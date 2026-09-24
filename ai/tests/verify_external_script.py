"""手动回归：把现成的（社区）``.praat`` 脚本真的跑一遍（C3）。

用法（仓库根目录，需要本机已经构建好 ``Praat.exe``）::

    python ai/tests/verify_external_script.py

这里没有「开着的 Praat」，所以用批处理模拟它：``execute(脚本)`` 就是「先建一个好
声音再跑这条脚本」，等价于在真机上有对象被选中的情况。然后：

1. 带表单的社区脚本：表单默认值要自动传进去，脚本自己 ``writeInfoLine`` 的输出
   要回到对话前端；
2. 没有表单的脚本：也要能跑；
3. 脚本自己写文件：前端要报告「它写了哪些文件」；
4. 脚本报错：要带中文说明回来（而不是把前端挂住）。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import external_script, tools   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"
TONE = 'Create Sound from formula: "tone", 1, 0, 1, 44100, ~ 0.5 * sin (2*pi*220*x)'
# 真实的对象名不会有空格（Praat 自己把空格换成下划线），这里也照真的来。
CONTEXT_TSV = "id\tclass\tname\tselected\n1\tSound\ttone\t1\n"

WITH_FORM = '''form: "Community helper"
    comment: "社区脚本常见的开头"
    positive: "Pitch floor (Hz)", "75"
    word: "Mode", "fast"
    boolean: "Verbose", 1
endform
pitchId = To Pitch: 0, pitch_floor, 600
selectObject: pitchId
mean = Get mean: 0, 0, "Hertz"
writeInfoLine: "community mean pitch = ", mean, " mode = ", mode$, " verbose = ", verbose
Remove
'''

NO_FORM = '''writeInfoLine: "no form, selected = ", selected$ ()
Save as WAV file: "community-output.wav"
'''

FAILS = '''form: "Broken"
    natural: "Count", "2"
endform
writeInfoLine: "before the error"
nosuchcommand: 1
'''


def run_batch_script(text: str, directory: Path, name: str) -> tuple[bool, str]:
    """把一段脚本当批处理跑（和 verify_chat_templates.py 一样的做法）。"""

    path = directory / f"{name}.praat"
    path.write_text(text, encoding="utf-8")
    completed = subprocess.run(
        [str(PRAAT), "--FULL-TRUST", "--run", str(path)],
        capture_output=True,
        timeout=180,
    )
    output = (completed.stdout + completed.stderr).decode("utf-16-le", "replace")
    return completed.returncode == 0, output.replace("\x00", "").strip()


def make_environment(directory: Path):
    """模拟「开着的 Praat」：先建一个好声音，再跑交给它的脚本。"""

    def execute(script: str) -> tuple[bool, list[str], str]:
        ok, output = run_batch_script(
            TONE + "\n" + script, directory, "export"
        )
        return ok, [], output

    return tools.LocalEnvironment(
        execute=execute,
        praat_executable=str(PRAAT),
        runtime_directory=directory / "runtime",
    )


def main() -> int:
    if not PRAAT.is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    failures = 0
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        context = tools.ToolContext(
            tools.parse_object_context(CONTEXT_TSV),
            directory / "chat_result.tsv",
            directory / "chat_state.txt",
        )
        environment = make_environment(directory)
        runner = tools.LOCAL_TOOLS[tools.RUN_SCRIPT_TOOL]

        # 1) 带表单的社区脚本：默认值自动传进去，输出回到前端。
        script = directory / "community-form.praat"
        script.write_text(WITH_FORM, encoding="utf-8")
        ok, lines, failure = runner.run({"path": str(script)}, context, environment)
        text = "\n".join(lines)
        good = (
            ok
            and "community mean pitch = 220" in text
            and "mode = fast" in text
            and "verbose = 1" in text
            and "Pitch floor (Hz)=75" in text
        )
        print(f"{'OK  ' if good else 'FAIL'} with-form: {text[:300] or failure}")
        failures += 0 if good else 1

        # 2) 没有表单的脚本也要能跑，并且报告它写出来的文件。
        plain = directory / "community-plain.praat"
        plain.write_text(NO_FORM, encoding="utf-8")
        ok, lines, failure = runner.run({"path": str(plain)}, context, environment)
        text = "\n".join(lines)
        good = ok and "no form, selected = Sound tone" in text and "community-output.wav" in text
        print(f"{'OK  ' if good else 'FAIL'} no-form+file: {text[:300] or failure}")
        failures += 0 if good else 1

        # 3) 脚本自己报错：中文说明 + Praat 的原文，不要抛异常。
        broken = directory / "community-broken.praat"
        broken.write_text(FAILS, encoding="utf-8")
        ok, lines, failure = runner.run({"path": str(broken)}, context, environment)
        good = (not ok) and "nosuchcommand" in failure and "批处理里看不到" in failure
        print(f"{'OK  ' if good else 'FAIL'} error-report: {failure[:300]}")
        failures += 0 if good else 1

        # 4) 认不出来的表单字段类型：要说清楚，而不是传错参数。
        weird = directory / "community-weird.praat"
        weird.write_text(
            'form: "Weird"\n    mysteryfield: "x", "1"\nendform\n', encoding="utf-8"
        )
        try:
            runner.run({"path": str(weird)}, context, environment)
            good = False
            detail = "没有拒绝这个表单"
        except tools.ToolError as error:
            good = "mysteryfield" in str(error)
            detail = str(error)
        print(f"{'OK  ' if good else 'FAIL'} unknown-field: {detail}")
        failures += 0 if good else 1

    total = 4
    print(f"\n{total - failures}/{total} 个外部脚本用例通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
