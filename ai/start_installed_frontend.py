"""安装版对象菜单入口：按已保存的本地/API 配置启动服务和对话窗口。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox


def main() -> int:
    from praat_ai.config import api_is_active, load_config
    from praat_ai.control import start_frontend
    from praat_ai.progress_popup import MiniProgress
    from praat_ai.ui_windows import create_root
    from start_ai_chat import main as start_chat

    config = load_config()
    # With no local files configured, the chat still offers the API settings UI.
    if not api_is_active(config) and not (
        config.server.llama_server and config.server.model_path
    ):
        return start_chat()
    root = create_root()
    root.withdraw()
    popup = MiniProgress(root, title="AIPraat", message="正在准备 AI 前端…")
    updates: list[tuple[float, str]] = []
    result: list[Exception | None] = []
    lock = threading.Lock()

    def progress(fraction: float, message: str) -> None:
        with lock:
            updates.append((fraction, message))

    def worker() -> None:
        try:
            start_frontend(progress=progress)
            result.append(None)
        except Exception as error:
            result.append(error)

    threading.Thread(target=worker, daemon=True).start()

    def poll() -> None:
        with lock:
            pending = list(updates)
            updates.clear()
        for fraction, message in pending:
            popup.update(fraction, message)
        if not result:
            root.after(50, poll)
            return
        popup.close()
        if result[0] is not None:
            messagebox.showerror("AIPraat 前端启动失败", str(result[0]), parent=root)
        root.quit()

    root.after(50, poll)
    root.mainloop()
    root.destroy()
    return 1 if result[0] is not None else start_chat()


if __name__ == "__main__":
    raise SystemExit(main())
