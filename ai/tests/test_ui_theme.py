"""界面主题：令牌完整性、系统深浅色探测、缩放、对比度、监听器生命周期。

这套令牌是 TW-Elements（Tailwind + MDB，MIT）的设计语言，见 guide.md §8.16。
"""

import sys
import types
import unittest
from unittest.mock import patch

from praat_ai import ui_theme


class TokenTests(unittest.TestCase):
    def test_both_palettes_have_the_same_keys(self) -> None:
        self.assertEqual(set(ui_theme.LIGHT), set(ui_theme.DARK))
        self.assertEqual(set(ui_theme.LIGHT), set(ui_theme.TOKEN_NAMES))

    def test_every_token_is_a_hex_colour(self) -> None:
        for name, value in {**ui_theme.LIGHT, **ui_theme.DARK}.items():
            with self.subTest(token=name):
                self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$")

    def test_text_is_readable_on_every_surface(self) -> None:
        """正文 vs 各层底色至少要过 WCAG AA（4.5:1）——深色下也要看得清。"""

        pairs = [
            ("text", "canvas"),
            ("text", "surface"),
            ("text", "surfaceAlt"),
            ("text", "codeBg"),
            ("text", "dangerSoft"),
            ("textMuted", "surface"),
            ("onPrimary", "primary"),
            ("codeText", "codeBg"),
        ]
        for palette in (ui_theme.LIGHT, ui_theme.DARK):
            for foreground, background in pairs:
                with self.subTest(mode=palette["canvas"], pair=(foreground, background)):
                    ratio = ui_theme.contrast_ratio(
                        palette[foreground], palette[background]
                    )
                    self.assertGreaterEqual(round(ratio, 1), 4.5)

    def test_accent_headers_pass_the_large_text_threshold(self) -> None:
        """强调行是加粗小标题（WCAG 的"大字号"档），底线是 3:1。"""

        pairs = [
            ("primary", "primarySoft"),
            ("primary", "surface"),
            ("successText", "shadowRing"),
            ("successText", "successSoft"),
            ("warningText", "chipBg"),
            ("danger", "dangerSoft"),
        ]
        for palette in (ui_theme.LIGHT, ui_theme.DARK):
            for foreground, background in pairs:
                with self.subTest(mode=palette["canvas"], pair=(foreground, background)):
                    ratio = ui_theme.contrast_ratio(
                        palette[foreground], palette[background]
                    )
                    self.assertGreaterEqual(round(ratio, 1), 3.0)

    def test_contrast_ratio_matches_wcag_examples(self) -> None:
        self.assertAlmostEqual(ui_theme.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(ui_theme.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=2)
        with self.assertRaises(ValueError):
            ui_theme.contrast_ratio("not-a-colour", "#FFFFFF")


class SystemThemeTests(unittest.TestCase):
    """``AppsUseLightTheme``：0 = 深色；缺失/读失败/没有 winreg 一律按浅色。"""

    def fake_winreg(self, value=None, *, raise_on_open=False, raise_on_query=False):
        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def open_key(*_args, **_kwargs):
            if raise_on_open:
                raise OSError("no key")
            return _Key()

        def query_value(_key, _name):
            if raise_on_query:
                raise FileNotFoundError("no value")
            return value, 4

        return types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            OpenKey=open_key,
            QueryValueEx=query_value,
        )

    def test_light_system(self) -> None:
        with patch.dict(sys.modules, {"winreg": self.fake_winreg(1)}):
            self.assertFalse(ui_theme.system_is_dark())

    def test_dark_system(self) -> None:
        with patch.dict(sys.modules, {"winreg": self.fake_winreg(0)}):
            self.assertTrue(ui_theme.system_is_dark())

    def test_missing_value_falls_back_to_light(self) -> None:
        with patch.dict(sys.modules, {"winreg": self.fake_winreg(raise_on_query=True)}):
            self.assertFalse(ui_theme.system_is_dark())

    def test_broken_registry_falls_back_to_light(self) -> None:
        with patch.dict(sys.modules, {"winreg": self.fake_winreg(raise_on_open=True)}):
            self.assertFalse(ui_theme.system_is_dark())

    def test_garbage_value_falls_back_to_light(self) -> None:
        with patch.dict(sys.modules, {"winreg": self.fake_winreg("昨天")}):
            self.assertFalse(ui_theme.system_is_dark())

    def test_without_winreg_module_it_is_light(self) -> None:
        with patch.dict(sys.modules, {"winreg": None}):
            self.assertFalse(ui_theme.system_is_dark())


class ScaleTests(unittest.TestCase):
    class _Window:
        def __init__(self, per_inch: float) -> None:
            self.per_inch = per_inch

        def winfo_fpixels(self, _value: str) -> float:
            if self.per_inch < 0:
                raise RuntimeError("no display")
            return self.per_inch

    def test_one_hundred_percent(self) -> None:
        self.assertAlmostEqual(ui_theme.scale_factor(self._Window(96)), 1.0)

    def test_one_hundred_and_twentyfive_percent(self) -> None:
        self.assertAlmostEqual(ui_theme.scale_factor(self._Window(120)), 1.25)

    def test_one_hundred_and_fifty_percent(self) -> None:
        self.assertAlmostEqual(ui_theme.scale_factor(self._Window(144)), 1.5)

    def test_silly_values_are_clamped(self) -> None:
        self.assertEqual(ui_theme.scale_factor(self._Window(0)), 1.0)
        self.assertEqual(ui_theme.scale_factor(self._Window(-1)), 1.0)
        self.assertEqual(ui_theme.scale_factor(self._Window(960)), 2.0)


class ThemeTests(unittest.TestCase):
    def make(self, *, dark: bool = False, scale: float = 1.0) -> ui_theme.Theme:
        return ui_theme.Theme(None, dark=dark, scale=scale)

    def test_colours_and_metrics(self) -> None:
        theme = self.make(scale=1.5)
        self.assertEqual(theme.color("primary"), ui_theme.LIGHT["primary"])
        self.assertEqual(theme.pad(8), 12)
        self.assertEqual(theme.radius(10), 15)

    def test_unknown_token_is_reported(self) -> None:
        with self.assertRaises(KeyError):
            self.make().color("不存在的令牌")

    def test_dark_mode_switches_the_palette(self) -> None:
        theme = self.make()
        theme.set_dark(True)
        self.assertEqual(theme.color("canvas"), ui_theme.DARK["canvas"])
        self.assertFalse(theme.set_dark(True))   # 没变就不重复通知

    def test_listeners_fire_on_switch_and_survive_failures(self) -> None:
        theme = self.make()
        seen: list[str] = []
        theme.add_listener(lambda item: seen.append(item.color("canvas")))
        self.assertEqual(seen, [ui_theme.LIGHT["canvas"]])   # 注册时立刻上一次色
        theme.set_dark(True)
        self.assertEqual(seen[-1], ui_theme.DARK["canvas"])

        def broken(_theme):
            raise RuntimeError("控件已经销毁")

        theme.add_listener(broken)
        theme.refresh()   # 坏掉的监听器要被摘掉，不能把别的也带崩
        self.assertEqual(theme.listener_count(), 1)

    def test_remove_listener(self) -> None:
        theme = self.make()
        calls: list[int] = []

        def listener(_theme):
            calls.append(1)

        theme.add_listener(listener)
        theme.remove_listener(listener)
        theme.refresh()
        self.assertEqual(calls, [1])
        self.assertEqual(theme.listener_count(), 0)

    def test_fonts_fall_back_without_a_tk_root(self) -> None:
        font = self.make().font("body")
        self.assertIn(len(font), (2, 3))
        self.assertTrue(font[0])
        self.assertEqual(self.make().font("body_bold")[-1], "bold")
        self.assertTrue(self.make().font("data")[0])


class FakeTimerWindow:
    """假的 Tk 窗口：只记 ``after`` / ``after_cancel``。"""

    def __init__(self) -> None:
        self.scheduled: dict[str, object] = {}
        self.cancelled: list[str] = []
        self.next_id = 0

    def after(self, _milliseconds: int, callback):
        self.next_id += 1
        name = f"after#{self.next_id}"
        self.scheduled[name] = callback
        return name

    def after_cancel(self, name: str) -> None:
        self.cancelled.append(name)
        self.scheduled.pop(name, None)

    def run(self) -> None:
        for name, callback in list(self.scheduled.items()):
            self.scheduled.pop(name, None)
            callback()


class ThemeWatcherTests(unittest.TestCase):
    def test_it_reports_changes_and_keeps_polling(self) -> None:
        window = FakeTimerWindow()
        state = {"dark": False}
        seen: list[bool] = []
        watcher = ui_theme.ThemeWatcher(
            window, seen.append, interval_ms=1000, probe=lambda: state["dark"]
        )
        watcher.start()
        window.run()
        self.assertEqual(seen, [])   # 没变就不通知
        state["dark"] = True
        window.run()
        self.assertEqual(seen, [True])
        self.assertEqual(len(window.scheduled), 1)   # 继续盯着

    def test_stop_prevents_further_polling(self) -> None:
        window = FakeTimerWindow()
        watcher = ui_theme.ThemeWatcher(
            window, lambda _dark: None, interval_ms=1000, probe=lambda: True
        )
        watcher.start()
        watcher.stop()
        self.assertEqual(window.scheduled, {})
        self.assertIn("after#1", window.cancelled)
        watcher._tick()
        self.assertEqual(window.scheduled, {})   # 停掉之后不许再排

    def test_probe_failure_keeps_the_previous_value(self) -> None:
        window = FakeTimerWindow()
        calls = {"count": 0}

        def probe() -> bool:
            calls["count"] += 1
            if calls["count"] == 1:
                return False
            raise RuntimeError("注册表读不到")

        seen: list[bool] = []
        watcher = ui_theme.ThemeWatcher(window, seen.append, probe=probe)
        watcher.start()
        window.run()
        self.assertEqual(seen, [])
        self.assertFalse(watcher.current)


if __name__ == "__main__":
    unittest.main()
