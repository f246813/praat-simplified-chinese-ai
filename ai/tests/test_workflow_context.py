import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, qwen, tools

OLD = 'id\tclass\tname\tselected\tsel_start\tsel_end\n1\tSound\tSound あなた\t0\t0.1\t0.6\n2\tHarmonicity\tHarmonicity あなた\t1\t\t\n'
NEW = OLD.replace('あなた\t0\t0.1', 'あなた\t1\t0.1').replace('Harmonicity あなた\t1', 'Harmonicity あなた\t0')


def calls(*actions):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': f'c{i}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
        for i, (name, args) in enumerate(actions)]}


class Client:
    def __init__(self, messages, api=False):
        self.messages = list(messages)
        self.config = qwen.QwenConfig(provider='api' if api else 'local')
        if api:
            self.config.max_context_tokens = 32768
        self.seen = []
        self.contexts = []

    def chat_message(self, messages, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        return self.messages.pop(0)

    def chat(self, messages, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        return '分析完成'

    def plan_praat_command(self, user_text, context_text, history, **kwargs):
        self.seen.append(copy.deepcopy(history))
        self.contexts.append(context_text)
        return self.messages.pop(0)


def run(client, execute, **kwargs):
    ctx = tools.ToolContext(tools.parse_object_context(OLD), Path('result.tsv'), Path('state.txt'))
    return chat.run_turn(client, user_text=kwargs.pop('user_text', '分析语音'),
                         context_text=OLD, history=[], context=ctx, execute=execute, **kwargs)


class WorkflowTests(unittest.TestCase):
    def test_same_batch_uses_current_selection_and_next_round_sees_it(self):
        client = Client([calls(('select_object', {'object': 1}), ('object_info', {})),
                         {'role': 'assistant', 'content': '完成'}])
        scripts = []
        run(client, lambda s: (scripts.append(s) or True, ['ok'], ''),
            native=True, refresh_context=lambda: NEW)
        self.assertIn('selectObject: 1', scripts[1])
        self.assertIn('Sound あなた\t1', client.seen[1][0]['content'])

    def test_user_failure_chain_never_analyses_the_harmonicity(self):
        """复现 2026-09-29 用户报的故障链。

        现场：1 号是 Sound、2 号是 Harmonicity，Harmonicity 是当前选中。
        模型先 ``select_object: 1`` 选中声音，再连做基频/强度/共振峰统计。
        修好之前，每一步都还在用请求开始时的旧列表（选中对象仍是 Harmonicity），
        于是三个统计都会去 ``To Pitch`` / ``To Intensity`` / ``To Formant`` 一个
        Harmonicity，Praat 连续报错。

        现在：同一批次里的下一步必须已经看到「1 号被选中」，并且三个统计都落在
        ``selectObject: 1`` 上、都不出现 ``selectObject: 2``。
        """

        client = Client([
            calls(('select_object', {'object': 1}),
                  ('pitch_statistics', {}),
                  ('intensity_statistics', {})),
            calls(('formant_statistics', {})),
            {'role': 'assistant', 'content': '完成'},
        ])
        scripts = []
        outcome = run(client, lambda s: (scripts.append(s) or True, ['ok'], ''),
                      native=True, refresh_context=lambda: NEW)
        analyses = [s for s in scripts if s]
        self.assertEqual(len(analyses), 4)
        for script in analyses[1:]:
            with self.subTest(script=script.splitlines()[0]):
                self.assertEqual(script.splitlines()[0], 'selectObject: 1')
                self.assertNotIn('selectObject: 2', script)
        self.assertTrue(all(step.ok for step in outcome.steps))

    def test_default_selection_in_the_analysed_batch_uses_the_refreshed_state(self):
        """没有 explicitly 给 object 时，默认对象要按刷新后的选择走。"""

        client = Client([
            calls(('select_object', {'object': 1}), ('pitch_statistics', {})),
            {'role': 'assistant', 'content': '完成'},
        ])
        scripts = []
        run(client, lambda s: (scripts.append(s) or True, ['ok'], ''),
            native=True, refresh_context=lambda: NEW)
        self.assertEqual(scripts[1].splitlines()[0], 'selectObject: 1')

    def test_created_object_is_resolvable_in_next_round(self):
        client = Client([calls(('extract_part', {'object': 1, 'from': 0, 'to': 0.3})),
                         calls(('object_info', {'object': 3})), {'role': 'assistant', 'content': '完成'}])
        fresh = NEW + '3\tSound\tSound part\t1\t\t\n'
        outcome = run(client, lambda s: (True, ['ok'], ''), native=True, refresh_context=lambda: fresh)
        self.assertTrue(outcome.steps[1].ok)
        self.assertIn('selectObject: 3', outcome.steps[1].script)

    def test_refresh_failure_stops_remaining_actions_and_pairs_calls(self):
        client = Client([calls(('select_object', {'object': 1}), ('object_info', {}))])
        scripts = []
        def broken():
            raise OSError('context unavailable')
        outcome = run(client, lambda s: (scripts.append(s) or True, ['ok'], ''),
                      native=True, refresh_context=broken)
        self.assertEqual(len(scripts), 1)
        self.assertIn('对象', outcome.failure)
        self.assertEqual([m['tool_call_id'] for m in client.seen[-1] if m['role'] == 'tool'], ['c0', 'c1'])

    def test_step_budget_pairs_all_pending_calls(self):
        client = Client([calls(('object_info', {'object': 1}), ('object_info', {'object': 2}))])
        run(client, lambda s: (True, ['ok'], ''), native=True, max_steps=1)
        responses = [m for m in client.seen[-1] if m['role'] == 'tool']
        self.assertEqual([m['tool_call_id'] for m in responses], ['c0', 'c1'])
        self.assertIn('上限', responses[1]['content'])

    def test_repeated_failure_stays_failed(self):
        client = Client([calls(('object_info', {'object': 1})), calls(('object_info', {'object': 1})),
                         {'role': 'assistant', 'content': '失败'}])
        outcome = run(client, lambda s: (False, [], 'error'), native=True)
        self.assertFalse(outcome.steps[1].ok)

    def test_corrected_retry_clears_recovered_failure(self):
        client = Client([calls(('pitch_statistics', {'object': 2})), calls(('pitch_statistics', {'object': 1})),
                         {'role': 'assistant', 'content': '完成'}])
        outcome = run(client, lambda s: (True, ['基频=220'], ''), native=True)
        self.assertFalse(outcome.steps[0].ok)
        self.assertTrue(outcome.steps[1].ok)
        self.assertEqual(outcome.failure, '')

    def test_json_refresh_and_empty_reply_recovery_keep_observations(self):
        client = Client([{'actions': [{'tool': 'select_object', 'arguments': {'object': 1}}]},
                         {'reply': ''}, {'reply': '已选Sound'}])
        run(client, lambda s: (True, ['实测=220'], ''), native=False, refresh_context=lambda: NEW)
        self.assertIn('Sound あなた\t1', client.contexts[1])
        self.assertIn('实测=220', str(client.seen[-1]))

    def test_wrap_up_failure_still_returns_measured_results(self):
        """收尾那轮网络失败，不能把已经测到的结果丢掉（2026-09-30 真机验收发现）。

        实测：真云端跑「分析整段语音」时，工具都执行完了，最后 ``wrap_up()`` 的
        HTTP 读超时抛出 ``QwenError``，整轮直接以异常结束——用户什么结果都看不到。
        收尾只是「把结果写成一段中文」，失败必须降级成实测摘要，而不是崩掉。

        ``max_rounds=1`` 让循环执行完这一批动作就用完轮数，从而走到收尾那轮。
        """

        client = Client([calls(('object_info', {'object': 1}))], api=True)
        calls_to_chat = {'n': 0}

        def failing_chat(messages, **kwargs):
            calls_to_chat['n'] += 1
            raise qwen.QwenError('Qwen request failed: The read operation timed out')

        client.chat = failing_chat
        outcome = run(client, lambda s: (True, ['时长 = 1.000 秒'], ''), native=True, max_rounds=1)
        self.assertEqual(calls_to_chat['n'], 2, '收尾失败后应该重试一次')
        self.assertIn('时长 = 1.000 秒', outcome.reply)
        self.assertTrue(any('收尾回答' in note for note in outcome.notes), outcome.notes)

    def test_wrap_up_failure_recovers_on_retry(self):
        """重试成功时就用模型给出的回答，不用摘要。"""

        client = Client([calls(('object_info', {'object': 1}))], api=True)
        calls_to_chat = {'n': 0}

        def flaky_chat(messages, **kwargs):
            calls_to_chat['n'] += 1
            if calls_to_chat['n'] == 1:
                raise qwen.QwenError('Qwen request failed: The read operation timed out')
            return '**观测**：这次测到的时长是 1.000 秒。'

        client.chat = flaky_chat
        outcome = run(client, lambda s: (True, ['时长 = 1.000 秒'], ''), native=True, max_rounds=1)
        self.assertEqual(calls_to_chat['n'], 2)
        self.assertIn('**观测**', outcome.reply)

    def test_whole_recording_ignores_editor_selection(self):
        client = Client([calls(('pitch_statistics', {'object': 1})), {'role': 'assistant', 'content': '完成'}])
        outcome = run(client, lambda s: (True, ['ok'], ''), native=True, user_text='分析整段语音指出不足之处')
        self.assertNotIn('0.100000', outcome.steps[0].script)
        self.assertNotIn('0.1\t0.6', client.seen[0][0]['content'])

    def test_api_allows_more_steps_and_followup_analysis_preparation(self):
        client = Client([calls(('object_info', {'object': 1})), calls(('select_object', {'object': 1})),
                         calls(('pitch_statistics', {'object': 1})), calls(('intensity_statistics', {'object': 1})),
                         {'role': 'assistant', 'content': '完成'}], api=True)
        outcome = run(client, lambda s: (True, ['ok'], ''), native=True, refresh_context=lambda: NEW)
        self.assertEqual(sum(bool(s.script) for s in outcome.steps), 4)

    def test_invalid_parameters_never_execute_default_mutation(self):
        message = calls(('remove_object', {}))
        message['tool_calls'][0]['function']['arguments'] = '{broken'
        client = Client([message, {'role': 'assistant', 'content': '未执行'}])
        scripts = []
        outcome = run(client, lambda s: (scripts.append(s) or True, [], ''), native=True)
        self.assertEqual(scripts, [])
        self.assertFalse(outcome.steps[0].ok)

    def test_legacy_json_top_level_script_is_executed(self):
        client = Client([{'tool': 'custom_script', 'arguments': {}, 'script': 'selectObject: 1'}, {'reply': '完成'}])
        scripts = []
        run(client, lambda s: (scripts.append(s) or True, ['ok'], ''), native=False)
        self.assertIn('selectObject: 1', scripts[0])

    def test_large_api_observation_is_clipped_without_losing_call_pairs(self):
        client = Client([calls(('object_info', {'object': 1})), {'role': 'assistant', 'content': '完成'}], api=True)
        client.config.limit_tokens = True
        run(client, lambda s: (True, ['测量结果 ' + 'x' * 160000], ''), native=True)
        messages = client.seen[-1]
        self.assertEqual(len([m for m in messages if m['role'] == 'tool']), 1)
        self.assertIn('截短', str(messages))
        self.assertLess(qwen.estimate_tokens(json.dumps(messages, ensure_ascii=False)), 26000)

    def test_unlimited_api_keeps_full_observation(self):
        client = Client([calls(('object_info', {'object': 1})), {'role': 'assistant', 'content': '完成'}], api=True)
        run(client, lambda s: (True, ['测量结果 ' + 'x' * 160000], ''), native=True)
        self.assertIn('x' * 160000, str(client.seen[-1]))


class CompletionTests(unittest.TestCase):
    def test_protocol_two_waits_until_matching_callback_finished(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chat, 'runtime_dir', return_value=Path(directory)):
            chat.context_path().write_text(OLD + '# praat-protocol=2\n', encoding='utf-8')
            chat.started_marker_path().write_text('started abc\n', encoding='utf-8')
            chat.state_path().write_text('done\n', encoding='utf-8')
            self.assertFalse(chat._completion_state('abc')[0])
            (Path(directory) / 'chat_finished.txt').write_text('finished old\n', encoding='utf-8')
            self.assertFalse(chat._completion_state('abc')[0])
            (Path(directory) / 'chat_finished.txt').write_text('finished abc\n', encoding='utf-8')
            self.assertTrue(chat._completion_state('abc')[0])


class RequestContextTests(unittest.TestCase):
    """整段请求要清掉编辑器旧选区，但只能动那两列。"""

    def test_only_the_selection_columns_are_cleared(self):
        text = chat._request_context(OLD, '分析整段语音指出不足')
        self.assertEqual(
            text,
            'id\tclass\tname\tselected\tsel_start\tsel_end\n'
            '1\tSound\tSound あなた\t0\t\t\n'
            '2\tHarmonicity\tHarmonicity あなた\t1\t\t\n',
        )
        # 清完仍然读得出同样的对象，只是没有圈选。
        rows = tools.parse_object_context(text)
        self.assertEqual([(row.id, row.class_name, row.selected) for row in rows],
                         [(1, 'Sound', False), (2, 'Harmonicity', True)])
        self.assertTrue(all(row.selection is None for row in rows))

    def test_four_column_legacy_lines_are_untouched(self):
        legacy = 'id\tclass\tname\tselected\n1\tSound\ttone\t1\n'
        self.assertEqual(chat._request_context(legacy, '分析整段语音'), legacy)

    def test_extra_columns_are_not_truncated(self):
        """列数比 6 多（以后协议再加列）时不能把多出来的列吃掉。"""

        wider = OLD + '3\tSound\tthree\t0\t0.2\t0.3\tfuture\n'
        result = chat._request_context(wider, '分析整段语音')
        self.assertIn('3\tSound\tthree\t0\t0.2\t0.3\tfuture', result)

    def test_non_recording_request_keeps_the_editor_selection(self):
        for user_text in ('分析我圈出来的这一段', '看看这个声音的基频', '截取 0.2 到 0.5 秒'):
            with self.subTest(user_text=user_text):
                self.assertEqual(chat._request_context(OLD, user_text), OLD)

    def test_whole_recording_phrasings_are_recognised(self):
        for user_text in ('分析整段语音', '整个声音的基频', '分析 the whole recording',
                          'analyze the entire file', 'full audio 的平均强度'):
            with self.subTest(user_text=user_text):
                self.assertNotIn('0.1\t0.6', chat._request_context(OLD, user_text))
                self.assertIn('0.1\t0.6', chat._request_context(OLD, '分析圈选的这一段'))

    def test_local_prefix_of_whole_does_not_count(self):
        # “wholesale” 不该被当成 whole。
        self.assertIn('0.1\t0.6', chat._request_context(OLD, 'wholesale comparison'))


if __name__ == '__main__':
    unittest.main()
