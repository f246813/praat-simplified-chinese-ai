"""Tk/Windows DPI and IME integration shared by all frontend input fields.

Tk 8.6 positions the native IME window, but does not set its font.  Use the
field's actual font at Tk's pixel scale; never scale that font a second time.
Let Tk and the IME handle composition, candidate selection and committed text.
"""
from __future__ import annotations

import ctypes
import os
import tkinter as tk
from ctypes import wintypes
from functools import lru_cache
from tkinter import font as tkfont


class _LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
        ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE),
        ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
        ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
        ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32),
    ]


@lru_cache(maxsize=1)
def _imm32():
    if os.name != "nt":
        return None
    try:
        api = ctypes.WinDLL("imm32", use_last_error=True)
        api.ImmGetContext.argtypes = [wintypes.HWND]
        api.ImmGetContext.restype = wintypes.HANDLE
        api.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
        api.ImmReleaseContext.restype = wintypes.BOOL
        api.ImmSetCompositionFontW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_LOGFONTW)]
        api.ImmSetCompositionFontW.restype = wintypes.BOOL
        api.ImmGetCompositionStringW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]
        api.ImmGetCompositionStringW.restype = wintypes.LONG
        return api
    except (OSError, AttributeError):
        return None


def enable_high_dpi() -> None:
    """Choose system DPI before the first HWND (Tk 8.6 uses one screen scale).

    Preserve any DPI mode selected by the host/manifest. Per-monitor V2 needs
    layout/font rescaling on WM_DPICHANGED, which this Tk frontend doesn't do.
    """
    if os.name != "nt" or tk._default_root is not None:
        return
    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        user.GetAwarenessFromDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        if user.GetAwarenessFromDpiAwarenessContext(user.GetThreadDpiAwarenessContext()) > 0:
            return
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        if shcore.SetProcessDpiAwareness(1) == 0:
            return
    except (OSError, AttributeError):
        pass
    try:
        ctypes.WinDLL("user32").SetProcessDPIAware()
    except (OSError, AttributeError):
        pass


def sync_ime_font(widget) -> bool:
    """Synchronize the focused field's Unicode composition font, for every IME."""
    api = _imm32()
    if api is None:
        return False
    try:
        specification = widget.cget("font")
        font = tkfont.Font(root=widget, font=specification)
        actual = font.actual()
        size = int(font.cget("size"))
        # Font(font=...) copies `font actual`, which converts negative pixel
        # sizes to rounded points. Read the original specification instead.
        try:
            size = int(widget.tk.call("font", "configure", specification, "-size"))
        except tk.TclError:
            parts = widget.tk.splitlist(specification)
            if len(parts) > 1:
                try:
                    size = int(parts[1])
                except (ValueError, TypeError):
                    pass
        # Negative Tk sizes are already pixels; positive sizes are points.
        pixels = abs(size) if size < 0 else round(size * float(widget.tk.call("tk", "scaling")))
        logical = _LOGFONTW()
        logical.lfHeight = -max(1, pixels)
        logical.lfWeight = 700 if actual["weight"] == "bold" else 400
        logical.lfItalic = actual["slant"] == "italic"
        logical.lfUnderline = bool(actual["underline"])
        logical.lfStrikeOut = bool(actual["overstrike"])
        logical.lfFaceName = actual["family"][:31]
        logical.lfCharSet = 1  # DEFAULT_CHARSET: allow Chinese/Japanese/Korean fallback.
        logical.lfQuality = 5  # CLEARTYPE_QUALITY: avoid the default bitmap System font.
        hwnd = widget.winfo_id()
        context = api.ImmGetContext(hwnd)
        if not context:
            return False
        try:
            return bool(api.ImmSetCompositionFontW(context, ctypes.byref(logical)))
        finally:
            api.ImmReleaseContext(hwnd, context)
    except (tk.TclError, OSError, ValueError):
        return False


def is_composing(widget) -> bool:
    """Check native preedit text, not the selected keyboard language/open status."""
    api = _imm32()
    if api is None:
        return False
    try:
        hwnd = widget.winfo_id()
        context = api.ImmGetContext(hwnd)
        if not context:
            return False
        try:
            return api.ImmGetCompositionStringW(context, 0x0008, None, 0) > 0  # GCS_COMPSTR
        finally:
            api.ImmReleaseContext(hwnd, context)
    except (tk.TclError, OSError):
        return False


def create_root() -> tk.Tk:
    enable_high_dpi()
    root = tk.Tk()
    if _imm32() is not None:
        def sync(event):
            # Tk children can share an HIMC. A resize of an unfocused field
            # must not overwrite the font of the field currently being edited.
            if event.type == tk.EventType.Configure and event.widget.focus_get() is not event.widget:
                return
            sync_ime_font(event.widget)

        # Class bindings include fields in later Toplevels (API/tutor dialogs),
        # and keep Tk's existing bindings and native composition handling intact.
        for name in ("Text", "Entry", "TEntry", "TCombobox"):
            for event in ("<FocusIn>", "<KeyPress>", "<ButtonRelease-1>", "<Configure>"):
                previous = root.bind_class(name, event)
                root.bind_class(name, event, sync)
                # Classic Entry's FocusIn script can return `break`, so an
                # appended callback would never run. Preserve it after ours.
                current = root.bind_class(name, event)
                root.tk.call("bind", name, event, current + "\n" + previous)
    return root
