from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import QwenConfig


class QwenError(RuntimeError):
    pass


class QwenClient:
    def __init__(self, config: QwenConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    def available(self) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}/models",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return 200 <= response.status < 300
        except (OSError, urllib.error.URLError):
            return False

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": self.config.top_p,
            "presence_penalty": self.config.presence_penalty,
            "chat_template_kwargs": {
                "enable_thinking": self.config.enable_thinking,
            },
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.request_timeout_sec,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise QwenError(f"Qwen request failed: {error}") from error

        try:
            message = result["choices"][0]["message"]
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            if content.strip():
                return content
            if reasoning.strip():
                return _final_reasoning_fallback(reasoning)
            return ""
        except (KeyError, IndexError, TypeError) as error:
            raise QwenError("Qwen returned an unexpected response.") from error

    def parse_analysis_request(
        self,
        user_text: str,
        selected_objects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        schema = {
            "reference_object": "selected object id or name",
            "learner_object": "selected object id or name",
            "language": "BCP-47 or language name",
            "phonemes": [
                {
                    "ipa": "IPA symbol",
                    "label": "optional display label",
                    "reference_start": 0.0,
                    "reference_end": 0.1,
                }
            ],
            "error_threshold": 1.25,
            "qwen_explain": True,
            "qwen_vision": False,
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Praat 本地纠音助手的请求解析器。"
                    "只输出一个 JSON 对象，不输出 Markdown。"
                    "不得编造不存在的对象 ID。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"可用对象：{json.dumps(selected_objects, ensure_ascii=False)}\n"
                    f"目标 JSON 示例：{json.dumps(schema, ensure_ascii=False)}\n"
                    f"用户请求：{user_text}"
                ),
            },
        ]
        response = self.chat(messages, max_tokens=700, temperature=0.1, json_mode=True)
        return extract_json_object(response)

    def plan_praat_command(
        self,
        user_text: str,
        object_context: str,
        history: list[dict[str, str]],
        *,
        tool_catalog: str,
        result_path: str,
        state_path: str,
    ) -> dict[str, Any]:
        system_prompt = """
你是 Praat（中文版，Windows）桌面助手的操作规划器。用户用自然语言提出操作要求，你只输出一个 JSON 对象，不输出 Markdown，不输出多余文字。

JSON 结构：
{"reply": "给用户的中文简短回复", "tool": "工具名", "arguments": {}, "script": ""}

规则：
1. tool 必须从下面的工具列表里选择；能用工具完成时 script 必须是空字符串。
2. 只有所有工具都无法完成请求时，tool 才用 "custom_script"，并在 script 里写完整 Praat 英文脚本。
3. script 必须是 Praat 脚本，绝对不能是 Python：不要出现 import、def、print、numpy、parselmouth、os 等 Python 写法。
4. 脚本里字符串一律用双引号；单引号在 Praat 中是变量插值，会直接报错。
5. 对象只能使用下方对象列表里真实存在的 id 或名称，不得编造。
6. 请求能从当前选中对象直接完成时，直接选工具，不要反问；只有请求完全无法执行时才在 reply 里提问。
7. 需要输出数值时，用 appendFileLine 写到我给出的结果文件路径。
8. 时间单位一律是秒；超出对象时长的时刻会被自动截断到对象末尾。
9. 常见需求都已经有对应工具（新建声音、截取片段、拼接声音、另存 WAV、重采样、复制对象、统计基频/强度、一次查询多条共振峰），优先用工具而不是自己写脚本。
10. 用户在句子里明确说了对象编号（例如「3 号对象」「第二个声音」）时，必须在 arguments 里用 object / object2 指出那个对象，不能留空。
11. 只有用户给出了新名字时才填 name / new_name；「复制一份」这类请求不要抄原来的名字。
""".strip()
        examples = """
示例：
用户：提取当前语音的第二共振峰带宽
输出：{"reply": "查询中间时刻的第 2 共振峰带宽。", "tool": "formant_bandwidth", "arguments": {"formant": 2}, "script": ""}
用户：查询 0.4 秒处的 F1 和 F2
输出：{"reply": "查询 0.4 秒处的第 1、2 共振峰频率。", "tool": "formant_frequency", "arguments": {"formant": "1,2", "time": 0.4}, "script": ""}
用户：把选中的声音改名为 测试
输出：{"reply": "重命名选中的声音。", "tool": "rename_object", "arguments": {"new_name": "测试"}, "script": ""}
用户：打开这个声音的编辑器
输出：{"reply": "打开编辑器。", "tool": "view_edit", "arguments": {}, "script": ""}
用户：这个声音的基频平均是多少
输出：{"reply": "统计整个声音的基频。", "tool": "pitch_statistics", "arguments": {}, "script": ""}
用户：截取 0.2 到 0.5 秒
输出：{"reply": "截取 0.2–0.5 秒的片段。", "tool": "extract_part", "arguments": {"start": 0.2, "end": 0.5}, "script": ""}
用户：生成一个 1 秒的 220 Hz 正弦音
输出：{"reply": "新建 1 秒的 220 Hz 纯音。", "tool": "create_sound", "arguments": {"duration": 1, "frequency": 220}, "script": ""}
用户：把这个声音保存成 D:/out/a.wav
输出：{"reply": "保存为 WAV 文件。", "tool": "save_sound", "arguments": {"path": "D:/out/a.wav"}, "script": ""}
用户：导入 D:/in/a.wav
输出：{"reply": "读取 wav 文件。", "tool": "custom_script", "arguments": {}, "script": "Read from file: \\"D:/in/a.wav\\""}
""".strip()
        context_message = "\n".join(
            [
                f"结果文件（脚本把数值结果写到这里）：{result_path}",
                f'完成标记文件（脚本最后一行必须是 appendFileLine: "{state_path}", "done"）：'
                f"{state_path}",
                "",
                "可用工具：",
                tool_catalog,
                "",
                "当前 Praat 对象列表（id、类、名称、是否选中）：",
                object_context,
                "",
                examples,
            ]
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt + "\n\n" + context_message,
            },
        ]
        for item in history[-8:]:
            role = item.get("role", "")
            content = item.get("content", "")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        response = self.chat(
            messages,
            max_tokens=self.config.plan_max_tokens,
            temperature=self.config.plan_temperature,
            json_mode=True,
        )
        return extract_json_object(response)

    def explain_errors(self, request: dict[str, Any], result: dict[str, Any]) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是发音训练助手。根据给定数值解释发音偏差，"
                    "不得修改分数，不得声称听到了音频。回答控制在 300 字以内。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请求：{json.dumps(request, ensure_ascii=False)}\n"
                    f"分析结果：{json.dumps(result, ensure_ascii=False)}"
                ),
            },
        ]
        return self.chat(messages, max_tokens=500, temperature=0.4).strip()

    def vision_explain(
        self,
        image_path: str | Path,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        path = Path(image_path)
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是语音学图表解释助手。只描述图中可见的曲线、"
                    "阴影区间和数值，不得重新计算发音分数。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"请求：{json.dumps(request, ensure_ascii=False)}\n"
                            f"错误摘要：{json.dumps(result.get('errors', []), ensure_ascii=False)}"
                        ),
                    },
                ],
            },
        ]
        return self.chat(messages, max_tokens=500, temperature=0.2).strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise QwenError("The model did not return a JSON object.")


def _final_reasoning_fallback(reasoning: str) -> str:
    markers = (
        "Final Decision:",
        "Final Answer:",
        "最终输出：",
        "最终答案：",
    )
    for marker in markers:
        if marker in reasoning:
            return reasoning.rsplit(marker, 1)[-1].strip()
    return reasoning.strip()
