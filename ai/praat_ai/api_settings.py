"""「前端 → API 配置」：填 API key 接云端大模型（OpenAI 兼容接口）。

前端默认连本机的 llama-server；这个窗口让用户改接一个**更大的云端模型**：
填服务商、地址（Base URL）、模型名和 API key，点「测试连接」确认能用，保存后
前端立刻改用它（见 :func:`praat_ai.config.apply_api_to_qwen`），本地 llama-server
那份配置原样留着，取消勾选「启用」就能回去。

两个入口共用同一份实现：

- Praat 菜单「前端 → API 配置…」→ `ai/start_api_settings.py` 起一个**独立进程**
  → `ai/run_api_settings.py` → 本模块的 :func:`run_standalone`（自己起一个 Tk
  根窗口）。**别改回** `run_ai_control.py api-config`：那条路是阻塞式的
  （Praat 会读子进程输出直到它退出），窗口开着的时候 Praat 整个不响应，
  缩窗口就变幽灵窗口，见 guide.md §8.15.2；
- 对话窗口里的「API 配置…」按钮 → :class:`ApiSettingsDialog`（挂在对话窗口上）。

API key 只写进 ``ai_config.json``（该文件在 .gitignore 里，不会进仓库）；也可以用
环境变量 ``PRAAT_AI_API_KEY`` 覆盖，界面里留空即可。窗口里 key 默认打码显示。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from . import qwen
from .config import AppConfig, load_config, normalize_thinking_level


#: 常见服务商的默认地址和示例模型（第一个是给本地 OpenAI 兼容网关用的）。
#: 都是 OpenAI 兼容的 ``/v1`` 接口；用户也可以自己改地址接别的网关。
PROVIDERS: tuple[dict[str, str], ...] = (
    {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "hint": "deepseek-chat / deepseek-reasoner",
    },
    {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "hint": "gpt-4o-mini / gpt-4o",
    },
    {
        "label": "阿里云百炼（通义千问）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "hint": "qwen-max / qwen-plus",
    },
    {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "hint": "glm-4-plus / glm-4-flash",
    },
    {
        "label": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "hint": "moonshot-v1-8k / moonshot-v1-128k",
    },
    {
        "label": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "hint": "可用的开源大模型很多，key 在官网申请",
    },
    {
        "label": "自定义 / 本机网关",
        "base_url": "http://127.0.0.1:8000/v1",
        "model": "local-model",
        "hint": "Ollama、LM Studio、vLLM 这类本机 OpenAI 兼容服务",
    },
)

#: 默认值（新建配置时用）。
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "label": "",
    "base_url": "",
    "model": "",
    "api_key": "",
    "request_timeout_sec": 120,
    "max_context_tokens": 32768,
    "plan_max_tokens": 1500,
    "plan_temperature": 0.1,
    "vision_when_requested": False,
    "thinking_level": "medium",
    "use_world_knowledge": True,
}

#: 「思考档位」下拉框的显示文字 → 配置里的值（见 config.THINKING_LEVELS）。
THINKING_CHOICES: tuple[tuple[str, str], ...] = (
    ("自动（服务端默认）", "auto"),
    ("关闭（最快）", "off"),
    ("低", "low"),
    ("中（推荐）", "medium"),
    ("高（最慢、最深）", "high"),
)


def thinking_choice_label(level: str) -> str:
    """把配置里的思考档位翻成下拉框里的显示文字。"""

    wanted = normalize_thinking_level(level)
    for label, value in THINKING_CHOICES:
        if value == wanted:
            return label
    return THINKING_CHOICES[0][0]


def settings_from_config(config: AppConfig) -> dict[str, Any]:
    """把当前配置读成一份「窗口里的值」（用来预填界面）。"""

    api = config.api
    values = dict(DEFAULTS)
    values.update(
        {
            "enabled": bool(api.enabled),
            "label": api.label,
            "base_url": api.base_url,
            "model": api.model,
            "api_key": api.api_key,
            "request_timeout_sec": api.request_timeout_sec,
            "max_context_tokens": api.max_context_tokens,
            "plan_max_tokens": api.plan_max_tokens,
            "plan_temperature": api.plan_temperature,
            "vision_when_requested": bool(api.vision_when_requested),
            "thinking_level": api.thinking_level,
            "use_world_knowledge": bool(api.use_world_knowledge),
        }
    )
    return values


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalize_settings(values: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """整理界面上的值，返回 ``(干净的值, 错误列表)``（错误是中文，直接显示给用户）。"""

    enabled = bool(values.get("enabled"))
    base_url = str(values.get("base_url", "") or "").strip().rstrip("/")
    model = str(values.get("model", "") or "").strip()
    errors: list[str] = []
    if enabled and not base_url:
        errors.append("启用 API 时必须填 API 地址（Base URL）。")
    if enabled and not model:
        errors.append("启用 API 时必须填模型名。")
    if base_url and not base_url.casefold().startswith(("http://", "https://")):
        errors.append("API 地址要以 http:// 或 https:// 开头。")
    if errors:
        enabled = False
    clean = {
        "enabled": enabled,
        "label": str(values.get("label", "") or "").strip(),
        "base_url": base_url,
        "model": model,
        "api_key": str(values.get("api_key", "") or "").strip(),
        "request_timeout_sec": _as_int(
            values.get("request_timeout_sec"), 120, 10, 600
        ),
        "max_context_tokens": _as_int(
            values.get("max_context_tokens"), 32768, 2048, 1_000_000
        ),
        "plan_max_tokens": _as_int(values.get("plan_max_tokens"), 1500, 128, 32768),
        "plan_temperature": _as_float(
            values.get("plan_temperature"), 0.1, 0.0, 2.0
        ),
        "vision_when_requested": bool(values.get("vision_when_requested")),
        "thinking_level": normalize_thinking_level(values.get("thinking_level")),
        "use_world_knowledge": bool(values.get("use_world_knowledge", True)),
    }
    return clean, errors


def save_settings(
    values: Mapping[str, Any],
    config_path: str | Path | None = None,
    *,
    verified: bool = False,
) -> dict[str, Any]:
    """写入 ``api`` 配置节（校验不过就抛 ``ValueError``）。

    ``verified=True``（刚点过「测试连接」并成功）会记下时间，窗口和状态里能显示
    「最近验证」；只影响显示，不参与任何逻辑。
    """

    from . import control   # 延迟导入：control 也 import 本模块，避免循环

    clean, errors = normalize_settings(values)
    if errors:
        raise ValueError("；".join(errors))
    if verified:
        import datetime

        clean["verified_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        # 改了地址/模型/key 就作废上一次的验证时间。
        clean["verified_at"] = ""
    # 思考档位是两条路共用的（本地翻成 enable_thinking、云端翻成 reasoning_effort），
    # 所以同时写进 ``qwen`` 节；其余字段只属于 ``api`` 节。
    return control.update_config(
        {
            "api": clean,
            "qwen": {"thinking_level": clean["thinking_level"]},
        },
        config_path,
    )


class ApiSettingsDialog:
    """「API 配置」小窗口（挂在对话窗口上；也用 :func:`run_standalone` 独立打开）。"""

    def __init__(
        self,
        parent,
        *,
        config: AppConfig | None = None,
        config_path: str | Path | None = None,
        on_saved: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self._tk = tk
        self._messagebox = messagebox
        self.config_path = config_path
        self.on_saved = on_saved
        self.values = settings_from_config(config or load_config(config_path))
        self.verified = bool(
            (config or load_config(config_path)).api.verified_at
        )

        self.window = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.window.title("API 配置")
        self.window.resizable(False, False)
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass

        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)

        self.enabled = tk.BooleanVar(value=bool(self.values["enabled"]))
        ttk.Checkbutton(
            frame,
            text="使用云端 API 模型（勾上后不再用本机 llama-server）",
            variable=self.enabled,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(frame, text="服务商").grid(row=1, column=0, sticky="w", pady=3)
        self.provider = tk.StringVar(value=self._provider_for(self.values))
        self.provider_box = ttk.Combobox(
            frame,
            textvariable=self.provider,
            values=[item["label"] for item in PROVIDERS],
            width=34,
        )
        self.provider_box.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
        self.provider_box.bind("<<ComboboxSelected>>", self._on_provider)

        ttk.Label(frame, text="API 地址").grid(row=2, column=0, sticky="w", pady=3)
        self.base_url = tk.StringVar(value=self.values["base_url"])
        ttk.Entry(frame, textvariable=self.base_url, width=46).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=3
        )

        ttk.Label(frame, text="模型名").grid(row=3, column=0, sticky="w", pady=3)
        self.model = tk.StringVar(value=self.values["model"])
        ttk.Entry(frame, textvariable=self.model, width=46).grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=3
        )

        ttk.Label(frame, text="API Key").grid(row=4, column=0, sticky="w", pady=3)
        self.api_key = tk.StringVar(value=self.values["api_key"])
        self.key_entry = ttk.Entry(
            frame, textvariable=self.api_key, width=34, show="•"
        )
        self.key_entry.grid(row=4, column=1, sticky="ew", pady=3)
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="显示", variable=self.show_key, command=self._toggle_key
        ).grid(row=4, column=2, sticky="w", padx=(6, 0))

        ttk.Label(frame, text="超时(秒)").grid(row=5, column=0, sticky="w", pady=3)
        self.timeout = tk.StringVar(value=str(self.values["request_timeout_sec"]))
        ttk.Entry(frame, textvariable=self.timeout, width=8).grid(
            row=5, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="上下文 token").grid(row=6, column=0, sticky="w", pady=3)
        self.context_tokens = tk.StringVar(value=str(self.values["max_context_tokens"]))
        ttk.Entry(frame, textvariable=self.context_tokens, width=8).grid(
            row=6, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="最大回复 token").grid(row=7, column=0, sticky="w", pady=3)
        self.plan_tokens = tk.StringVar(value=str(self.values["plan_max_tokens"]))
        ttk.Entry(frame, textvariable=self.plan_tokens, width=8).grid(
            row=7, column=1, sticky="w", pady=3
        )

        # 思考档位：云端翻成 reasoning_effort，本地翻成 enable_thinking
        # （见 qwen.thinking_request_fields）。默认「中」——云端大模型够聪明，
        # 档位太低会把「先想再规划」这一步省掉。
        ttk.Label(frame, text="思考档位").grid(row=8, column=0, sticky="w", pady=3)
        self.thinking_choice = tk.StringVar(
            value=thinking_choice_label(self.values["thinking_level"])
        )
        ttk.Combobox(
            frame,
            textvariable=self.thinking_choice,
            values=[label for label, _ in THINKING_CHOICES],
            state="readonly",
            width=18,
        ).grid(row=8, column=1, sticky="w", pady=3)
        ttk.Label(
            frame,
            text="越高越慢，但测量规划更稳",
            foreground="#6B7280",
        ).grid(row=8, column=2, sticky="w", padx=(6, 0))

        # 允许云端模型发挥自己的语言学知识（本地小模型永远不让，免得编数字）。
        self.world_knowledge = tk.BooleanVar(
            value=bool(self.values["use_world_knowledge"])
        )
        ttk.Checkbutton(
            frame,
            text="允许它用自己的语言学知识解释、举例（测量数字仍只来自工具结果）",
            variable=self.world_knowledge,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(2, 0))

        hint = ttk.Label(
            frame,
            text=(
                "填完点「测试连接」确认；key 只存在 ai_config.json（已 gitignore），"
                "也可以用环境变量 PRAAT_AI_API_KEY。"
            ),
            foreground="#6B7280",
            wraplength=420,
            justify="left",
        )
        hint.grid(row=10, column=0, columnspan=3, sticky="w", pady=(8, 2))

        buttons = ttk.Frame(frame)
        buttons.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        buttons.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value=self._verified_text())
        ttk.Label(buttons, textvariable=self.status, foreground="#374151").grid(
            row=0, column=0, sticky="w"
        )
        self.test_button = ttk.Button(
            buttons, text="测试连接", width=10, command=self.test_connection
        )
        self.test_button.grid(row=0, column=1, padx=(6, 0))
        ttk.Button(buttons, text="保存", width=8, command=self.save).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(buttons, text="取消", width=8, command=self.close).grid(
            row=0, column=3, padx=(6, 0)
        )

    # ---------------------------------------------------------------- 交互

    def _provider_for(self, values: Mapping[str, Any]) -> str:
        for item in PROVIDERS:
            if item["base_url"] == values.get("base_url"):
                return item["label"]
        return str(values.get("label") or "")

    def _verified_text(self) -> str:
        if self.verified:
            return "上次测试连接成功。"
        return "还没测试过连接。"

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    def _on_provider(self, _event: object = None) -> None:
        label = self.provider.get().strip()
        for item in PROVIDERS:
            if item["label"] == label:
                self.base_url.set(item["base_url"])
                if not self.model.get().strip() or self.model.get().strip() in {
                    other["model"] for other in PROVIDERS
                }:
                    self.model.set(item["model"])
                self.values["label"] = label
                self.status.set(item.get("hint", ""))
                break

    def collect(self) -> dict[str, Any]:
        thinking = next(
            (
                value
                for label, value in THINKING_CHOICES
                if label == self.thinking_choice.get()
            ),
            "auto",
        )
        return {
            "enabled": self.enabled.get(),
            "label": self.provider.get().strip(),
            "base_url": self.base_url.get(),
            "model": self.model.get(),
            "api_key": self.api_key.get(),
            "request_timeout_sec": self.timeout.get(),
            "max_context_tokens": self.context_tokens.get(),
            "plan_max_tokens": self.plan_tokens.get(),
            # 窗口里没有这两项的控件：原样带回，别让一次保存把它们抹掉。
            "plan_temperature": self.values.get("plan_temperature"),
            "vision_when_requested": self.values.get("vision_when_requested"),
            "thinking_level": thinking,
            "use_world_knowledge": self.world_knowledge.get(),
        }

    def test_connection(self) -> None:
        values, errors = normalize_settings(self.collect())
        if errors:
            self.status.set("；".join(errors))
            return
        if not values["base_url"] or not values["model"]:
            self.status.set("先填 API 地址和模型名。")
            return
        self.test_button.configure(state="disabled")
        self.status.set("正在测试连接…")

        def worker() -> None:
            ok, detail = qwen.probe_api(
                base_url=values["base_url"],
                api_key=values["api_key"],
                model=values["model"],
                timeout=values["request_timeout_sec"],
            )

            def finish() -> None:
                self.test_button.configure(state="normal")
                self.status.set(detail)
                self.verified = bool(ok)
                if ok:
                    self.enabled.set(True)

            try:
                self.window.after(0, finish)
            except Exception:   # noqa: BLE001 - 窗口已关就什么都不做
                pass

        threading.Thread(target=worker, daemon=True).start()

    def save(self) -> None:
        values, errors = normalize_settings(self.collect())
        if errors:
            self._messagebox.showwarning("API 配置", "；".join(errors), parent=self.window)
            return
        try:
            save_settings(values, self.config_path, verified=self.verified)
        except (ValueError, OSError) as error:
            self._messagebox.showerror("API 配置", f"保存失败：{error}", parent=self.window)
            return
        if self.on_saved is not None:
            try:
                self.on_saved(values)
            except Exception:   # noqa: BLE001 - 回调只是刷新界面，失败不该影响保存
                pass
        self.close()

    def close(self) -> None:
        try:
            self.window.destroy()
        except Exception:   # noqa: BLE001
            pass


def run_standalone(config_path: str | Path | None = None) -> int:
    """独立打开「API 配置」窗口（Praat 菜单那一路用）。返回进程退出码。"""

    import tkinter as tk

    from . import parent_watch

    dialog = ApiSettingsDialog(None, config_path=config_path)
    # Praat 关了就跟着退，别把这个小窗留在桌面上（同对话窗口）。
    if parent_watch.should_watch():
        parent_watch.ParentWatcher(dialog.window, grace_sec=2.0).start()
    dialog.window.mainloop()
    try:
        dialog.window.destroy()
    except Exception:   # noqa: BLE001
        pass
    del tk
    return 0
