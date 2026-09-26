"""Live Win32 geometry check for dynamic action-area submenu buttons.

Run from the repository root with the project's Windows Python environment.
This starts and closes its own Praat instance and does not modify user data.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

if os.name != "nt":
    raise SystemExit("SKIP: this live geometry check requires Windows")

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "ai"))
sys.path.insert(0, str(PROJECT / "ai" / "tests"))

from praat_ai import sendpraat  # noqa: E402
from progress_window_utils import capture_png  # noqa: E402


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.COLORREF
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.SendMessageW.restype = wintypes.LPARAM
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD


def _control_text(hwnd: int) -> tuple[str, str]:
    class_name = ctypes.create_unicode_buffer(256)
    title = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(hwnd, class_name, len(class_name))
    user32.GetWindowTextW(hwnd, title, len(title))
    return class_name.value, title.value


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    bounds = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(bounds)):
        raise ctypes.WinError()
    return bounds.left, bounds.top, bounds.right, bounds.bottom


def _cascade_label_ink_center(hwnd: int) -> tuple[float, float]:
    """Return the visible label's ink center and the symmetric label-zone center."""
    client = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise ctypes.WinError()
    width, height = client.right, client.bottom

    # Match the intended rails: 3px button inset + 27px left rail and
    # 19px arrow + 8px gap on the right.  Both label-zone edges are 30px in.
    label_left = 3 + 4 + 16 + 7
    label_right = width - 3 - 19 - 8
    if label_right <= label_left:
        raise AssertionError(f"Cascade label zone is too narrow: {width}px button")

    dc = user32.GetDC(hwnd)
    if not dc:
        raise ctypes.WinError()
    ink_x: list[int] = []
    try:
        for y in range(2, max(2, height - 2)):
            for x in range(label_left, label_right):
                pixel = int(gdi32.GetPixel(dc, x, y))
                if pixel == 0xFFFFFFFF:  # CLR_INVALID
                    continue
                red = pixel & 0xFF
                green = (pixel >> 8) & 0xFF
                blue = (pixel >> 16) & 0xFF
                if red < 120 and green < 130 and blue < 145:
                    ink_x.append(x)
    finally:
        user32.ReleaseDC(hwnd, dc)

    if not ink_x:
        raise AssertionError("Could not find cascade-title ink between the reserved rails")
    ink_center = (min(ink_x) + max(ink_x)) / 2
    label_center = (label_left + label_right - 1) / 2
    return ink_center, label_center


def _terminate_process(process_id: int) -> None:
    handle = kernel32.OpenProcess(0x0001, False, process_id)  # PROCESS_TERMINATE
    stopped = False
    if handle:
        try:
            if kernel32.TerminateProcess(handle, 0):
                stopped = kernel32.WaitForSingleObject(handle, 5000) == 0
        finally:
            kernel32.CloseHandle(handle)
    if not stopped:
        subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            check=False,
            capture_output=True,
        )


def _process_image_path(process_id: int) -> Path:
    handle = kernel32.OpenProcess(0x1000, False, process_id)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise ctypes.WinError()
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            raise ctypes.WinError()
        return Path(buffer.value).resolve()
    finally:
        kernel32.CloseHandle(handle)


def _objects_window(process_id: int, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for window in sendpraat.list_windows():
            if (
                window.process_id == process_id
                and window.title == sendpraat.PRAAT_OBJECTS_TITLE
                and window.visible
            ):
                return window
        time.sleep(0.2)
    return None


def _dynamic_menu_buttons(parent_hwnd: int) -> list[tuple[str, tuple[int, ...], tuple[int, ...]]]:
    found: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []

    def visit(hwnd, _lparam) -> bool:
        class_name, title = _control_text(hwnd)
        if class_name.casefold() == "button":
            container = user32.GetParent(hwnd)
            parent_class, parent_title = _control_text(container)
            if parent_class.casefold().startswith("praatchildwindow") and parent_title == "rowColumn":
                found.append((title, _rect(container), _rect(hwnd)))
        return True

    callback = WNDENUMPROC(visit)
    user32.EnumChildWindows(parent_hwnd, callback, 0)
    return found


def _dynamic_menu_button_handle(
    parent_hwnd: int, bounds: tuple[int, ...]
) -> int | None:
    found: list[int] = []

    def visit(hwnd, _lparam) -> bool:
        class_name, _title = _control_text(hwnd)
        if class_name.casefold() != "button" or _rect(hwnd) != bounds:
            return True
        container = user32.GetParent(hwnd)
        parent_class, parent_title = _control_text(container)
        if parent_class.casefold().startswith("praatchildwindow") and parent_title == "rowColumn":
            found.append(hwnd)
        return True

    callback = WNDENUMPROC(visit)
    user32.EnumChildWindows(parent_hwnd, callback, 0)
    return found[0] if found else None


def _action_row_rectangles(
    parent_hwnd: int, menu_rows: list[tuple[int, ...]]
) -> list[tuple[int, ...]]:
    left, _top, right, _bottom = menu_rows[0]
    rows = set(menu_rows)

    def visit(hwnd, _lparam) -> bool:
        class_name, _title = _control_text(hwnd)
        if class_name.casefold() != "button":
            return True
        container = user32.GetParent(hwnd)
        parent_class, parent_title = _control_text(container)
        if (
            parent_class.casefold().startswith("praatchildwindow")
            and parent_title in {"form", "menu"}
        ):
            bounds = _rect(hwnd)
            if bounds[0] == left and bounds[2] == right:
                rows.add(bounds)
        return True

    callback = WNDENUMPROC(visit)
    user32.EnumChildWindows(parent_hwnd, callback, 0)
    return sorted(rows, key=lambda bounds: bounds[1])


def _visible_scrollbars(
    parent_hwnd: int,
) -> list[tuple[int, str, str, tuple[int, ...]]]:
    found: list[tuple[int, str, str, tuple[int, ...]]] = []

    def visit(hwnd, _lparam) -> bool:
        class_name, title = _control_text(hwnd)
        if class_name.casefold() == "scrollbar" and user32.IsWindowVisible(hwnd):
            found.append((hwnd, class_name, title, _rect(hwnd)))
        return True

    callback = WNDENUMPROC(visit)
    user32.EnumChildWindows(parent_hwnd, callback, 0)
    return found


def _fixed_form_buttons(parent_hwnd: int) -> list[tuple[str, tuple[int, ...]]]:
    found: list[tuple[str, tuple[int, ...]]] = []

    def visit(hwnd, _lparam) -> bool:
        class_name, title = _control_text(hwnd)
        if class_name.casefold() == "button":
            parent = user32.GetParent(hwnd)
            parent_class, parent_title = _control_text(parent)
            if (
                parent_class.casefold().startswith("praatchildwindow")
                and parent_title == "form"
            ):
                found.append((title, _rect(hwnd)))
        return True

    callback = WNDENUMPROC(visit)
    user32.EnumChildWindows(parent_hwnd, callback, 0)
    return found


def _action_clip_window(scroll_window: int) -> tuple[int, ...] | None:
    found: list[tuple[int, ...]] = []

    def visit(hwnd, _lparam) -> bool:
        class_name, title = _control_text(hwnd)
        if (
            class_name.casefold().startswith("praatchildwindow")
            and title == "bulletinBoard"
            and user32.GetParent(hwnd) == scroll_window
        ):
            found.append(_rect(hwnd))
        return True

    callback = WNDENUMPROC(visit)
    user32.EnumChildWindows(scroll_window, callback, 0)
    return found[0] if found else None


def main() -> int:
    executable = Path(
        os.environ.get("PRAAT_EXECUTABLE_PATH", PROJECT / "Praat.exe")
    ).resolve()
    if not executable.is_file():
        raise SystemExit(f"Praat executable not found: {executable}")

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".praat", delete=False,
        dir=PROJECT / "ai" / "runtime",
    ) as script:
        script.write(
            'Create Sound from formula: "layout-probe", 1, 0, 0.5, 44100, '
            '~ 0.3 * sin (2*pi*220*x)\n'
        )
        script_path = Path(script.name)

    process = subprocess.Popen(
        [str(executable), "--FULL-TRUST", "--new-send", str(script_path)],
        cwd=PROJECT,
    )
    app_process_id = process.pid
    try:
        objects = _objects_window(process.pid)
        if objects is None:
            raise AssertionError("Praat Objects window did not appear")
        app_process_id = objects.process_id
        actual_executable = _process_image_path(objects.process_id)
        if os.path.normcase(str(actual_executable)) != os.path.normcase(str(executable)):
            raise AssertionError(
                f"Praat window came from {actual_executable}, expected {executable}"
            )
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        window_dpi = user32.GetDpiForWindow(objects.handle) or 96
        expected_height = round(28 * window_dpi / 96)
        print(
            f"EXE: {actual_executable}; SHA-256: {executable_hash}; "
            f"window DPI: {window_dpi} ({window_dpi / 96:.0%})"
        )
        deadline = time.monotonic() + 15
        buttons = []
        signature = None
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            current = _dynamic_menu_buttons(objects.handle)
            current_signature = tuple(current)
            if current_signature != signature:
                buttons = current
                signature = current_signature
                stable_since = time.monotonic()
            elif buttons and time.monotonic() - stable_since >= 1.5:
                break
            time.sleep(0.2)
        if not buttons:
            raise AssertionError("No dynamic submenu buttons found under rowColumn controls")

        menu_rows = []
        for title, container, button in buttons:
            print(f"{title!r}: row={container}, button={button}")
            menu_rows.append(container)
        action_rows = _action_row_rectangles(objects.handle, menu_rows)
        ordinary_heights = {
            bounds[3] - bounds[1]
            for bounds in action_rows
            if bounds not in menu_rows
        }
        ordinary_widths = {
            bounds[2] - bounds[0]
            for bounds in action_rows
            if bounds not in menu_rows
        }
        if len(ordinary_heights) != 1:
            raise AssertionError(
                f"Could not establish one ordinary action-row height: {ordinary_heights}"
            )
        ordinary_height = ordinary_heights.pop()
        dynamic_row_heights = {row[3] - row[1] for row in menu_rows}
        dynamic_button_heights = {
            button[3] - button[1] for _title, _row, button in buttons
        }
        dynamic_row_widths = {row[2] - row[0] for row in menu_rows}
        dynamic_button_widths = {
            button[2] - button[0] for _title, _row, button in buttons
        }
        print(
            f"Measured heights: ordinary={ordinary_height}px, "
            f"dynamic rows={sorted(dynamic_row_heights)}, "
            f"cascade buttons={sorted(dynamic_button_heights)}; "
            f"expected={expected_height}px"
        )
        print(
            f"Measured widths: ordinary={sorted(ordinary_widths)}, "
            f"dynamic rows={sorted(dynamic_row_widths)}, "
            f"cascade buttons={sorted(dynamic_button_widths)}"
        )
        if ordinary_height != expected_height:
            raise AssertionError(
                f"At {window_dpi / 96:.0%} window DPI, action rows must be "
                f"{expected_height}px from the independent 28px baseline; "
                f"ordinary rows measured {ordinary_height}px"
            )
        if dynamic_row_heights != {expected_height}:
            raise AssertionError(
                f"Dynamic row containers must be {expected_height}px at this DPI: "
                f"{menu_rows}"
            )
        if dynamic_button_heights != {expected_height}:
            raise AssertionError(
                f"Dynamic submenu buttons must be {expected_height}px at this DPI: "
                f"{sorted(dynamic_button_heights)}"
            )
        off_center_labels = []
        for title, _container, button in buttons:
            button_hwnd = _dynamic_menu_button_handle(objects.handle, button)
            if button_hwnd is None:
                raise AssertionError(f"Could not find HWND for cascade button {title!r}")
            ink_center, label_center = _cascade_label_ink_center(button_hwnd)
            if abs(ink_center - label_center) > 3:
                off_center_labels.append((title, ink_center, label_center))
        if off_center_labels:
            raise AssertionError(
                "Cascade titles must be centered between the fixed icon and arrow rails: "
                f"{off_center_labels}"
            )
        print(f"PASS: {len(buttons)} cascade titles are centered between the fixed rails")
        if (
            len(ordinary_widths) != 1
            or dynamic_row_widths != ordinary_widths
            or dynamic_button_widths != ordinary_widths
        ):
            raise AssertionError(
                "Ordinary actions, dynamic row containers, and submenu buttons "
                "must share one width: "
                f"ordinary={sorted(ordinary_widths)}, "
                f"rows={sorted(dynamic_row_widths)}, "
                f"buttons={sorted(dynamic_button_widths)}"
            )
        mismatches = [
            (title, container, button)
            for title, container, button in buttons
            if button != container
        ]
        if mismatches:
            raise AssertionError(
                "Dynamic submenu buttons must fill their rows; mismatched bounds: "
                f"{mismatches}"
            )
        for current, following in zip(action_rows, action_rows[1:]):
            gap = following[1] - current[3]
            if gap != 5:
                raise AssertionError(
                    f"Action rows must keep 5px spacing; found {gap}px between "
                    f"{current} and {following}"
                )
        padded_titles = [
            title
            for title, _container, _button in buttons
            if title != title.strip() or title.endswith(">")
        ]
        if padded_titles:
            raise AssertionError(
                "Dynamic submenu HWND titles must be plain titles without alignment "
                f"spaces or embedded disclosure markers: {padded_titles}"
            )
        snapshot = PROJECT / "ai" / "runtime" / "dynamic_action_area.png"
        snapshot_captured = capture_png(objects.handle, snapshot)
        if not snapshot_captured:
            print("Screenshot omitted because Pillow is unavailable")

        # Exercise both sides of the automatic-scrollbar threshold.  A tall window
        # must reclaim the 16px bar width; shrinking it again must restore scrolling.
        original_window = _rect(objects.handle)
        overflow_size = (450, 250)
        if not user32.SetWindowPos(
            objects.handle,
            None,
            original_window[0],
            original_window[1],
            *overflow_size,
            0x0004 | 0x0010,  # SWP_NOZORDER | SWP_NOACTIVATE
        ):
            raise ctypes.WinError()
        overflow_deadline = time.monotonic() + 5
        overflow_buttons = []
        overflow_scrollbars = []
        while time.monotonic() < overflow_deadline:
            overflow_buttons = _dynamic_menu_buttons(objects.handle)
            overflow_scrollbars = _visible_scrollbars(objects.handle)
            if len(overflow_buttons) == len(buttons) and any(
                title.casefold() == "verticalscrollbar"
                for _hwnd, _class_name, title, _bounds in overflow_scrollbars
            ):
                break
            time.sleep(0.1)
        if len(overflow_buttons) != len(buttons):
            raise AssertionError("Could not stabilize the action list in a short window")
        if not any(
            title.casefold() == "verticalscrollbar"
            for _hwnd, _class_name, title, _bounds in overflow_scrollbars
        ):
            raise AssertionError("Overflowing action content must show a vertical scrollbar")
        overflow_rows = _action_row_rectangles(
            objects.handle, [row for _title, row, _button in overflow_buttons]
        )
        overflow_widths = {row[2] - row[0] for row in overflow_rows}
        if len(overflow_widths) != 1:
            raise AssertionError(f"Overflow action rows do not share one width: {overflow_widths}")
        overflow_width = overflow_widths.pop()
        vertical_scrollbar = next(
            hwnd
            for hwnd, _class_name, title, _bounds in overflow_scrollbars
            if title.casefold() == "verticalscrollbar"
        )
        scroll_window = user32.GetParent(vertical_scrollbar)
        overflow_clip = _action_clip_window(scroll_window)
        if overflow_clip is None:
            raise AssertionError("Could not locate the overflowing action viewport")

        thumb_at_bottom = (32767 << 16) | 4  # WM_VSCROLL / SB_THUMBPOSITION
        user32.SendMessageW(
            scroll_window, 0x0115, thumb_at_bottom, vertical_scrollbar
        )
        scroll_deadline = time.monotonic() + 5
        scrolled_buttons = []
        while time.monotonic() < scroll_deadline:
            scrolled_buttons = _dynamic_menu_buttons(objects.handle)
            if scrolled_buttons and scrolled_buttons[0][1] != overflow_buttons[0][1]:
                break
            time.sleep(0.1)
        if not scrolled_buttons or scrolled_buttons[0][1] == overflow_buttons[0][1]:
            raise AssertionError("Could not move the overflowing action list before hiding its bar")

        if not user32.SetWindowPos(
            objects.handle,
            None,
            original_window[0],
            original_window[1],
            450,
            1200,
            0x0004 | 0x0010,  # SWP_NOZORDER | SWP_NOACTIVATE
        ):
            raise ctypes.WinError()
        fit_deadline = time.monotonic() + 5
        fit_buttons = []
        fit_scrollbars = []
        while time.monotonic() < fit_deadline:
            fit_buttons = _dynamic_menu_buttons(objects.handle)
            fit_scrollbars = _visible_scrollbars(objects.handle)
            if len(fit_buttons) == len(buttons) and not any(
                title.casefold() == "verticalscrollbar"
                for _hwnd, _class_name, title, _bounds in fit_scrollbars
            ):
                break
            time.sleep(0.1)
        if any(
            title.casefold() == "verticalscrollbar"
            for _hwnd, _class_name, title, _bounds in fit_scrollbars
        ):
            raise AssertionError(
                "Automatic vertical scrollbar must be hidden when all action content fits"
            )
        if len(fit_buttons) != len(buttons):
            raise AssertionError("Action buttons did not stabilize in a tall window")
        fit_clip = _action_clip_window(scroll_window)
        if fit_clip is None:
            raise AssertionError("Could not locate the fitting action viewport")
        fit_rows = _action_row_rectangles(
            objects.handle, [row for _title, row, _button in fit_buttons]
        )
        if [row[1] for row in fit_rows] != [row[1] for row in action_rows]:
            raise AssertionError(
                "Hiding an automatic scrollbar after scrolling must reset the work window to its origin"
            )
        fit_widths = {row[2] - row[0] for row in fit_rows}
        if len(fit_widths) != 1:
            raise AssertionError(f"Fitting action rows do not share one width: {fit_widths}")
        fit_width = fit_widths.pop()
        if fit_width < overflow_width + 12:
            raise AssertionError(
                "Hiding the automatic scrollbar must return its reserved width to action rows: "
                f"overflow={overflow_width}px, fit={fit_width}px"
            )
        if (fit_clip[2] - fit_clip[0]) < (overflow_clip[2] - overflow_clip[0]) + 12:
            raise AssertionError(
                "Hiding the automatic scrollbar must expand the clipped viewport: "
                f"overflow={overflow_clip}, fit={fit_clip}"
            )
        print(
            f"PASS: automatic scrollbar hides and returns width when content fits "
            f"({overflow_width}px -> {fit_width}px)"
        )

        if not user32.SetWindowPos(
            objects.handle,
            None,
            original_window[0],
            original_window[1],
            original_window[2] - original_window[0],
            original_window[3] - original_window[1],
            0x0004 | 0x0010,  # SWP_NOZORDER | SWP_NOACTIVATE
        ):
            raise ctypes.WinError()
        time.sleep(0.5)

        old_window = _rect(objects.handle)
        old_size = old_window[2] - old_window[0], old_window[3] - old_window[1]
        resized = user32.SetWindowPos(
            objects.handle,
            None,
            old_window[0],
            old_window[1],
            old_size[0] + 100,
            old_size[1] + 80,
            0x0004 | 0x0010,   # SWP_NOZORDER | SWP_NOACTIVATE
        )
        if not resized:
            raise ctypes.WinError()
        new_window = _rect(objects.handle)
        if (new_window[2] - new_window[0], new_window[3] - new_window[1]) == old_size:
            raise AssertionError("Praat Objects window did not resize")
        resize_deadline = time.monotonic() + 5
        previous_signature = None
        stable_samples = 0
        resized_buttons = []
        while time.monotonic() < resize_deadline:
            current_buttons = _dynamic_menu_buttons(objects.handle)
            current_signature = tuple(current_buttons)
            if current_buttons and current_signature == previous_signature:
                stable_samples += 1
                if stable_samples >= 2:
                    resized_buttons = current_buttons
                    break
            else:
                stable_samples = 0
            previous_signature = current_signature
            time.sleep(0.2)
        if len(resized_buttons) != len(buttons):
            raise AssertionError(
                f"Resize changed the number of dynamic menus: {len(buttons)} → "
                f"{len(resized_buttons)}"
            )
        resized_mismatches = [
            (title, row, button)
            for title, row, button in resized_buttons
            if row != button
        ]
        if resized_mismatches:
            raise AssertionError(
                f"Resized dynamic submenu bounds diverged: {resized_mismatches}"
            )
        resized_menu_rows = [row for _title, row, _button in resized_buttons]
        resized_action_rows = _action_row_rectangles(objects.handle, resized_menu_rows)
        if any(
            bounds[3] - bounds[1] != expected_height
            for bounds in resized_menu_rows
        ):
            raise AssertionError(
                f"Resized dynamic rows no longer match {expected_height}px: "
                f"{resized_menu_rows}"
            )
        for current, following in zip(resized_action_rows, resized_action_rows[1:]):
            gap = following[1] - current[3]
            if gap != 5:
                raise AssertionError(
                    f"Resize changed the action-row gap to {gap}px between "
                    f"{current} and {following}"
                )

        small_window = user32.SetWindowPos(
            objects.handle,
            None,
            new_window[0],
            new_window[1],
            450,
            250,
            0x0004 | 0x0010,   # SWP_NOZORDER | SWP_NOACTIVATE
        )
        if not small_window:
            raise ctypes.WinError()
        small_deadline = time.monotonic() + 5
        small_buttons = []
        while time.monotonic() < small_deadline:
            small_buttons = _dynamic_menu_buttons(objects.handle)
            if len(small_buttons) == len(buttons) and all(
                button[3] - button[1] == expected_height
                for _title, _row, button in small_buttons
            ):
                break
            time.sleep(0.2)
        if len(small_buttons) != len(buttons):
            raise AssertionError(
                f"Small window changed the number of dynamic menus: {len(small_buttons)}"
            )
        if any(
            button[3] - button[1] != expected_height
            for _title, _row, button in small_buttons
        ):
            raise AssertionError(
                f"Small window scaled action buttons away from {expected_height}px: "
                f"{small_buttons}"
            )
        scrollbars = _visible_scrollbars(objects.handle)
        vertical_scrollbars = [
            (hwnd, bounds)
            for hwnd, _class_name, title, bounds in scrollbars
            if title.casefold() == "verticalscrollbar"
        ]
        print(f"Visible scrollbars at minimum window size: {scrollbars}")
        if not vertical_scrollbars:
            raise AssertionError(
                "The minimum-height Objects window must expose a vertical scroll bar for "
                "the dynamic action area"
            )
        if any(
            title.casefold() == "horizontalscrollbar"
            for _hwnd, _class_name, title, _bounds in scrollbars
        ):
            raise AssertionError(
                "The action area must not reserve or display a horizontal scroll bar"
            )
        vertical_scrollbar = vertical_scrollbars[0][0]
        scroll_window = user32.GetParent(vertical_scrollbar)
        clip = _action_clip_window(scroll_window)
        if clip is None:
            raise AssertionError("Could not locate the dynamic action viewport")
        window_bottom = _rect(objects.handle)[3]
        fixed_button_band = round(140 * window_dpi / 96)
        fixed_buttons = [
            (title, bounds)
            for title, bounds in _fixed_form_buttons(objects.handle)
            if bounds[1] >= window_bottom - fixed_button_band
        ]
        if not fixed_buttons:
            raise AssertionError("Could not locate the fixed bottom command buttons")
        fixed_button_top = min(bounds[1] for _title, bounds in fixed_buttons)
        if clip[3] > fixed_button_top:
            raise AssertionError(
                "The action viewport must stop above the fixed bottom buttons: "
                f"viewport={clip}, first fixed-button top={fixed_button_top}"
            )
        small_menu_rows = [row for _title, row, _button in small_buttons]
        small_action_rows = _action_row_rectangles(objects.handle, small_menu_rows)
        small_menu_row_set = set(small_menu_rows)
        small_ordinary_rows = [
            row for row in small_action_rows if row not in small_menu_row_set
        ]
        if not small_ordinary_rows:
            raise AssertionError("Could not locate ordinary actions in the scroll area")
        last_before = max(small_ordinary_rows, key=lambda row: row[3])
        if last_before[3] <= clip[3]:
            raise AssertionError(
                "The minimum-height action list did not extend beyond its viewport: "
                f"last row={last_before}, viewport={clip}"
            )

        thumb_at_bottom = (32767 << 16) | 4  # WM_VSCROLL / SB_THUMBPOSITION
        user32.SendMessageW(scroll_window, 0x0115, thumb_at_bottom, vertical_scrollbar)
        bottom_deadline = time.monotonic() + 5
        last_after = last_before
        while time.monotonic() < bottom_deadline:
            scrolled_buttons = _dynamic_menu_buttons(objects.handle)
            if scrolled_buttons:
                scrolled_menu_rows = [
                    row for _title, row, _button in scrolled_buttons
                ]
                scrolled_action_rows = _action_row_rectangles(
                    objects.handle, scrolled_menu_rows
                )
                scrolled_menu_row_set = set(scrolled_menu_rows)
                scrolled_ordinary_rows = [
                    row
                    for row in scrolled_action_rows
                    if row not in scrolled_menu_row_set
                ]
                if scrolled_ordinary_rows:
                    last_after = max(scrolled_ordinary_rows, key=lambda row: row[3])
                if last_after[1] >= clip[1] and last_after[3] <= clip[3]:
                    break
            time.sleep(0.1)
        if last_after[1] < clip[1] or last_after[3] > clip[3]:
            raise AssertionError(
                "Scrolling to the bottom must bring the final ordinary action into the viewport: "
                f"last row={last_after}, viewport={clip}"
            )

        print(f"PASS: {len(buttons)} submenu buttons fill their row containers")
        print(
            f"PASS: dynamic and ordinary action rows are {expected_height}px high "
            "with 5px spacing"
        )
        if snapshot_captured:
            print(f"Screenshot: {snapshot}")
        print("PASS: action-row geometry remains consistent after resize")
        print("PASS: minimum-height window keeps normal button size and scrolls to the final action")
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        _terminate_process(app_process_id)
        script_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
