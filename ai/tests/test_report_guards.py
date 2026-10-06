import unittest

from pydantic_ai import ModelRetry

from praat_ai.cloud_agent import AnalysisReport, Coverage
from praat_ai.escape_policy import AnalysisState, Evidence
from praat_ai.report_guards import (UNVERIFIED_CALC, report_context_data, report_guard_instructions,
                                    validate_report)


CONTEXT = '1\tSound\ttarget\t1\t0.2\t0.4\n2\tSound\tother\t0\n'


def report(text, explanation='已有解释和实际证据，仍应核对录音范围。'):
    return AnalysisReport(analysis=text + '\n报告依据已有记录，范围外的声音特征仍需相应测量。',
                          coverage=[Coverage(item='分析录音', status='partial', explanation=explanation)])


def evidence(tool, rows, obj=1, **args):
    return Evidence(tool, {'object': obj, **args}, rows, CONTEXT)


def pitch(mean=220, start=0, end=1, obj=1):
    return evidence('pitch_statistics',
                    [f'基频统计（{start:.3f}–{end:.3f} 秒）：平均 {mean:.3f} Hz，最低 200.000 Hz，最高 240.000 Hz，最高点出现在 0.600 秒'],
                    obj=obj, **{'from': start, 'to': end})


class ReportGuardsTests(unittest.TestCase):
    def test_vot_report_accepts_known_id_colon_but_rejects_unknown_id(self):
        context = 'id\tclass\tname\tselected\n1\tSound\tSound あなた\t1\n'
        item = Evidence('vot', {'object':1, 'from':0.446194, 'to':0.66158},
                        ['VOT 估计值 = 0.0380 秒（38.0 毫秒）：爆破 0.551 秒 → 浊音起始 0.589 秒'], context)
        for label in ('ID: 1', 'id：1', '对象 1', 'object: 1'):
            with self.subTest(label=label):
                state = AnalysisState('分析录音', context, evidence=[item])
                self.accepts(state, f'本次分析针对对象 Sound あなた（{label}）。\nVOT 估计值为 38.0 毫秒。[E1]')
        for label in ('ID: 99', 'id：99', 'object: 99'):
            with self.subTest(label=label):
                state = AnalysisState('分析录音', context, evidence=[item])
                self.rejects(state, f'本次分析针对对象 Sound あなた（{label}）。')
                self.assertEqual(state.metrics['guard_blocks'], {'report.object_unknown':1})
        self.rejects(AnalysisState('分析录音', context, evidence=[item]), '本次测得计数为 1。')

    def state(self, *items):
        return AnalysisState('分析录音语调', CONTEXT, evidence=list(items))

    def accepts(self, state, text):
        return validate_report(state, report(text))

    def rejects(self, state, text):
        with self.assertRaises(ModelRetry):
            self.accepts(state, text)

    def test_context_indexes_have_roles_without_duplicate_values(self):
        state = self.state(pitch())
        context = report_context_data(state)
        self.assertEqual(context['evidence_ids'], ['E1'])
        self.assertEqual(context['quantity_refs']['E1'][:3], ['r1:range.start', 'r1:range.end', 'r1:pitch.mean'])
        self.assertNotIn('220', str(context))
        self.assertIn('E1.q1', report_guard_instructions(state))
        self.assertEqual(report_context_data(self.state()), {})
        self.assertIn('没有测量', report_guard_instructions(self.state()))

    def test_real_measurement_with_range_and_unit_conversion(self):
        self.accepts(self.state(pitch()), '本段在 0.000–1.000 秒的平均基频为 0.220 kHz。[E1]')
        self.accepts(self.state(pitch(219.96)), '平均基频约 220.0 Hz。[E1]')

    def test_fabricated_number_without_or_with_unrelated_citation(self):
        # 编造的数值照旧拦；但「漏写引证」和「写错编号」不再算编造——守卫自己会把引证
        # 补上、把不存在的编号清掉（2026-10-06 起：引证是守卫的记账方式，不是模型必须
        # 逐行照抄的格式）。
        self.rejects(self.state(), '这段录音的平均基频是 220 Hz。')
        self.rejects(self.state(pitch()), '平均基频是 300 Hz。[E1]')
        self.rejects(self.state(pitch()), '平均基频是 300 Hz。')
        state = self.state(pitch())
        result = self.accepts(state, '平均基频是 220 Hz。[E99]')
        self.assertIn('[E1]', result.analysis)
        self.assertNotIn('[E99]', result.analysis)
        self.assertIn('[E1]', self.accepts(self.state(pitch()), '平均基频是 220 Hz。').analysis)
        self.assertEqual(state.metrics['guard_repairs'],
                         {'report.citation_unknown': 1, 'report.citation_filled': 1})

    def test_wrong_units_are_not_the_same_quantity(self):
        self.rejects(self.state(pitch()), '平均基频是 220 kHz。[E1]')
        self.rejects(self.state(pitch()), '平均基频是 220 ms。[E1]')
        self.rejects(self.state(pitch()), '平均基频是 220。[E1]')

    def test_matching_number_from_f1_is_not_mean_pitch(self):
        item = evidence('formant_frequency', ['F1 = 220.000 Hz'])
        self.accepts(self.state(item), '第一共振峰 F1 为 220 Hz。[E1]')
        self.rejects(self.state(item), '平均基频为 220 Hz。[E1]')

    def test_vot_components_keep_their_own_wording(self):
        # 2026-10-06 实测：vot 那一行的每个数都被打成 vot.value，而报告里「爆破 0.551 秒」
        # 这类换个说法的句子拿不到量名，两边标签一比就判成编造，两次拒绝后整份回答被
        # 换掉。没点名量名的出处标签现在退回「同对象 + 同范围 + 同量纲 + 同数值」核对。
        item = evidence('vot', ['VOT 估计值 = 0.0380 秒（38.0 毫秒）：爆破 0.551 秒；浊音起始 0.589 秒'])
        for text in ['爆破 0.551 秒 [E1]，浊音起始 0.589 秒 [E1]。',
                     '该音的爆破出现在 0.551 秒 [E1]',
                     '- 浊音起始：0.589 秒 [E1]']:
            with self.subTest(text=text):
                self.accepts(self.state(item), text)
        self.rejects(self.state(item), '爆破 0.777 秒 [E1]。')
        # 漏写引证不再是编造：守卫自己把数字落在哪条证据上写进正文。
        self.assertIn('[E1]', self.accepts(self.state(item), '爆破 0.551 秒。').analysis)

    def test_numeric_object_and_range_must_match(self):
        self.rejects(self.state(pitch(obj=2)), '本段平均基频为 220 Hz。[E1]')
        self.accepts(self.state(pitch(obj=2)), '对象 2 other 的平均基频为 220 Hz。[E1]')
        self.rejects(self.state(pitch()), '在 0.000–0.500 秒的平均基频是 220 Hz。[E1]')
        self.rejects(self.state(pitch(210, 0, .5), pitch(220, .5, 1)),
                     '在 0.000–0.500 秒的平均基频是 220 Hz。[E1] [E2]')

    def test_block_counters_name_the_rule(self):
        # 守卫的强制力必须可统计：哪条规则真的在拦、拦了几次，是决定它继续当闸门还是
        # 退回提示词的唯一依据（2026-10-06 那次事故只能靠猜）。
        state = self.state(pitch())
        self.rejects(state, '平均基频是 300 Hz。[E1]')
        self.assertEqual(state.metrics['guard_blocks'], {'report.number_unmatched': 1})
        self.rejects(state, '本段音高下降。[E1]')
        self.assertEqual(state.metrics['guard_blocks'],
                         {'report.number_unmatched': 1, 'report.prosody_untraced': 1})
        self.rejects(state, '对象 99 的平均基频为 220 Hz。[E1]')
        self.assertEqual(state.metrics['guard_blocks']['report.object_unknown'], 1)

    def test_general_knowledge_and_ordinary_dialogue_need_no_tool(self):
        self.accepts(self.state(), '一般知识：一八度包含 12 个半音，这只是概念说明。')
        self.accepts(self.state(), '# 一般知识\n通常用 75–600 Hz 作为分析示例。\n# 本次结果\n没有测量，不能判断这段录音是否为平板型。')
        self.accepts(self.state(), '你好，我们可以先明确你的目标，再选择合适的操作。')
        self.rejects(self.state(), '一般知识：本录音的平均基频为 220 Hz。')

    def test_honest_missing_measurement_is_not_a_prosody_claim(self):
        for text in ('不能判断平板型，缺少音高走向测量。',
                     '只有全段平均值，无法判断这段语调是否平淡。',
                     '平均值不代表音高下降，需要先取得分段测量。'):
            self.accepts(self.state(), text)
        self.rejects(self.state(), '不能判断平板型，但这段音高下降。')
        self.rejects(self.state(), '这段不是平板型，而是头高型。')

    def test_mean_alone_cannot_support_prosody(self):
        self.rejects(self.state(pitch()), '平均基频 220 Hz，所以本段是平板型。[E1]')
        self.rejects(self.state(pitch()), '这段音高下降。[E1]')
        self.accepts(self.state(pitch()), '平均基频为 220 Hz，仍不能判断平板型，需要走向测量。[E1]')

    def test_defined_slope_supports_variability_but_absolute_slope_not_direction(self):
        slope = evidence('measure', ['基频平均绝对斜率 = 1.00 Hz/s'], parameters=['pitch_slope'])
        self.accepts(self.state(slope), '基频平均绝对斜率为 1 Hz/s，本段语调平坦；局部情况仍须核对。[E1]')
        self.rejects(self.state(slope), '本段音高下降。[E1]')
        octave_free = evidence('measure', ['不含倍频跳变的基频斜率 = 1.00 半音/s'], parameters=['pitch_slope_octave_free'])
        self.accepts(self.state(octave_free), '不含倍频跳变的基频斜率为 1 半音/s，本段语调平坦。[E1]')
        self.rejects(self.state(octave_free), '本段音高下降。[E1]')

    def test_defined_start_end_pair_same_target_and_range(self):
        start = evidence('measure', ['起点基频（0.000–1.000 秒）= 240.00 Hz'], parameters=['pitch_start'], **{'from': 0, 'to': 1})
        end = evidence('measure', ['终点基频（0.000–1.000 秒）= 200.00 Hz'], parameters=['pitch_end'], **{'from': 0, 'to': 1})
        self.accepts(self.state(start, end), '本段音高下降；起终点测量可支持整体趋势，局部轨迹仍要核对。[E1] [E2]')
        self.rejects(self.state(start), '本段音高下降。[E1]')
        other = evidence('measure', end.rows, obj=2, parameters=['pitch_end'], **{'from': 0, 'to': 1})
        self.rejects(self.state(start, other), '本段音高下降。[E1] [E2]')
        different_range = evidence('measure', ['终点基频（1.000–2.000 秒）= 200.00 Hz'], parameters=['pitch_end'], **{'from': 1, 'to': 2})
        self.rejects(self.state(start, different_range), '本段音高下降。[E1] [E2]')

    def test_defined_ordered_segments_support_trajectory(self):
        self.accepts(self.state(pitch(240, 0, .5), pitch(200, .5, 1)),
                     '本段音高下降，分段平均值显示前后差异，但音调分类仍须结合对齐。[E1] [E2]')
        self.rejects(self.state(pitch(240, 0, 1), pitch(200, 0, 1)), '本段音高下降。[E1] [E2]')
        self.rejects(self.state(pitch(240, 0, .5), pitch(200, .5, 1, obj=2)), '本段音高下降。[E1] [E2]')

    def test_undefined_irrelevant_and_nonmeasurement_do_not_support_prosody(self):
        undefined = evidence('measure', ['起点基频（0.000–1.000 秒）无法计算：这一段里没有可用的数据',
                                        '终点基频（0.000–1.000 秒）无法计算：这一段里没有可用的数据'],
                             parameters=['pitch_start', 'pitch_end'])
        undefined_slope = evidence('measure', ['基频平均绝对斜率 = --undefined--'], parameters=['pitch_slope'])
        intensity = evidence('measure', ['强度斜率 = 1.00 dB'], parameters=['mean_intensity'])
        audio = Evidence('listen', {}, ['基频斜率 = 1.00 Hz/s'], CONTEXT, kind='audio')
        for item in (undefined, undefined_slope, intensity, audio, pitch(obj=2)):
            self.rejects(self.state(item), '这段语调平坦。[E1]')
        self.rejects(self.state(undefined), '起点基频为 0 Hz。[E1]')

    def test_deterministic_transparent_percentage_derivation(self):
        state = self.state(evidence('pitch_statistics', ['基频统计（0.200–0.400 秒）：平均 220.000 Hz']),
                           evidence('duration', ['target 总时长 = 1.000000 秒']))
        result = self.accepts(state, '选段起点占总时长的比例为 {{calc:E1.q1/E2.q1*100|%}}。')
        self.assertIn('(0.200 秒)/(1.000000 秒)*100 = 20 % [E1] [E2]', result.analysis)
        self.assertNotIn('{{calc:', result.analysis)
        self.rejects(state, '选段占比为 90 %；算式为 {{calc:E1.q1/E2.q1*100|%}}。')

    def test_derivation_checks_reference_units_arithmetic_and_no_code(self):
        state = self.state(pitch(), evidence('duration', ['target 总时长 = 1.000000 秒']))
        # 算不出来的推导式只把那一处标成「未核对」，不再阻断整份报告：这一处不成立不等于
        # 报告在编造测量（2026-10-06 起；原来 20 个阻断点里有 13 个是这类内部语法问题）。
        for expression in ('E1.q99/E2.q1*100|%', 'E1.q3+E2.q1|Hz', 'E1.q3/E2.q1|ms',
                           'E1.q3/0|Hz', '999|Hz', '__import__("os")|Hz', 'E1.q3**2|Hz',
                           'E1.q3+999|Hz', 'E1.q3|madeup', 'E1.q1/E2.q1*100|Hz'):
            with self.subTest(expression=expression):
                result = self.accepts(state, '透明推导为 {{calc:' + expression + '}}。')
                self.assertIn(UNVERIFIED_CALC, result.analysis)
                self.assertNotIn('{{calc:', result.analysis)
        result = self.accepts(state, '透明推导为 {{calc:E1.q3}}。')
        self.assertIn(UNVERIFIED_CALC, result.analysis)
        self.assertNotIn('os', result.analysis)     # 注入文本既不会执行，也不会留在正文里
        # 算得出来的照样由程序写结果。
        self.assertIn('(220.000 Hz)', self.accepts(state, '平均基频换算为 {{calc:E1.q3|kHz}}。').analysis)
        self.assertIn('(1.000000 秒)', self.accepts(state, '总时长换算为 {{calc:E2.q1|ms}}。').analysis)

    def test_derivation_cannot_launder_f1_into_mean_pitch(self):
        state = self.state(evidence('formant_frequency', ['F1 = 220.000 Hz']))
        self.rejects(state, '平均基频为 {{calc:E1.q1|Hz}}。')

    def test_derivation_cannot_launder_other_recording_as_original_target(self):
        state = self.state(pitch(), pitch(obj=2))
        self.rejects(state, '本段平均基频为 {{calc:E2.q3*1|Hz}}。')
        self.accepts(state, '对象 2 other 的平均基频为 {{calc:E2.q3|Hz}}。')

    def test_non_pitch_directions_and_noise_recommendations_are_not_prosody(self):
        self.accepts(self.state(), '下一步先降低噪声，再取得可靠测量；调整位置有助于降低误差。')
        self.accepts(self.state(), '强度下降可能影响响度，需要强度测量才能具体说明。')
        self.accepts(self.state(), '共振峰升高可能反映口形改变，这里尚未取得相应测量。')

    def test_whole_recording_conclusion_cannot_use_two_tiny_unrelated_segments(self):
        state = self.state(pitch(240, 0, .1), pitch(200, .9, 1),
                           evidence('duration', ['target 总时长 = 1.000000 秒']))
        state.goal = '分析整段录音语调'
        self.rejects(state, '整段录音音高下降。[E1] [E2]')
        state.evidence[:2] = [pitch(240, 0, .5), pitch(200, .5, 1)]
        self.accepts(state, '整段录音音高下降；分段测量只支持整体趋势。[E1] [E2]')

    def test_percentage_and_milliseconds_from_real_measurement(self):
        state = self.state(evidence('vot', ['VOT = 25.000 毫秒']),
                           evidence('measure', ['jitter = 1.25 %']))
        self.accepts(state, 'VOT 为 0.025 秒。[E1]')
        self.accepts(state, 'jitter = 1.25 %。[E2]')
        self.rejects(state, 'VOT 为 25 秒。[E1]')
        self.rejects(state, 'jitter = 125 %。[E2]')

    def test_coverage_explanations_are_checked_too(self):
        with self.assertRaises(ModelRetry):
            validate_report(self.state(pitch()), report('现有平均值不足以判断具体音调类型，须先取得走向测量。',
                                                        '本段平均基频为 999 Hz。[E1]'))

    def test_next_step_parameters_are_not_fabricated_measurements(self):
        self.accepts(self.state(), '建议重复测量 3 次，再选择 75 Hz 的基频下限作参数对照。')
        self.rejects(self.state(), '建议使用本录音测得的 220 Hz 作为依据。')

    def test_report_cannot_invent_object_identifier(self):
        self.rejects(self.state(pitch()), '对象 99 的平均基频为 220 Hz。[E1]')

    def test_whole_mean_cannot_relabel_segment_mean(self):
        state = self.state(pitch(220, .2, .4), evidence('duration', ['target 总时长 = 1.000000 秒']))
        state.goal = '分析整个声音的音调'
        self.rejects(state, '整段平均基频为 220 Hz。[E1]')
        self.rejects(state, '整段平均基频为 {{calc:E1.q3|Hz}}。')
        self.accepts(state, '在 0.200–0.400 秒的平均基频为 220 Hz。[E1]')


if __name__ == '__main__':
    unittest.main()
