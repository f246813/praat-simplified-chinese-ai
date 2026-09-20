"""手动回归：用真机 Praat + 真机模型跑一遍对话窗口的执行链路。

用法（仓库根目录，需要先装好 Python 依赖和本地模型服务）：

    python ai/tests/verify_chat_live.py

它会：

1. 启动 ``Praat.exe``（如果已经有 Praat 在跑就直接用）；
2. 用对话窗口真正的发送函数 ``praat_ai.chat._send_script`` 送一个建声音的脚本；
3. 检查 Praat 有没有写出 ``ai/runtime/chat_context.tsv``（对象列表回传）；
4. 让本地 Qwen 规划「把选中的声音改名为 ...」「查询 0.5 秒处的基频」等请求，
   渲染模板、送给 Praat、把结果读回来；
5. 验证改名之后对象列表里的名字也跟着更新（对话上下文不是过期快照）。

这条链路会写 ``ai/runtime/`` 并启动 GUI，所以只在手动回归时跑，不会被
``unittest discover`` 收集。需要在没有沙箱限制的环境里执行。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, tools   # noqa: E402
from praat_ai.config import load_config   # noqa: E402
from praat_ai.qwen import QwenClient   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"

CREATE_SOUND = "\n".join(
    [
        'Create Sound from formula: "tone", 1, 0, 1, 44100, '
        "~ 0.5 * sin (2*pi*220*x)",
        'appendFileLine: "@STATE@", "done"',
        "",
    ]
)


def praat_running() -> bool:
    return chat.praat_process_running(str(PRAAT))


def start_praat() -> subprocess.Popen[bytes] | None:
    if praat_running():
        print("· 已经有 Praat 在运行，直接使用它")
        return None
    if not PRAAT.is_file():
        raise SystemExit(f"没有找到 {PRAAT}")
    print("· 启动 Praat.exe")
    process = subprocess.Popen([str(PRAAT)])
    deadline = time.time() + 30
    while time.time() < deadline:
        if praat_running():
            time.sleep(6.0)   # 等窗口把消息回调挂好并进入空闲状态
            return process
        time.sleep(0.5)
    raise SystemExit("Praat 启动超时")


def context_rows() -> tuple[tools.ObjectRow, ...]:
    return tools.parse_object_context(chat.object_context())


def send(script: str) -> tuple[bool, str]:
    executable = chat.praat_executable()
    if not executable:
        raise SystemExit("没有找到 Praat 可执行文件")
    script = script.replace("@STATE@", chat.state_path().as_posix())
    ok, output = chat._send_script(executable, script)
    results = chat._read_results()
    return ok, ("；".join(results) if results else output.strip())


def ask(client: QwenClient, text: str) -> tuple[str, str]:
    rows = context_rows()
    context = tools.ToolContext(
        objects=rows,
        result_path=chat.result_path(),
        state_path=chat.state_path(),
    )
    plan = client.plan_praat_command(
        text,
        chat.object_context(),
        [],
        tool_catalog=tools.catalog_text(),
        result_path=str(chat.result_path()),
        state_path=str(chat.state_path()),
    )
    reply = str(plan.get("reply", "")).strip() or "已完成。"
    tool_name = str(plan.get("tool", "")).strip()
    if not tool_name and str(plan.get("script", "") or "").strip():
        tool_name = tools.CUSTOM_SCRIPT_TOOL
    if not tool_name:
        return reply, ""
    script = tools.render(
        tool_name,
        plan.get("arguments") or {},
        context,
        custom_script=str(plan.get("script", "") or ""),
    )
    return f"{reply}（工具 {tool_name}）", script


def main() -> int:
    failures = 0
    instances = chat.praat_process_ids(str(PRAAT)) or []
    if len(instances) > 1:
        print(
            f"!! 检测到 {len(instances)} 个 Praat 在运行（{instances}）："
            "--send 只会送给最新打开的那个，请先关掉多余的窗口再跑这个验证。"
        )
        return 2
    started = start_praat()
    config = load_config()
    client = QwenClient(config.qwen)
    if not client.available():
        print("!! 本地模型服务没响应，请先启动前端")
        failures += 1
    try:
        print("· 先刷新一次对象列表")
        refreshed, note = chat.refresh_object_context(str(PRAAT))
        print(f"  刷新{'成功' if refreshed else '失败'}：{note}")
        if not refreshed:
            failures += 1

        print("· 送一个建声音的脚本，检查对象列表回传")
        ok, detail = send(CREATE_SOUND)
        print(f"  发送{'成功' if ok else '失败'}：{detail}")
        if not ok:
            failures += 1
        rows = context_rows()
        print(f"  chat_context.tsv：{[(row.id, row.class_name, row.name) for row in rows]}")
        if not rows:
            print("  !! 没有读到对象列表")
            failures += 1

        cases = [
            "阅读当前对象的信息",
            "把当前对象改名为 测试音",
            "查询 0.5 秒处的基频",
            "把这个声音截取 0.2 到 0.5 秒",
        ]
        for text in cases:
            reply, script = ask(client, text)
            print(f"· {text}")
            print(f"  规划：{reply}")
            if not script:
                print("  （这个请求不需要执行脚本）")
                continue
            ok, detail = send(script)
            print(f"  执行{'成功' if ok else '失败'}：{detail}")
            if not ok:
                failures += 1
            if text.startswith("把当前对象改名"):
                names = [row.name for row in context_rows()]
                print(f"  改名后的对象列表：{names}")
                if not any("测试音" in name for name in names):
                    print("  !! 对象列表没有跟着刷新")
                    failures += 1
    finally:
        if started is not None:
            print("· 关闭本次启动的 Praat")
            subprocess.run(
                ["taskkill", "/PID", str(started.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
    print(f"\n结论：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
