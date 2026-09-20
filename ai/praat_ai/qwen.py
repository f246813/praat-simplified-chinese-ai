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
            "top_p": 0.8,
            "presence_penalty": 1.5,
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
