"""Real Tk raster check for deformed rounded-control borders on Windows.

Run from the repository root with PYTHONPATH=ai. The window is visible briefly
and then closes; it never reads the user's AI configuration or starts Praat.
"""

from __future__ import annotations

import ctypes
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from ctypes import wintypes
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import ui_theme, ui_widgets  # noqa: E402
from progress_window_utils import capture_png  # noqa: E402


def _is_border_color(pixel, color: tuple[int, int, int]) -> bool:
    return sum(abs(actual - expected) for actual, expected in zip(pixel, color)) <= 60


def _hex_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _edge_run(strip, color: tuple[int, int, int]) -> int:
    start = next(
        (index for index, pixel in enumerate(strip) if _is_border_color(pixel, color)),
        None,
    )
    assert start is not None, f"edge color {color} missing from scanline"
    end = start
    while end < len(strip) and _is_border_color(strip[end], color):
        end += 1
    return end - start


def _measure_edges(image, color: tuple[int, int, int]) -> dict[str, int]:
    width, height = image.size
    center_x, center_y = width // 2, height // 2
    return {
        "top": _edge_run([image.getpixel((center_x, y)) for y in range(height)], color),
        "bottom": _edge_run(
            [image.getpixel((center_x, y)) for y in range(height - 1, -1, -1)], color
        ),
        "left": _edge_run([image.getpixel((x, center_y)) for x in range(width)], color),
        "right": _edge_run(
            [image.getpixel((x, center_y)) for x in range(width - 1, -1, -1)], color
        ),
    }


def _capture_widget(root, widget, title: str) -> Image.Image:
    root.update()
    filename = Path(tempfile.gettempdir()) / f"{title}.png"
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    handle = user32.FindWindowW(None, root.title())
    assert handle
    assert capture_png(handle, filename)
    bounds = wintypes.RECT()
    assert user32.GetWindowRect(handle, ctypes.byref(bounds))
    return Image.open(filename).convert("RGB").crop((
        widget.winfo_rootx() - bounds.left,
        widget.winfo_rooty() - bounds.top,
        widget.winfo_rootx() - bounds.left + widget.winfo_width(),
        widget.winfo_rooty() - bounds.top + widget.winfo_height(),
    ))


def _assert_corner_quality(
    image: Image.Image,
    radius: int,
    known_colors: set[tuple[int, int, int]],
    label: str,
) -> None:
    width, height = image.size
    side = min(max(3, radius), width // 2, height // 2)
    has_antialias_pixel = False
    for y in range(side):
        for x in range(side):
            pixel = image.getpixel((x, y))
            mirrors = (
                image.getpixel((width - 1 - x, y)),
                image.getpixel((x, height - 1 - y)),
                image.getpixel((width - 1 - x, height - 1 - y)),
            )
            assert all(
                max(abs(a - b) for a, b in zip(pixel, mirror)) <= 3
                for mirror in mirrors
            ), f"{label} corners are asymmetric at ({x}, {y})"
            has_antialias_pixel |= pixel not in known_colors
    assert has_antialias_pixel, f"{label} corner has no antialiased pixels"


def _assert_edge_widths(
    image: Image.Image,
    color: tuple[int, int, int],
    expected_width: int,
    label: str,
) -> dict[str, int]:
    edge_widths = _measure_edges(image, color)
    assert set(edge_widths.values()) == {expected_width}, (
        f"{label} edge widths are asymmetric: {edge_widths}; "
        f"expected {expected_width}px"
    )
    return edge_widths


def check_outline(scale: float, *, dark: bool) -> None:
    root = tk.Tk()
    try:
        root.title("Praat UI Edge Probe")
        root.geometry("240x100+80+80")
        root.attributes("-topmost", True)
        theme = ui_theme.Theme(root, dark=dark, scale=scale)
        root.configure(background=theme.color("canvas"))
        clicks = []
        button = ui_widgets.RoundedButton(
            root,
            theme,
            "API 配置…",
            command=lambda: clicks.append("clicked"),
            kind="outlined",
            width=94,
            height=32,
        )
        button.pack(padx=20, pady=20, fill="x")
        root.update()
        button._redraw()
        root.update()
        width, height = button.winfo_width(), button.winfo_height()
        prefix = f"praat_button_{'dark' if dark else 'light'}_{scale:g}"
        image = _capture_widget(root, button, f"{prefix}_initial")
        outline_color = button._palette(theme)[2]
        assert outline_color is not None
        border = _hex_rgb(outline_color)
        expected_width = max(1, theme.pad(1))
        edge_widths = _assert_edge_widths(
            image, border, expected_width, f"outlined button initial ({scale:g}x)"
        )
        middle = max(
            row for row in range(height) if _is_border_color(image.getpixel((width // 2, row)), border)
        )
        radius = theme.radius(6)
        near_corners = [
            (column, row)
            for row in range(max(0, height - radius - 4), height)
            for column in list(range(2, radius + 5))
            + list(range(width - radius - 5, width - 2))
            if _is_border_color(image.getpixel((column, row)), border)
        ]
        deepest_corner = max(row for _, row in near_corners)
        straight_right = max(
            column
            for column in range(width)
            if _is_border_color(image.getpixel((column, height // 2)), border)
        )
        rightmost_corner = max(
            column
            for row in range(1, min(height // 2, radius + 5))
            for column in range(width - radius - 5, width)
            if _is_border_color(image.getpixel((column, row)), border)
        )
        _assert_corner_quality(
            image,
            radius,
            {_hex_rgb(theme.color(token)) for token in ("canvas", "surface", "primary", "primarySoft")},
            f"outlined button initial ({scale:g}x)",
        )
        print(
            f"theme={'dark' if dark else 'light'} scale={scale:g} size={width}x{height} "
            f"edge_widths={edge_widths} straight_bottom={middle} deepest_corner={deepest_corner} "
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

        def check_state(name: str) -> None:
            state_image = _capture_widget(root, button, f"{prefix}_{name}")
            state_outline = button._palette(theme)[2]
            assert state_outline is not None
            state_color = _hex_rgb(state_outline)
            widths = _assert_edge_widths(
                state_image,
                state_color,
                expected_width,
                f"outlined button {name} ({scale:g}x)",
            )
            _assert_corner_quality(
                state_image,
                radius,
                {
                    _hex_rgb(theme.color(token))
                    for token in (
                        "canvas",
                        "surface",
                        "primary",
                        "primaryHover",
                        "primarySoft",
                        "surfaceAlt",
                    )
                },
                f"outlined button {name} ({scale:g}x)",
            )
            print(
                f"button theme={'dark' if dark else 'light'} scale={scale:g} "
                f"state={name} edge_widths={widths} corners=symmetric antialias=present"
            )

        button.event_generate("<Enter>")
        root.update()
        check_state("hover")
        button.event_generate(
            "<ButtonPress-1>", x=button.winfo_width() // 2, y=button.winfo_height() // 2
        )
        root.update()
        check_state("pressed-focused")
        button.event_generate(
            "<ButtonRelease-1>", x=button.winfo_width() // 2, y=button.winfo_height() // 2
        )
        root.update()
        assert clicks == ["clicked"], f"mouse click did not activate the button: {clicks}"
        check_state("released-focused")
        button.event_generate("<FocusOut>")
        root.update()
        check_state("blurred")
        button.event_generate("<Leave>")
        root.update()
        check_state("idle")

        before_resize = button.winfo_width()
        root.geometry("360x160+80+80")
        root.update()
        assert button.winfo_width() > before_resize, "test button did not resize with its window"
        check_state("resized")
    finally:
        root.destroy()


def check_field_entry_edges(scale: float, *, dark: bool) -> None:
    root = tk.Tk()
    try:
        theme_name = "dark" if dark else "light"
        prefix = f"praat_field_{theme_name}_{scale:g}"
        root.title("Praat Field Edge Probe")
        root.geometry("320x120+80+80")
        root.attributes("-topmost", True)
        theme = ui_theme.Theme(root, dark=dark, scale=scale)
        root.configure(background=theme.color("canvas"))
        style = ttk.Style(root)
        if "clam" in style.theme_names() and style.theme_use() != "clam":
            style.theme_use("clam")
        ui_widgets.configure_ttk(style, theme)

        shell = ui_widgets.FieldCard(root, theme, width=260, height=42, radius=8)
        shell.pack(fill="x", padx=24, pady=24)
        entry = ttk.Entry(shell)
        shell.attach(entry)
        root.update()
        shell._redraw()
        root.update()
        expected_width = max(1, theme.pad(1))

        def check_state(name: str, border_token: str) -> None:
            shell_image = _capture_widget(root, shell, f"{prefix}_{name}")
            border = _hex_rgb(theme.color(border_token))
            edge_widths = _assert_edge_widths(
                shell_image,
                border,
                expected_width,
                f"FieldCard {name} ({scale:g}x)",
            )
            _assert_corner_quality(
                shell_image,
                theme.radius(8),
                {
                    _hex_rgb(theme.color(token))
                    for token in ("canvas", "surface", "border", "primary")
                },
                f"FieldCard {name} ({scale:g}x)",
            )
            entry_box = (
                entry.winfo_rootx() - shell.winfo_rootx(),
                entry.winfo_rooty() - shell.winfo_rooty(),
                entry.winfo_rootx() - shell.winfo_rootx() + entry.winfo_width(),
                entry.winfo_rooty() - shell.winfo_rooty() + entry.winfo_height(),
            )
            entry_image = shell_image.crop(entry_box)
            surface = _hex_rgb(theme.color("surface"))
            entry_width, entry_height = entry_image.size
            corners = {
                "top_left": (0, 0),
                "top_right": (entry_width - 1, 0),
                "bottom_left": (0, entry_height - 1),
                "bottom_right": (entry_width - 1, entry_height - 1),
            }
            residue = {
                corner: entry_image.getpixel(point)
                for corner, point in corners.items()
                if entry_image.getpixel(point) != surface
            }
            assert not residue, f"ttk.Entry corner residue in {name}: {residue}"
            print(
                f"field theme={theme_name} scale={scale:g} state={name} "
                f"size={shell_image.width}x{shell_image.height} "
                f"edge_widths={edge_widths} corners=symmetric entry_corners=clean"
            )

        before_resize = shell.winfo_width()
        check_state("initial", "border")
        entry.event_generate("<FocusIn>")
        root.update()
        check_state("focused", "primary")
        entry.event_generate("<FocusOut>")
        root.update()
        check_state("blurred", "border")
        root.geometry("400x160+80+80")
        root.update()
        assert shell.winfo_width() > before_resize, "test field did not resize with its window"
        check_state("resized", "border")
    finally:
        root.destroy()


def check_reopened(scale: float, *, dark: bool) -> None:
    root = tk.Tk()
    try:
        theme_name = "dark" if dark else "light"
        root.title("Praat Reopened Edge Probe")
        root.geometry("360x160+80+80")
        root.attributes("-topmost", True)
        theme = ui_theme.Theme(root, dark=dark, scale=scale)
        root.configure(background=theme.color("canvas"))
        style = ttk.Style(root)
        if "clam" in style.theme_names() and style.theme_use() != "clam":
            style.theme_use("clam")
        ui_widgets.configure_ttk(style, theme)
        button = ui_widgets.RoundedButton(
            root, theme, "重新打开", kind="outlined", width=94, height=32
        )
        button.pack(fill="x", padx=20, pady=12)
        shell = ui_widgets.FieldCard(root, theme, width=260, height=42, radius=8)
        shell.pack(fill="x", padx=24, pady=12)
        entry = ttk.Entry(shell)
        shell.attach(entry)
        root.update()

        expected_width = max(1, theme.pad(1))
        button_image = _capture_widget(root, button, f"praat_reopen_button_{theme_name}_{scale:g}")
        button_border = _hex_rgb(theme.color("primary"))
        _assert_edge_widths(button_image, button_border, expected_width, "reopened button")
        _assert_corner_quality(
            button_image,
            theme.radius(6),
            {_hex_rgb(theme.color(token)) for token in ("canvas", "surface", "primary")},
            "reopened button",
        )

        field_image = _capture_widget(root, shell, f"praat_reopen_field_{theme_name}_{scale:g}")
        field_border = _hex_rgb(theme.color("border"))
        _assert_edge_widths(field_image, field_border, expected_width, "reopened FieldCard")
        _assert_corner_quality(
            field_image,
            theme.radius(8),
            {_hex_rgb(theme.color(token)) for token in ("canvas", "surface", "border")},
            "reopened FieldCard",
        )
        entry_box = (
            entry.winfo_rootx() - shell.winfo_rootx(),
            entry.winfo_rooty() - shell.winfo_rooty(),
            entry.winfo_rootx() - shell.winfo_rootx() + entry.winfo_width(),
            entry.winfo_rooty() - shell.winfo_rooty() + entry.winfo_height(),
        )
        entry_image = field_image.crop(entry_box)
        surface = _hex_rgb(theme.color("surface"))
        assert all(
            entry_image.getpixel(point) == surface
            for point in (
                (0, 0),
                (entry_image.width - 1, 0),
                (0, entry_image.height - 1),
                (entry_image.width - 1, entry_image.height - 1),
            )
        ), "ttk.Entry corner residue after reopening"
        print(
            f"reopened theme={theme_name} scale={scale:g} "
            "button=uniform field=uniform corners=symmetric"
        )
    finally:
        root.destroy()


if __name__ == "__main__":
    for is_dark in (False, True):
        for factor in (1.0, 1.25, 1.5, 2.0):
            check_outline(factor, dark=is_dark)
            check_field_entry_edges(factor, dark=is_dark)
            check_reopened(factor, dark=is_dark)
