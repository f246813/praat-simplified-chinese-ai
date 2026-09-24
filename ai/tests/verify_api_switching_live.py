"""手动回归：进 API / 回本地 时本机模型服务的启停（2026-09-22 的三个新用例）。

用法（仓库根目录，需要装好本地模型 + llama-server；会真的起停 8000 端口上的服务）::

    python ai/tests/verify_api_switching_live.py

它自己带一份临时配置（``PRAAT_AI_CONFIG_PATH``：从用户的 ``ai_config.json`` 复制、
去掉 key、强制关掉 API 开关），**不动** ``ai/ai_config.json``。验三件事：

1. ``api.stop_local_service=true``（默认）：从本地切到 API → 8000 端口必须空掉；
2. ``false``：切到 API → 8000 端口**仍有服务，而且模型没变**；
3. 取消勾选 API（回本地）／切一个本地预设 → 自动把本机服务起起来，随后发一条
   真消息不再出现 ``[WinError 10061]``。

走的是对话窗口自己的那条路（``ChatWindow.on_api_settings_saved`` + 消息队列），
不是直接调 control——不然「窗口里点保存」这一环没人守着。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import api_settings, chat, config as config_module, control, qwen, server  # noqa: E402
from praat_ai.config import load_config   # noqa: E402

API_VALUES = {
    "enabled": True,
    "label": "FakeCloud",
    "base_url": "https://api.example.invalid/v1",
    "model": "deepseek-chat",
    "api_key": "sk-not-used-here",
    "request_timeout_sec": 30,
    "max_context_tokens": 32768,
    "plan_max_tokens": 800,
    "plan_temperature": 0.1,
    "vision_when_requested": False,
    "thinking_level": "medium",
    "use_world_knowledge": True,
}


def pump(window: chat.ChatWindow, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        window.root.update()
        window.flush_messages()
        time.sleep(0.1)


def wait_for(predicate, timeout: float, label: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.5)
    raise SystemExit(f"等待超时：{label}")


def port_open() -> bool:
    return control.endpoint_available(local_base_url())


def live_model() -> str:
    return Path(server.running_model(local_base_url())).name


def configured_model() -> str:
    return Path(load_config().server.model_path).name


def local_base_url() -> str:
    """本机 llama-server 的地址。

    **必须**从 ``server.host/port`` 拼，不能用 ``config.qwen.base_url``：API 模式下
    `apply_api_to_qwen` 会把 ``qwen.base_url`` 换成云端地址，拿它去探本机端口只会
    永远探不到（第一版就是这么写错的，①③ 两条会假过）。
    """

    config = load_config()
    host = config.server.host or "127.0.0.1"
    port = config.server.port or 8000
    return f"http://{host}:{port}/v1"


def main() -> int:
    real_config = config_module.default_config_path()
    if not real_config.is_file():
        print(f"没有找到 {real_config}")
        return 2
    payload = json.loads(real_config.read_text(encoding="utf-8"))
    payload.setdefault("api", {})
    payload["api"]["enabled"] = False
    payload["api"]["api_key"] = ""            # 临时副本里不留 key
    payload["api"]["stop_local_service"] = True
    presets = [item for item in payload.get("server", {}).get("presets", [])]
    if not presets:
        print("配置里没有 server.presets，这个回归需要至少一个本地预设。")
        return 2

    problems: list[str] = []
    temporary = tempfile.TemporaryDirectory()
    temp_config = Path(temporary.name) / "ai_config.json"
    temp_config.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.environ["PRAAT_AI_CONFIG_PATH"] = str(temp_config)
    print(f"· 临时配置：{temp_config}（没有动 {real_config}）")

    window = chat.ChatWindow()
    started_service = False
    try:
        pump(window, 0.5)

        # ---------- 0：先确保本机服务在跑 ----------
        print("· 先把本机模型服务起起来（约 10 秒）…")
        control.ensure_local_service(load_config())
        started_service = True
        wait_for(port_open, 120, "本机模型服务就绪")
        baseline_model = live_model()
        print(
            f"  OK  {local_base_url()} 上是 {baseline_model}；"
            f"配置里是 {configured_model()}"
        )
        if baseline_model != configured_model():
            problems.append(
                f"端口上是 {baseline_model}，配置里是 {configured_model()}"
            )

        # ---------- ① stop_local_service=True：切 API 必须把服务收掉 ----------
        values = dict(API_VALUES, stop_local_service=True)
        api_settings.save_settings(values, temp_config)
        window.on_api_settings_saved(values)
        pump(window, 3)
        closed = wait_for(lambda: not port_open(), 60, "8000 端口空掉")
        print(
            f"  {'OK' if closed else 'FAIL'}  ① stop_local_service=True：切到 API 后"
            f" 8000 端口{'已空掉' if closed else '还在'}（模型服务已停）"
        )
        if not closed:
            problems.append("① 切到 API 之后本机服务还占着 8000 端口")

        # ---------- ③ 取消 API：必须自动把服务起起来，再发一条真消息 ----------
        values = dict(API_VALUES, enabled=False)
        api_settings.save_settings(values, temp_config)
        window.on_api_settings_saved(values)
        pump(window, 3)
        print("· 取消 API 之后等窗口把本机服务起起来（约 10 秒）…")
        wait_for(port_open, 120, "取消 API 后本机服务就绪")
        print(f"  OK  自动起来了：端口上是 {live_model()}")
        client = qwen.QwenClient(load_config().qwen)
        try:
            reply = client.chat(
                [{"role": "user", "content": "只回复两个字：收到"}], max_tokens=16
            )
            ok = bool(reply.strip())
            detail = f"回答「{reply.strip()[:20]}」"
        except qwen.QwenError as error:
            ok = False
            detail = str(error)[:120]
        print(f"  {'OK' if ok else 'FAIL'}  ③ 回本地后发一条真消息：{detail}")
        if not ok:
            problems.append(f"③ 回本地后发消息失败：{detail}")

        # ---------- ② stop_local_service=False：切 API 不能动本机服务 ----------
        before = live_model()
        values = dict(API_VALUES, stop_local_service=False)
        api_settings.save_settings(values, temp_config)
        window.on_api_settings_saved(values)
        pump(window, 12)
        still_open = port_open()
        after = live_model()
        ok = still_open and after == before
        print(
            f"  {'OK' if ok else 'FAIL'}  ② stop_local_service=False：切到 API 之后"
            f" 8000 端口{'仍在、模型还是 ' + after if still_open else '被停掉了'}"
        )
        if not ok:
            problems.append(
                f"② 取消勾选之后本机服务被动了（端口在={still_open}，模型 {before}→{after}）"
            )

        # ---------- ③′ 切本地预设：也要把服务弄起来（这里先真的停掉再切） ----------
        api_settings.save_settings(dict(API_VALUES, stop_local_service=True), temp_config)
        control.stop_frontend(temp_config)
        wait_for(lambda: not port_open(), 60, "停止本机服务")
        preset_id = str(payload["server"].get("active_preset") or presets[0]["id"])
        print(f"· 切回本地预设「{preset_id}」…")
        control.apply_preset(preset_id, temp_config)
        wait_for(port_open, 120, "切预设后本机服务就绪")
        ok = live_model() == configured_model()
        print(
            f"  {'OK' if ok else 'FAIL'}  ③′ 切本地预设之后端口上是 {live_model()}"
            f"（配置 {configured_model()}）"
        )
        if not ok:
            problems.append("③′ 切本地预设之后端口上的模型和配置不一致")

        print(f"\n状态：{window.status.get()}")
    finally:
        try:
            window.close()
        except Exception:   # noqa: BLE001
            pass
        temporary.cleanup()
        os.environ.pop("PRAAT_AI_CONFIG_PATH", None)
        if started_service:
            print("· 本机模型服务保持运行（和别的真机回归一样，跑完自己按需停）")

    print(f"\n{'全部通过' if not problems else '有 %d 个问题' % len(problems)}")
    for item in problems:
        print(f"  !! {item}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
