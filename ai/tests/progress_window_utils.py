"""给真机回归用的小工具：找 Praat 的进度窗口、截图、数量进度条填充。

背景（2026-09-21 用户报的）：窗口弹出来时**里面没有进度条**，随后进度条闪一下就
跟着窗口消失。修好之后要有人守着「第一帧里就有进度条」这件事，所以这里把
「找窗口 + PrintWindow 截图 + 数绿色填充像素」抽出来，给
`verify_model_progress_live.py` 用。

截图走 PrintWindow：不要求窗口在最前面、也不受遮挡影响。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from praat_ai import sendpraat


PROGRESS_TITLES = ("正在处理中", "Work in progress")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_progress_window(process_id: int = 0) -> sendpraat.WindowInfo | None:
    """**可见的**进度窗口；给了 ``process_id`` 就只看那个 Praat 进程的。

    Praat 的进度窗口用完是「隐藏」而不是销毁，所以必须只看可见的那些。
    """

    for window in sendpraat.list_windows():
        if process_id and window.process_id != process_id:
            continue
        if not window.visible:
            continue
        if window.title.strip() in PROGRESS_TITLES:
            return window
    return None


def child_texts(handle: int) -> list[str]:
    """窗口里的子控件文字（标签、按钮）。"""

    texts: list[str] = []

    @WNDENUMPROC
    def visit(child, _param):   # type: ignore[no-untyped-def]
        length = user32.GetWindowTextLengthW(child)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(child, buffer, length + 1)
        if buffer.value.strip():
            texts.append(buffer.value.strip()[:60])
        return True

    user32.EnumChildWindows(handle, visit, 0)
    return texts


def capture_png(handle: int, path: Path) -> bool:
    """把窗口画进位图存成 PNG（需要 Pillow；没装就返回 False）。"""

    try:
        from PIL import Image
    except ImportError:
        return False

    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        return False
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False

    window_dc = user32.GetDC(handle)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    user32.PrintWindow(handle, memory_dc, 0)
    gdi32.SelectObject(memory_dc, previous)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height   # 自上而下
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    copied = gdi32.GetDIBits(
        memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
    )
    ok = False
    if copied:
        image = Image.frombuffer(
            "RGBA", (width, height), buffer, "raw", "BGRA", 0, 1
        ).convert("RGB")
        image.save(path)
        ok = True
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(handle, window_dc)
    return ok


def bar_metrics(png: Path) -> tuple[int, int, int]:
    """量一张进度窗口截图里的进度条：``(填充像素数, 轨道像素数, 窗口宽度)``。

    填充是绿色（Win32 进度条默认那个绿），轨道是浅灰。取窗口下半部分里
    「绿+灰」最多的那一行来数——也就是进度条所在的那一行。
    """

    from PIL import Image

    image = Image.open(png).convert("RGB")
    width, height = image.size
    best = (0, 0)
    for y in range(height // 2, height * 3 // 4):
        row = [image.getpixel((x, y)) for x in range(width)]
        green = sum(1 for r, g, b in row if g > 120 and r < 140 and b < 140)
        track = sum(
            1 for r, g, b in row if abs(r - g) < 12 and abs(g - b) < 12 and 200 <= r <= 240
        )
        if green + track > best[0] + best[1]:
            best = (green, track)
    return best[0], best[1], width
