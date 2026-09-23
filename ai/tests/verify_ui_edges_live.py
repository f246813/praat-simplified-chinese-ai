"""Real Tk raster check for deformed rounded-control borders on Windows.

Run from the repository root with PYTHONPATH=ai. The window is visible briefly
and then closes; it never reads the user's AI configuration or starts Praat.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import ui_theme, ui_widgets  # noqa: E402
from progress_window_utils import capture_png  # noqa: E402


def check_outline(scale: float, *, dark: bool) -> None:
    root = tk.Tk()
    try:
        root.title("Praat UI Edge Probe")
        root.geometry("240x100+80+80")
        root.attributes("-topmost", True)
        theme = ui_theme.Theme(root, dark=dark, scale=scale)
        root.configure(background=theme.color("canvas"))
        button = ui_widgets.RoundedButton(
            root, theme, "API 配置…", kind="outlined", width=94, height=32
        )
        button.pack(pady=20)
        root.update()
        button._redraw()
        root.update()
        width, height = button.winfo_width(), button.winfo_height()
        screenshot = (
            Path(__file__).resolve().parents[1]
            / "runtime"
            / f"ui_border_{'dark' if dark else 'light'}_{scale:g}.png"
        )
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        handle = user32.FindWindowW(None, "Praat UI Edge Probe")
        assert handle
        assert capture_png(handle, screenshot)
        bounds = wintypes.RECT()
        assert user32.GetWindowRect(handle, ctypes.byref(bounds))
        image = Image.open(screenshot).convert("RGB").crop((
            button.winfo_rootx() - bounds.left,
            button.winfo_rooty() - bounds.top,
            button.winfo_rootx() - bounds.left + width,
            button.winfo_rooty() - bounds.top + height,
        ))
        image.save(screenshot)
        outline_color = button._palette(theme)[2]
        assert outline_color is not None
        border = tuple(
            int(outline_color[position : position + 2], 16)
            for position in (1, 3, 5)
        )
        middle = max(
            row for row in range(height) if image.getpixel((width // 2, row)) == border
        )
        radius = theme.radius(6)
        near_corners = [
            (column, row)
            for row in range(max(0, height - radius - 4), height)
            for column in list(range(2, radius + 5))
            + list(range(width - radius - 5, width - 2))
            if image.getpixel((column, row)) == border
        ]
        deepest_corner = max(row for _, row in near_corners)
        straight_right = max(
            column
            for column in range(width)
            if image.getpixel((column, height // 2)) == border
        )
        rightmost_corner = max(
            column
            for row in range(1, min(height // 2, radius + 5))
            for column in range(width - radius - 5, width)
            if image.getpixel((column, row)) == border
        )
        print(
            f"theme={'dark' if dark else 'light'} scale={scale:g} size={width}x{height} "
            f"straight_bottom={middle} deepest_corner={deepest_corner} "
            f"straight_right={straight_right} rightmost_corner={rightmost_corner}"
        )
        assert deepest_corner <= middle, (
            f"rounded border protrudes {deepest_corner - middle} pixel(s) below "
            "its straight bottom edge"
        )
        assert rightmost_corner <= straight_right, (
            f"rounded border protrudes {rightmost_corner - straight_right} pixel(s) past "
            "its straight right edge"
        )
    finally:
        root.destroy()


if __name__ == "__main__":
    for is_dark in (False, True):
        for factor in (1.0, 1.25, 1.5):
            check_outline(factor, dark=is_dark)
