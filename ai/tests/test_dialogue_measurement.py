"""Known duration requests still use real templates and app-state validation."""
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from praat_ai import cloud_workflow
from praat_ai.config import AppConfig, apply_api_to_qwen
from praat_ai.conversation_store import ConversationStore

CONTEXT='id\tclass\tname\tselected\n1\tSound\tfixture\t1\n'


class DurationWorkflowTests(unittest.TestCase):
    def test_duration_uses_verified_template_without_model_or_audio_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); store=ConversationStore(root/'records.sqlite3')
            cfg=AppConfig(); cfg.api.enabled=True; cfg.api.thinking_level='high'; apply_api_to_qwen(cfg)
            window=SimpleNamespace(config=cfg,pending_analysis=None,history=[],task_materials=[],current_materials=None,
                analysis_state=None,store=store,session_id=store.new_session(),cancel_event=threading.Event(),
                messages=queue.Queue(),_closed=False)
            with (patch('praat_ai.chat.object_context',return_value=CONTEXT),
                  patch('praat_ai.chat.runtime_dir',return_value=root),
                  patch('praat_ai.chat.praat_executable',return_value='fixture.exe'),
                  patch('praat_ai.chat.praat_process_ids',return_value=[123]),
                  patch('praat_ai.chat.refresh_object_context',return_value=(True,'')),
                  patch('praat_ai.chat._send_script',return_value=(True,'')) as send,
                  patch('praat_ai.chat._read_failure',return_value=''),
                  patch('praat_ai.chat._read_results',return_value=['时长 = 1.250000 s']),
                  patch('praat_ai.cloud_agent.run_cloud_turn',side_effect=AssertionError('No model call needed')),
                  patch('praat_ai.cloud_workflow.TaskMaterials',side_effect=AssertionError('No material needed'))):
                try: cloud_workflow.process_cloud(window,'测量当前声音的时长')
                except AssertionError as error: self.fail(str(error))
            self.assertEqual(send.call_count,1)
            self.assertIn('Get total duration',send.call_args.args[1])
            state=window.analysis_state
            self.assertEqual(state.requests,0)
            self.assertEqual(state.status,'complete')
            self.assertIn('1.250000',state.report)
            self.assertEqual(state.evidence[0].tool,'duration')
            self.assertEqual(window.task_materials,[])


if __name__=='__main__': unittest.main()
