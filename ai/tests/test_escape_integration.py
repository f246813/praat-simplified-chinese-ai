import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from praat_ai import chat, tools
from praat_ai.config import AppConfig
from praat_ai.escape_policy import AnalysisState
from praat_ai.conversation_store import ConversationStore
from praat_ai.materials import TaskMaterials


class WindowIntegrationTests(unittest.TestCase):
    def test_cloud_discussion_bypasses_global_praat_check(self):
        window = chat.ChatWindow.__new__(chat.ChatWindow)
        window.config = AppConfig()
        window.config.api.enabled = True
        window.config.api.base_url, window.config.api.model = 'https://test.invalid/v1', 'fake'
        window.messages = queue.Queue()
        window.history = []
        window.cancel_event = threading.Event()
        with patch.object(window, 'process_cloud_message', create=True) as cloud, patch.object(chat, 'praat_process_ids', side_effect=AssertionError('must not check globally')):
            window.process_message('解释一下共振峰原理')
        cloud.assert_called_once_with('解释一下共振峰原理')

    def test_continue_uses_original_state_and_visible_prompt(self):
        window = chat.ChatWindow.__new__(chat.ChatWindow)
        window.busy = False
        window.config = AppConfig()
        window.config.api.enabled = True
        window.config.api.base_url, window.config.api.model = 'https://test.invalid/v1', 'fake'
        window.analysis_state = AnalysisState('原始目标', 'original selection')
        window.analysis_state.can_continue = True
        class Entry:
            def delete(self, *_): pass
            def insert(self, index, value): self.value = value
        window.entry = Entry()
        with patch.object(window, 'submit') as submit:
            window.continue_analysis('补充一般解释')
        submit.assert_called_once()
        self.assertIn('原始目标', window.entry.value)
        self.assertEqual(window.pending_analysis.context_text, 'original selection')

    def test_changed_selection_keeps_original_range(self):
        from praat_ai.cloud_workflow import bound_context
        old = 'id\tclass\tname\tselected\tselection_start\tselection_end\n1\tSound\ttone\t1\t0.2\t0.5\n'
        new = 'id\tclass\tname\tselected\tselection_start\tselection_end\n1\tSound\ttone\t1\t0.8\t0.9\n'
        context = tools.ToolContext(tools.parse_object_context(old), Path('result'), Path('state'))
        self.assertEqual(bound_context(context, new).objects[0].selection, (0.2,0.5))

    def test_explicit_target_and_range_override_current_selection(self):
        from praat_ai.cloud_workflow import target_context
        original = 'id\tclass\tname\tselected\tselection_start\tselection_end\n1\tSound\tfirst\t1\t0.1\t0.9\n2\tSound\tsecond\t0\t0.5\t0.8\n'
        bound = tools.parse_object_context(target_context('直接听 2 号对象 0.2–0.4 秒的原始音频',original))
        self.assertFalse(bound[0].selected)
        self.assertTrue(bound[1].selected)
        self.assertEqual(bound[1].selection,(0.2,0.4))
    def test_number_references_and_multi_target_measurement_binding(self):
        from praat_ai.cloud_workflow import target_context, explicit_range
        original = 'id\tclass\tname\tselected\n1\tSound\tfirst\t1\n2\tSound\tsecond\t0\n'
        for reference in ('编号 2', 'id 2', '#2'):
            rows = tools.parse_object_context(target_context('直接听' + reference + '的录音', original))
            self.assertEqual([row.id for row in rows if row.selected], [2])
        rows = tools.parse_object_context(target_context('比较对象 1 和对象 2 的基频', original))
        self.assertEqual([row.id for row in rows if row.selected], [1,2])
        self.assertEqual(explicit_range('文件 C:\\sample.wav 的 0.2–0.5 秒'), (0.2,0.5))


if __name__ == '__main__':
    unittest.main()
