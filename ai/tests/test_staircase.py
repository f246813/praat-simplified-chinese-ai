import unittest
from praat_ai.escape_policy import AnalysisState, Budget, BranchExit, Evidence


class PolicyTests(unittest.TestCase):
    def test_one_distinct_repair_across_modes(self):
        state = AnalysisState('compare pronunciation', 'original selection')
        state.failed('formant', 'invalid arguments')
        self.assertEqual(state.mode, 'L1')
        with self.assertRaises(BranchExit):
            state.failed('formant', 'invalid arguments again')

    def test_two_stagnant_rounds(self):
        state = AnalysisState('goal', '')
        state.finish_round()
        with self.assertRaises(BranchExit):
            state.finish_round()

    def test_new_evidence_resets_stagnation_duplicate_does_not(self):
        state = AnalysisState('goal', '')
        state.finish_round()
        state.add_evidence(Evidence('pitch', {'time':0.5}, ['220 Hz'], 'original selection'))
        state.finish_round()
        state.add_evidence(Evidence('pitch', {'time':0.5}, ['220 Hz'], 'original selection'))
        state.finish_round()
        with self.assertRaises(BranchExit):
            state.finish_round()

    def test_report_reserve_and_physical_boundary(self):
        budget = Budget(context_tokens=4096, response_tokens=1000)
        self.assertFalse(budget.should_close(1000))
        self.assertTrue(budget.should_close(3000))
        self.assertGreater(budget.reserve, 1000)

    def test_continue_keeps_goal_evidence_and_failed_branches(self):
        state = AnalysisState('原始目标', 'original selection')
        state.add_evidence(Evidence('pitch', {}, ['220 Hz'], 'original selection'))
        state.failures['formant'] = 2
        next_state = state.continued('补充解释')
        self.assertEqual(next_state.goal, state.goal)
        self.assertEqual(next_state.context_text, state.context_text)
        self.assertEqual(next_state.evidence, state.evidence)
        self.assertEqual(next_state.failures['formant'], 2)
        self.assertIn('原始目标', next_state.visible_prompt)


if __name__ == '__main__':
    unittest.main()
