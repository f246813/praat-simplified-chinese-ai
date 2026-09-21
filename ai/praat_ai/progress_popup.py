"""「简约小窗口 + 进度条」：加载/停止模型时给用户看的那个小窗。

两种入口用两套 UI，但数据是同一条进度流（0–1 的进度 + 一句中文说明）：

- Praat 菜单里点「启动前端 / 加载模型」→ 控制脚本把进度打到标准输出
  （``PRAAT_PROGRESS\\t<进度>\\t<说明>``）→ Praat 自己的进度小窗
  （`sys/praat_python.cpp` → `Melder_progress`）；
- 对话窗口里点「应用预设 / API 配置」→ 本模块的 :class:`MiniProgress`，
  一个只有一句话 + 一根进度条的小窗，不抢焦点、不能改大小、关闭时不留残影。
"""

from __future__ import annotations

import time

#: 小窗最少显示多久：一次「应用预设」有时几百毫秒就完了，不兜一下用户只看到一闪。
MINIMUM_VISIBLE_SEC = 0.8


class MiniProgress:
    """挂在对话窗口上的迷你进度窗（简约：一句话 + 一根进度条 + 自动消失）。"""

    def __init__(self, root, *, title: str = "Praat AI", message: str = "正在加载模型…"):
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self.root = root
        self.shown_at = time.monotonic()
        self.window = tk.Toplevel(root)
        self.window.title(title)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)   # 简约：不给中途关闭
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass

        frame = ttk.Frame(self.window, padding=(16, 14, 16, 14))
        frame.pack(fill="both", expand=True)
        self.message = tk.StringVar(value=message)
        ttk.Label(
            frame,
            textvariable=self.message,
            width=34,
            anchor="w",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")
        self.bar = ttk.Progressbar(
            frame, mode="determinate", maximum=100.0, length=280
        )
        self.bar.pack(fill="x", pady=(8, 0))
        # 一开始就画出进度条（0%），别让用户先看到一个空窗口。
        self.bar.configure(value=0.0)
        self._place_near_parent()
        try:
            self.window.update_idletasks()
        except Exception:   # noqa: BLE001
            pass

    def _place_near_parent(self) -> None:
        """显示在对话窗口中间偏上一点（不遮住输入框）。"""

        try:
            self.window.update_idletasks()
            parent = self.root.winfo_rootx(), self.root.winfo_rooty()
            size = self.root.winfo_width(), self.root.winfo_height()
            width = self.window.winfo_width()
            height = self.window.winfo_height()
            x = parent[0] + max(0, (size[0] - width) // 2)
            y = parent[1] + max(0, (size[1] - height) // 3)
            self.window.geometry(f"+{x}+{y}")
        except Exception:   # noqa: BLE001 - 位置算不出来就用系统默认位置
            pass

    def update(self, fraction: float, message: str | None = None) -> None:
        """更新进度条（0–1）和文案。"""

        try:
            self.bar.configure(value=max(0.0, min(1.0, float(fraction))) * 100.0)
            if message:
                self.message.set(message)
            self.window.update_idletasks()
        except Exception:   # noqa: BLE001 - 窗口已经被关掉时忽略
            pass

    def close(self) -> None:
        try:
            self.window.destroy()
        except Exception:   # noqa: BLE001
            pass

    def remaining_minimum_seconds(self) -> float:
        """还要等多久才允许关闭（不够 MINIMUM_VISIBLE_SEC 就返回剩下的秒数）。"""

        elapsed = time.monotonic() - self.shown_at
        return max(0.0, MINIMUM_VISIBLE_SEC - elapsed)
