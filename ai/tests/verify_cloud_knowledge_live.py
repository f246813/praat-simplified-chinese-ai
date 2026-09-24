"""手动回归（**会花一点点钱**）：云端模型真的会做对比、也报得出自己的模型名。

用户报的两条（2026-09-21）：

1. 让它「把选中语段和东京标准音对比」，它没用自己的世界知识，直接回了一句「已完成」
   ——那条「已完成」其实是**代码兜底**：模型既没给正文也没调工具时，界面用一句空话
   顶上了（见 chat._summary_of / run_agent_loop）；
2. 问「我是谁」时它自称「Praat 语音助手」——现在系统提示里带了身份规则
   （qwen.identity_instructions），要报**自己的模型名** + 「我被设置成 Praat 的前端」。

这个脚本走真实链路（真 config、真 HTTP、真 run_turn），不动 Praat：执行那一步用假
执行器（返回几条像样的测量值），只看模型**最终回答**里有没有比较和自己的身份。

用法（仓库根目录）::

    python ai/tests/verify_cloud_knowledge_live.py           # 先看要发几次请求
    python ai/tests/verify_cloud_knowledge_live.py --send    # 真发（会花掉极少量的钱）
    python ai/tests/verify_cloud_knowledge_live.py --send --local   # 用本地模型（不花钱，
                                                                   # 只验身份那条）

每次请求都很小（系统提示 + 工具 schema ≈ 6k token），两次一共不到一万 token 量级。
**它不会打印你的 API key。**
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

from praat_ai import chat, qwen, tools   # noqa: E402
from praat_ai.config import api_is_active, load_config   # noqa: E402


CONTEXT_TSV = "id\tclass\tname\tselected\n1\tSound\tvowel-tokyo\t1\n"

#: 假执行器返回的「测量结果」：像真测出来的一样，用来看模型会不会拿它去做对比。
FAKE_RESULTS = [
    "基频（0.500 秒处）= 208.400 Hz",
    "第 1、2 共振峰（0.400–0.600 秒）= 742.000 Hz / 1196.000 Hz",
    "时长 = 0.312 s",
]

#: 回答里出现这些词，说明它真的在拿参照系比，而不是敷衍一句「已完成」。
COMPARISON_MARKERS = ("东京", "标准", "常见", "通常", "文献", "建议", "偏", "练习")


def main() -> int:
    local_only = "--local" in sys.argv
    if "--send" not in sys.argv:
        print("这是真机回归，会向配置好的云端模型发 2 次小请求。")
        print("要真的发就加 --send：")
        print("  python ai/tests/verify_cloud_knowledge_live.py --send")
        return 0

    config = load_config()
    temporary_directory = None
    if local_only:
        # 本地小模型是严格模式：它本来就不该拿世界知识做对比，所以只验「我是谁」。
        # 用户配置是 API 模式时，自己带一份「关掉 API」的临时配置再起本地服务
        # （PRAAT_AI_CONFIG_PATH，见 guide.md §8.15.5），不动他的 ai_config.json。
        from praat_ai import config as config_module, control

        real_config = config_module.default_config_path()
        if real_config.is_file():
            payload = json.loads(real_config.read_text(encoding="utf-8"))
            if payload.get("api", {}).get("enabled"):
                temporary_directory = tempfile.TemporaryDirectory()
                local_path = Path(temporary_directory.name) / "ai_config.json"
                payload["api"]["enabled"] = False
                payload["api"]["api_key"] = ""
                local_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                os.environ["PRAAT_AI_CONFIG_PATH"] = str(local_path)
                print("· 你的配置是 API 模式：本地这一轮用临时配置（只关掉 API 开关）")

        print("· 本地模式：先把本机模型服务拉起来（只验身份那条）")
        control.start_frontend()
        config = load_config()
    elif not api_is_active(config):
        print("当前不是 API 模式：先在「API 配置…」里填好云端模型，或者加 --local。")
        return 2
    source = "本地" if local_only else "云端"
    print(f"· {source}模型：{config.qwen.model}")

    failures = 0
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        context = tools.ToolContext(
            tools.parse_object_context(CONTEXT_TSV),
            directory / "chat_result.tsv",
            directory / "chat_state.txt",
        )
        client = qwen.QwenClient(config.qwen)

        def execute(script: str) -> tuple[bool, list[str], str]:
            return True, list(FAKE_RESULTS), ""

        expected = 1
        if not local_only:
            outcome = chat.run_turn(
                client,
                user_text="把选中的这段语音和东京标准音对比一下，我的发音怎么样？",
                context_text=CONTEXT_TSV,
                history=[],
                context=context,
                execute=execute,
                native=True,
            )
            reply = outcome.reply.strip()
            print("\n· 对比类请求的回答：\n" + reply + "\n")
            ok = (
                len(reply) >= 40
                and reply not in {"已完成。", "已完成"}
                and any(marker in reply for marker in COMPARISON_MARKERS)
            )
            print(f"{'OK  ' if ok else 'FAIL'} 对比类请求给出了比较（长度 {len(reply)}）")
            failures += 0 if ok else 1
            expected += 1

        identity = chat.run_turn(
            client,
            user_text="我是谁？",
            context_text=CONTEXT_TSV,
            history=[],
            context=context,
            execute=execute,
            native=True,
        ).reply.strip()
        print("\n· 问「我是谁」的回答：\n" + identity + "\n")
        # 本地小模型可能只报名字的一部分（例如省略 .gguf），所以只硬要求那句话；
        # 模型名对不对单独打出来看。
        print(f"· 回答里提到模型名：{config.qwen.model in identity}")
        ok = (
            "我被设置成 Praat 的前端" in identity
            and "Praat 语音助手" not in identity
        )
        print(f"{'OK  ' if ok else 'FAIL'} 身份说法对（模型名 + 前端身份）")
        failures += 0 if ok else 1

    if local_only:
        from praat_ai import control

        print("· 收尾：停掉本地模型服务")
        try:
            control.stop_frontend()
        except Exception as error:   # noqa: BLE001 - 收尾失败不影响结论
            print(f"  （停服务时出错：{error}）")
        os.environ.pop("PRAAT_AI_CONFIG_PATH", None)
        if temporary_directory is not None:
            temporary_directory.cleanup()

    print(f"\n{expected - failures}/{expected} 条通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
