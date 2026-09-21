from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .config import QwenConfig


class QwenError(RuntimeError):
    pass


#: 规划接口的取值（见 :func:`planner_mode`）。
TOOLS_MODE = "tools"
JSON_MODE = "json"
AUTO_MODE = "auto"

#: ``QwenConfig.provider`` 的取值：``llama.cpp``（本地 llama-server）/
#: ``api``（云端 OpenAI 兼容服务，见 :class:`praat_ai.config.ApiConfig`）。
LOCAL_PROVIDER = "llama.cpp"
API_PROVIDER = "api"

#: 切换规划接口的环境变量：``tools`` / ``json`` / ``auto``（默认）。
PLANNER_MODE_ENV = "PRAAT_AI_PLANNER"


def planner_mode() -> str:
    """这次用哪种规划接口。

    - ``tools``：把工具的 JSON Schema 放进 ``tools``，读模型返回的 ``tool_calls``
      （llama-server 原生 function calling，实测本机 Qwen3.5-2B 支持，见
      ai/docs/adr/ADR-003）。
    - ``json``：老的「把工具清单和十几条规则写进提示词，让模型自己拼 JSON」。
    - ``auto``（默认）：先走 ``tools``；模型既没给工具调用、也没给任何正文时退回
      ``json``。换成不支持工具调用的服务端时，直接设 ``PRAAT_AI_PLANNER=json``
      可以省掉这一趟。
    """

    value = os.getenv(PLANNER_MODE_ENV, "").strip().casefold()
    if value in {"json", "prompt", "legacy"}:
        return JSON_MODE
    if value in {"tools", "tool", "function_calling", "fc"}:
        return TOOLS_MODE
    return AUTO_MODE


#: 原生 function calling 用的系统提示：只写业务规则和现场信息，
#: 工具的说明/参数/必填项都在 JSON Schema 里（不再靠提示词列清单）。
TOOL_PLANNER_INSTRUCTIONS = """
你是 Praat（中文版，Windows）桌面助手的操作规划器。用户用自然语言提出操作要求，你通过工具调用来完成，不要输出 Markdown。

规则：
1. 能用一个工具完成就不要写自定义脚本；只有所有工具都做不到时才用 custom_script。
2. custom_script 里必须是 Praat 英文脚本，绝对不能是 Python：不要出现 import、def、print、numpy、parselmouth、os。
3. Praat 脚本里字符串一律用双引号；单引号在 Praat 中是变量插值，会直接报错。
4. 对象只能使用对象列表里真实存在的 id 或名称，不得编造。
5. 用户明确说了对象编号（例如「3 号对象」「第二个声音」）时，object / object2 必须填那个对象。
6. 用户说「这个声音」「当前对象」时，指的是下面标着「当前选中」的那一个，它往往不是 1 号对象，别习惯性写 1。
7. 用户说法里带对象类型时按类型选：说「这个 TextGrid」就用 TextGrid，不要因为别的类型是当前选中就写错。
8. 没有对应工具的测量（例如 CPP）不许拿别的量代替；这时在回复里直说做不到，并说明还缺什么。
9. 请求能从当前选中对象直接完成时就直接调用工具，不要反问；只有完全无法执行时才在回复里提问。
10. 回复里只能用工具结果里出现过的数字、名称和文件名，一个都不要自己编造或推算；
    结果里没有的信息就直说没有。
11. 只做用户要求的那件事：不要顺手多做别的操作，也不要重复调用同一个工具；
    上一步的结果已经够回答时，直接回答，不要再调工具。
""".strip()


def history_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """把对话历史转成 messages（接口不认的字段一律丢掉）。"""

    messages: list[dict[str, Any]] = []
    for item in history:
        role = str(item.get("role", ""))
        content = str(item.get("content", "") or "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


# ---------------------------------------------------------------------------
# A5：上下文的 token 预算。
#
# 以前是死规矩：历史只带最近 8 条、对象列表整份塞进 system prompt。可 ctx 只有
# 8192，而光工具 schema 就有 18k 字符（≈5k token），所以长对话或长对象列表时会被
# 服务端**静默**截掉——用户看到的是模型突然「忘了」前面说过什么。现在按预算算，
# 并且把「省掉了什么」写出来（prompt 里 + 对话窗口的提示行）。
# ---------------------------------------------------------------------------

#: 给服务端留的余量（消息包装、工具调用回灌这些零碎开销）。
SAFETY_TOKENS = 200


def estimate_tokens(text: str) -> int:
    """粗略估 token 数：中日韩字符 ≈ 1 字 1 个，其余（ASCII/JSON 结构）≈ 4 字符 1 个。

    只要「够准」就行：用来决定该丢多少历史，不需要和分词器完全一致（真按词表算得
    拉一个 tokenizer，而本地只有 llama-server 的 HTTP 接口）。
    """

    if not text:
        return 0
    wide = 0
    narrow = 0
    for character in text:
        if ord(character) >= 0x2E80:   # CJK 部首/汉字/全角标点/假名/谚文…
            wide += 1
        else:
            narrow += 1
    return wide + (narrow + 3) // 4


def history_budget(
    max_context_tokens: int,
    *,
    instructions: str = "",
    tool_schemas: Any = (),
    user_text: str = "",
    response_tokens: int = 700,
) -> int:
    """这次请求还能给对话历史留多少 token。

    ``max_context_tokens`` 是配置里的上下文窗口；工具 schema、系统提示、用户这句话
    和留给模型的回答都要先扣掉，剩下的才是历史能用的。
    """

    overhead = (
        estimate_tokens(instructions or "")
        + estimate_tokens(user_text or "")
        + int(response_tokens)
        + SAFETY_TOKENS
    )
    schemas = list(tool_schemas or ())
    if schemas:
        overhead += estimate_tokens(json.dumps(schemas, ensure_ascii=False))
    return max(0, int(max_context_tokens) - overhead)


def trim_history(
    history: list[dict[str, str]], *, max_tokens: int
) -> tuple[list[dict[str, Any]], int]:
    """按预算从**最近**往回留对话历史，返回 ``(messages, 丢掉的条数)``。

    只留「从某句用户消息开始」的完整后段：如果留下来的第一句是 assistant 的回答，
    说明它对应的那句用户消息被截掉了，把它也丢掉——宁可少带一轮，也别给模型半截
    上下文。
    """

    messages: list[dict[str, Any]] = []
    used = 0
    for item in reversed(list(history or [])):
        role = str(item.get("role", ""))
        content = str(item.get("content", "") or "")
        if role not in {"user", "assistant"} or not content:
            continue
        cost = estimate_tokens(content) + 4
        if used + cost > max_tokens:
            break
        messages.append({"role": role, "content": content})
        used += cost
    messages.reverse()
    if messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages, max(0, len(history or []) - len(messages))


def trim_object_context(context_text: str, *, max_tokens: int) -> tuple[str, int]:
    """对象列表太长时只列一部分，并写清楚省掉了多少个（返回 ``(文本, 省掉的行数)``）。

    表头和**当前选中**那一行一定留着：提示词第 6 条（「当前对象往往不是 1 号」）就
    靠这一行；如果选中对象排得很靠后，会把它单独补进来。
    """

    lines = [line for line in (context_text or "").splitlines() if line.strip()]
    if len(lines) <= 1:
        return context_text, 0
    header, rows = lines[0], lines[1:]
    if estimate_tokens(context_text) <= max_tokens:
        return context_text, 0

    kept: list[str] = []
    used = estimate_tokens(header) + 4
    for row in rows:
        cost = estimate_tokens(row) + 1
        if kept and used + cost > max_tokens:
            break
        kept.append(row)
        used += cost

    selected = ""
    for row in rows:
        cells = row.split("\t")
        if len(cells) >= 4 and cells[3] == "1":
            selected = f"{cells[0]} 号「{cells[2]}」"
            if row not in kept:
                kept.append(row)
            break
    hidden = len(rows) - len(kept)
    note = (
        f"（对象列表一共 {len(rows)} 个，这里只列了 {len(kept)} 个；"
        f"还有 {hidden} 个没列出"
    )
    note += f"。当前选中是 {selected}）" if selected else "）"
    return "\n".join([header, *kept, note]), hidden


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """``tool_calls[].function.arguments`` 是 JSON 字符串，解析成 dict。"""

    if isinstance(raw, Mapping):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            value = extract_json_object(text)
        except QwenError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def extract_tool_actions(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把一次响应里的 ``tool_calls`` 变成 ``[{"tool": ..., "arguments": {...}}]``。

    模型可能一次给多个调用（实测同一句话里问两个时刻，它会给两个 ``pitch`` 调用），
    顺序就是它想执行的顺序。``id`` 也带上：回灌结果时要按 ``tool_call_id`` 对上。
    """

    calls = message.get("tool_calls") or []
    actions: list[dict[str, Any]] = []
    if not isinstance(calls, list):
        return actions
    for index, call in enumerate(calls):
        if not isinstance(call, Mapping):
            continue
        function = call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name", "") or "").strip()
        if not name:
            continue
        actions.append(
            {
                "tool": name,
                "arguments": _parse_tool_arguments(function.get("arguments")),
                "id": str(call.get("id", "") or f"call-{index + 1}"),
            }
        )
    return actions


#: 模型写在正文里的工具调用（Qwen 的文本格式）。
_TEXT_TOOL_CALL = re.compile(r"<tool_call\s*>(.*?)</tool_call\s*>", re.DOTALL | re.IGNORECASE)
_TEXT_FUNCTION = re.compile(r"<function\s*=\s*([\w.\-]+)\s*>", re.IGNORECASE)
_TEXT_PARAMETER = re.compile(r"<parameter\s*=\s*([\w.\-]+)\s*>", re.IGNORECASE)


def parse_text_tool_calls(content: str) -> tuple[list[dict[str, Any]], str]:
    """解析模型写在**正文里**的 ``<tool_call>`` 文本形式，返回 ``(动作, 剩下的文字)``。

    本机 llama-server 没开 ``--jinja`` 时，小模型偶尔不返回结构化的 ``tool_calls``，
    而是把 Qwen 的文本格式塞进 ``content``::

        <tool_call>
        <function=spectrogram>
        <parameter=name>
        Spectrum_03
        </parameter>
        </function>
        </tool_call>

    以前这串 XML 会被当成"最终回答"显示给用户。这里把它解析成工具调用（参数值是
    字符串，工具自己的解析函数都接受），并把 XML 之外的文字留给用户看。模型被截断
    （只有开头没有 ``</tool_call>``）时也能解析，剩下的半截不会再显示出来。
    """

    text = content or ""
    actions: list[dict[str, Any]] = []
    blocks = _TEXT_TOOL_CALL.findall(text)
    if not blocks:
        first = _TEXT_FUNCTION.search(text)
        if first:
            # 模型被 max_tokens 截断，只有开头：把 <function=…> 之后的部分当一个块。
            blocks = [text[first.start() :]]
    for index, block in enumerate(blocks):
        functions = list(_TEXT_FUNCTION.finditer(block))
        for order, function in enumerate(functions):
            # 一个块里可能有多个 <function=…>，各自取到下一个函数标签为止。
            tail_start = (
                functions[order + 1].start() if order + 1 < len(functions) else len(block)
            )
            body = block[function.end() : tail_start]
            arguments: dict[str, Any] = {}
            for parameter in _TEXT_PARAMETER.finditer(body):
                key = parameter.group(1)
                tail = body[parameter.end() :]
                end = re.search(r"</parameter\s*>", tail, re.IGNORECASE)
                raw = tail[: end.start()] if end else tail
                arguments[key] = raw.strip()
            actions.append(
                {
                    "tool": function.group(1),
                    "arguments": arguments,
                    "id": f"text-{index + 1}-{order + 1}",
                }
            )
    if not actions:
        return [], text.strip()

    leftover = _TEXT_TOOL_CALL.sub("", text)
    if _TEXT_FUNCTION.search(leftover):
        # 没有闭合标签（模型被 max_tokens 截断）：从 <tool_call> / <function= 起全不要。
        leftover = re.split(r"<tool_call\s*>|<function\s*=", leftover, maxsplit=1, flags=re.IGNORECASE)[0]
    return actions, leftover.strip()


def assistant_tool_message(
    message: Mapping[str, Any],
    actions: list[dict[str, Any]] | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """把模型那次「工具调用」的响应整理成可以回传的 assistant 消息。

    只留 ``role`` / ``content`` / ``tool_calls``：``reasoning_content`` 这类字段
    各家服务端的接受度不一样，回灌时不需要它（推理内容不参与下一轮对话）。

    ``actions`` 由调用方给出（正文里那串文本形式的调用也要按同样的顺序回传，
    否则后面每条 ``role: tool`` 的 id 就对不上了）。
    """

    parsed = extract_tool_actions(message) if actions is None else actions
    calls: list[dict[str, Any]] = []
    for action in parsed:
        calls.append(
            {
                "id": str(action.get("id", "") or "call-1"),
                "type": "function",
                "function": {
                    "name": action["tool"],
                    "arguments": json.dumps(action["arguments"], ensure_ascii=False),
                },
            }
        )
    if content is None:
        raw = message.get("content") or ""
        content = raw if isinstance(raw, str) else ""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": calls,
    }


def tool_result_message(call_id: str, content: str) -> dict[str, Any]:
    """一次工具执行的观察结果，按 OpenAI 的 ``role: tool`` 形状回灌。"""

    return {"role": "tool", "tool_call_id": call_id, "content": content}


def selected_object_hint(object_context: str) -> str:
    """把「当前选中哪个对象」单独写一句，模型不会误挑同名列表里的第一条。"""

    for line in (object_context or "").splitlines():
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) >= 4 and parts[0].isdigit() and parts[3] == "1":
            return f"当前选中：id {parts[0]}（{parts[1]} {parts[2]}）"
    return "当前没有选中任何对象。"


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
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        message = self.chat_message(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            tools=tools,
        )
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(reasoning, str) and reasoning.strip():
            return _final_reasoning_fallback(reasoning)
        return ""

    def chat_message(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """发一次请求，返回原始的 ``message`` 对象（含 ``tool_calls``）。"""

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": self.config.top_p,
            "presence_penalty": self.config.presence_penalty,
        }
        if self.config.provider != API_PROVIDER:
            # llama.cpp 专有：用模型自带的 chat 模板（多轮里把工具结果作为
            # role=tool 回灌，没有这一条小模型会跑偏，见 ADR-004）。
            # 云端 OpenAI 兼容服务不认这个字段，所以 API 模式不带它。
            payload["chat_template_kwargs"] = {
                "enable_thinking": self.config.enable_thinking,
            }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        try:
            result = self._post(payload)
        except QwenError as error:
            # 新一点的云端模型不认 max_tokens（要 max_completion_tokens），
            # 报错里提到它时换个字段名再试一次，别让用户自己去猜。
            if "max_completion_tokens" not in str(error):
                raise
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = max_tokens
            result = self._post(payload)

        try:
            message = result["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise QwenError("Qwen returned an unexpected response.") from error
        if not isinstance(message, dict):
            raise QwenError("Qwen returned an unexpected response.")
        return message

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发一次 ``/chat/completions``，返回解析后的 JSON。"""

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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", errors="replace")[:300]
            except Exception:   # noqa: BLE001 - 读不到就算了
                detail = ""
            raise QwenError(
                f"HTTP {error.code} {error.reason}：{detail or error}"
            ) from error
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise QwenError(f"Qwen request failed: {error}") from error

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
        tool_schemas: list[dict[str, Any]] | None = None,
        tool_labels: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """规划一次操作，返回 ``{"reply", "tool", "arguments", "script", "actions"}``。

        默认走原生 function calling：工具的 JSON Schema 交给 llama-server，读回来的
        ``tool_calls`` 直接就是工具名 + 参数，不用模型自己拼 JSON（也不用把十几条
        格式规则写进提示词）。``PRAAT_AI_PLANNER=json`` 可以退回老接口，排障用。
        """

        mode = planner_mode()
        if mode != JSON_MODE and tool_schemas:
            plan = self._plan_with_tools(
                user_text,
                object_context,
                history,
                tool_schemas=tool_schemas,
                tool_labels=dict(tool_labels or {}),
                result_path=result_path,
                state_path=state_path,
            )
            if plan is not None:
                return plan
        return self._plan_with_json(
            user_text,
            object_context,
            history,
            tool_catalog=tool_catalog,
            result_path=result_path,
            state_path=state_path,
        )

    def _plan_with_tools(
        self,
        user_text: str,
        object_context: str,
        history: list[dict[str, str]],
        *,
        tool_schemas: list[dict[str, Any]],
        tool_labels: dict[str, str],
        result_path: str,
        state_path: str,
    ) -> dict[str, Any] | None:
        """原生 function calling 那条路；返回 ``None`` 表示「退回 JSON 接口」。"""

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": TOOL_PLANNER_INSTRUCTIONS
                + "\n\n"
                + self._tool_context(result_path, state_path, object_context),
            },
        ]
        messages.extend(history_messages(history))
        messages.append({"role": "user", "content": user_text})
        message = self.chat_message(
            messages,
            tools=tool_schemas,
            max_tokens=self.config.plan_max_tokens,
            temperature=self.config.plan_temperature,
        )
        actions = extract_tool_actions(message)
        content = message.get("content") or ""
        reply = content.strip() if isinstance(content, str) else ""
        if not actions:
            if reply:
                # 模型选择只回话、不执行动作（例如「你好」或「这个做不到」）。
                return {"reply": reply, "tool": "", "arguments": {}, "script": "", "actions": []}
            if planner_mode() == TOOLS_MODE:
                raise QwenError("模型没有返回工具调用，也没有给出任何回复。")
            return None
        if not reply:
            # 只给了工具调用、没写回话：用工具说明兜一句，别让对话窗口显示空白。
            reply = tool_labels.get(actions[0]["tool"], "") or f"执行 {actions[0]['tool']}。"
        plan: dict[str, Any] = {
            "reply": reply,
            "actions": actions,
            "tool": actions[0]["tool"],
            "arguments": actions[0]["arguments"],
            "script": "",
        }
        return plan

    def _tool_context(
        self, result_path: str, state_path: str, object_context: str
    ) -> str:
        return "\n".join(
            [
                f"结果文件（脚本把数值结果写到这里）：{result_path}",
                f'完成标记文件（脚本最后一行必须是 appendFileLine: "{state_path}", "done"）：'
                f"{state_path}",
                "",
                selected_object_hint(object_context),
                "",
                "当前 Praat 对象列表（id、类、名称、是否选中）：",
                object_context,
            ]
        )

    def _plan_with_json(
        self,
        user_text: str,
        object_context: str,
        history: list[dict[str, str]],
        *,
        tool_catalog: str,
        result_path: str,
        state_path: str,
    ) -> dict[str, Any]:
        """老的提示词 + JSON 接口（``PRAAT_AI_PLANNER=json`` 或工具接口失败时用）。"""

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
12. 用户说「这个声音」「当前对象」时指的就是下面标着「当前选中」的那一个；它往往不是 1 号对象，别习惯性写 1。
13. 用户说法里带对象类型时按类型选：说「这个 TextGrid」就用 TextGrid，说「这个声音」就用 Sound；不要因为另一个类型的对象是当前选中就写错。
14. 没有对应工具的测量（例如 CPP）绝不能拿别的量代替；reply 里直说做不到，并说明还缺什么。
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
用户：在 0.28 到 0.45 秒之间找 VOT
输出：{"reply": "在这个范围里估计 VOT。", "tool": "vot", "arguments": {"from": 0.28, "to": 0.45}, "script": ""}
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
                selected_object_hint(object_context),
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


def probe_api(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """试一下这个 API 能不能用（「API 配置」窗口里的「测试连接」）。

    只发一条极小的对话请求：能拿到回复就说明地址、key、模型名三样都对。比只查
    ``/models`` 更靠得住——有些网关的 ``/models`` 是假的或者不列全部模型。
    """

    client = QwenClient(
        QwenConfig(
            base_url=(base_url or "").strip().rstrip("/"),
            model=(model or "").strip(),
            api_key=(api_key or "EMPTY"),
            provider=API_PROVIDER,
            request_timeout_sec=max(5, int(timeout)),
            plan_max_tokens=16,
        )
    )
    try:
        message = client.chat_message(
            [{"role": "user", "content": "ping"}],
            max_tokens=16,
            temperature=0.0,
        )
    except QwenError as error:
        return False, str(error)
    text = str(message.get("content") or message.get("reasoning_content") or "").strip()
    if not text:
        return True, f"连接成功（{model} 回了空内容，但接口是通的）。"
    return True, f"连接成功：{model} 回了「{text[:40]}」。"
