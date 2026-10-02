"""Exercise chat key handling across the native IME boundary, without a model."""
import unittest
from unittest.mock import patch

from praat_ai import chat, ui_windows


class Field:
    def __init__(self):
        self.text = '已有文字'

    def winfo_id(self):
        return 0x123456789

    def insert(self, index, value):
        self.text += value


class NativeContext:
    def __init__(self, length, context=0x23456789A):
        self.length = length
        self.context = context
        self.releases = []

    def ImmGetContext(self, hwnd):
        return self.context

    def ImmGetCompositionStringW(self, context, kind, buffer, length):
        if kind != 8 or buffer is not None or length != 0:
            raise AssertionError('Expected native GCS_COMPSTR byte-length query')
        return self.length

    def ImmReleaseContext(self, hwnd, context):
        self.releases.append((hwnd, context))


class CompositionKeysTests(unittest.TestCase):
    def make_window(self):
        window = chat.ChatWindow.__new__(chat.ChatWindow)
        window.entry = Field()
        submitted = []
        window.submit = lambda: submitted.append(window.entry.text)
        return window, submitted

    def test_preedit_return_neither_sends_nor_inserts_a_newline(self):
        for preedit in ('nihao', 'にほんご', '한글'):
            with self.subTest(preedit=preedit):
                api = NativeContext(len(preedit.encode('utf-16-le')))
                window, submitted = self.make_window()
                with patch.object(ui_windows, '_imm32', return_value=api):
                    self.assertEqual(window.on_return(None), 'break')
                    self.assertEqual(window.on_shift_return(None), 'break')
                self.assertEqual(submitted, [])
                self.assertEqual(window.entry.text, '已有文字')
                self.assertEqual(len(api.releases), 2)

    def test_finished_composition_allows_normal_send_and_shift_newline(self):
        for length in (0, -1, -2):  # Empty preedit, IMM_ERROR_NODATA, IMM_ERROR_GENERAL.
            with self.subTest(length=length):
                api = NativeContext(length)
                window, submitted = self.make_window()
                with patch.object(ui_windows, '_imm32', return_value=api):
                    self.assertEqual(window.on_return(None), 'break')
                    self.assertEqual(window.on_shift_return(None), 'break')
                self.assertEqual(submitted, ['已有文字'])
                self.assertEqual(window.entry.text, '已有文字\n')

    def test_missing_context_or_non_windows_does_not_block_normal_typing(self):
        for api in (None, NativeContext(10, context=0)):
            window, submitted = self.make_window()
            with patch.object(ui_windows, '_imm32', return_value=api):
                window.on_return(None)
            self.assertEqual(submitted, ['已有文字'])


if __name__ == '__main__':
    unittest.main()
