"""找到本机上正在跑的那个 Praat。

为什么要单独一个模块（2026-09-20，参考 PraatPlugin 的
``PraatInstallationLocator``）：以前 :func:`praat_ai.chat.praat_executable` 只认
环境变量 ``PRAAT_AI_PRAAT_EXECUTABLE``，否则写死仓库根目录的 ``Praat.exe``。
用户把 Praat 装在别处、或者从别的位置启动同一个 fork，前端就直接报
「没有检测到正在运行的 Praat」，而他其实正开着 Praat。

这里按「越可能是用户手上那个」的顺序找：

1. 显式指定（环境变量）；
2. 本仓库根目录的 ``Praat.exe``（这个 fork 自己构建出来的那个，正常就是它）；
3. ``PATH``（``shutil.which``，不额外起子进程）；
4. 常见安装位置（Program Files、Program Files (x86)、
   ``%LOCALAPPDATA%/Programs/Praat``、桌面、家目录）；
5. macOS / Linux 的常规位置（对话窗口的投递只能在 Windows 上用，但找得到路径
   至少能让报错信息说清是哪个平台不支持）。

缓存策略和参考库一致：找到就缓存；没找到也缓存，但 ``NOT_FOUND_RETRY_SEC``
秒后重试一次——用户中途把 Praat 装好，不用重启对话窗口。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


#: 显式指定 Praat 可执行文件的环境变量。
EXECUTABLE_ENV = "PRAAT_AI_PRAAT_EXECUTABLE"

#: 找不到时多久重试一次。
NOT_FOUND_RETRY_SEC = 30.0

_cached: Path | None = None
_cache_valid = False
_last_search = 0.0


def project_root() -> Path:
    """这个 fork 的仓库根目录（``ai/praat_ai/praat_app.py`` 往上三层）。"""

    return Path(__file__).resolve().parents[2]


def _windows_candidates() -> list[Path]:
    candidates: list[Path] = []
    for variable, relative in (
        ("ProgramFiles", "Praat/Praat.exe"),
        ("ProgramFiles(x86)", "Praat/Praat.exe"),
        ("LOCALAPPDATA", "Programs/Praat/Praat.exe"),
        ("LOCALAPPDATA", "Praat/Praat.exe"),
    ):
        base = os.getenv(variable, "").strip()
        if base:
            candidates.append(Path(base) / relative)
    home = os.getenv("USERPROFILE", "").strip()
    if home:
        candidates.append(Path(home) / "Desktop" / "Praat.exe")
        candidates.append(Path(home) / "Praat.exe")
    return candidates


def _other_platform_candidates() -> list[Path]:
    home = Path.home()
    return [
        Path("/Applications/Praat.app/Contents/MacOS/Praat"),
        home / "Applications/Praat.app/Contents/MacOS/Praat",
        Path("/usr/bin/praat"),
        Path("/usr/local/bin/praat"),
    ]


def candidate_paths() -> list[Path]:
    """按优先级列出要试的路径（不做存在性检查，方便单测和报错信息）。"""

    candidates: list[Path] = [project_root() / "Praat.exe"]
    if os.name == "nt":
        candidates.extend(_windows_candidates())
    else:
        candidates.extend(_other_platform_candidates())
    return candidates


def _on_path() -> Path | None:
    for name in ("Praat.exe", "praat"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def describe_search() -> str:
    """给用户看的一句话：找到在哪、或者都找过哪里。"""

    executable = find_praat()
    if executable:
        return f"Praat：{executable}"
    tried = "、".join(str(path) for path in candidate_paths()[:6])
    return (
        "没有找到 Praat.exe。试过：" + tried
        + "。也可以设 PRAAT_AI_PRAAT_EXECUTABLE 指定完整路径。"
    )


def reset_cache() -> None:
    """清掉缓存（单测用；也给「用户刚装了 Praat」的兜底留个手动入口）。"""

    global _cached, _cache_valid, _last_search
    _cached = None
    _cache_valid = False
    _last_search = 0.0


def find_praat(explicit: str = "") -> str:
    """返回 Praat 可执行文件的完整路径；找不到返回空字符串。"""

    global _cached, _cache_valid, _last_search

    configured = (explicit or os.getenv(EXECUTABLE_ENV, "")).strip()
    if configured:
        path = Path(configured)
        return str(path) if path.is_file() else ""

    now = time.monotonic()
    if _cache_valid:
        if _cached is not None or now - _last_search < NOT_FOUND_RETRY_SEC:
            return str(_cached) if _cached is not None else ""

    _last_search = now
    _cache_valid = True
    for candidate in candidate_paths():
        if candidate.is_file():
            _cached = candidate
            return str(candidate)
    on_path = _on_path()
    _cached = on_path
    return str(on_path) if on_path is not None else ""
