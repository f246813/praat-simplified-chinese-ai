"""Real Praat regression for the chat-to-VOT path, using isolated synthetic audio.

Run from the project root: python ai/tests/verify_vot_dispatch.py
No running GUI/model is required; the selected model must not plan these commands.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import verify_chat_templates as templates
from praat_ai import chat, qwen, tools


def main() -> int:
    cases = [
        ("测量vot", templates.ONE_SOUND_SELECTED, templates.VOT_SOUND),
        ("爆破是0.30秒，浊音起始是0.42秒，帮我算VOT", templates.ONE_SOUND, templates.VOT_SOUND),
        ("在0.25到0.5秒之间找一下VOT", templates.ONE_SOUND, templates.VOT_SOUND),
        ("测量vot", templates.ONE_SOUND, templates.SILENT),
        ("在9到10秒之间测量VOT", templates.ONE_SOUND, templates.VOT_SOUND),
    ]
    records = []
    with tempfile.TemporaryDirectory(prefix="vot-dispatch-check-") as raw:
        directory = Path(raw)
        for index, (request, context_text, prefix) in enumerate(cases):
            result = directory / f"result-{index}.tsv"
            state = directory / f"state-{index}.txt"
            context = tools.ToolContext(tools.parse_object_context(context_text), result, state)

            def execute(script: str) -> tuple[bool, list[str], str]:
                script_path = directory / f"case-{index}.praat"
                script_path.write_text(prefix + "\n" + script, encoding="utf-8")
                process = subprocess.run(
                    [str(templates.PRAAT), "--FULL-TRUST", "--run", str(script_path)],
                    capture_output=True, timeout=30,
                )
                lines = result.read_text(encoding="utf-8").splitlines() if result.exists() else []
                return (
                    process.returncode == 0 and state.exists(), lines,
                    process.stderr.decode("utf-16-le", errors="replace") if process.returncode else "",
                )

            # No endpoint is contacted for a recognized, complete VOT command.
            outcome = chat.run_turn(
                qwen.QwenClient(qwen.QwenConfig(base_url="http://127.0.0.1:1/v1")),
                user_text=request, context_text=context_text, history=[],
                context=context, execute=execute,
            )
            records.append({
                "request": request,
                "tools": [step.tool for step in outcome.steps],
                "reply": outcome.reply,
                "failure": outcome.failure,
            })
            assert records[-1]["tools"] == ["vot"], records[-1]
            if index >= 3:
                assert outcome.failure and "未完成" in outcome.reply, records[-1]
            else:
                assert not outcome.failure and "计算公式" in outcome.reply, records[-1]
            if index == 0:
                assert "按编辑器圈选" in outcome.reply, records[-1]
            if index == 1:
                assert "120.0 毫秒" in outcome.reply, records[-1]
            print(json.dumps(records[-1], ensure_ascii=False))
    (templates.PROJECT / "test-records" / "project" / "verify-vot-dispatch-praat.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(cases)}/{len(cases)} real Praat dispatch checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
