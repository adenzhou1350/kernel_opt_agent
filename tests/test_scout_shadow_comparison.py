import unittest
from scripts.scout_shadow_comparison import (
    bidirectional_rule_choice, choice, make_view, normalized_usage, observe,
    parsed, rule_choice, run_arm, validate_verdict,
)


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.assets = {'a.go': dict(text='first\nsecond\nthird\n', sha256='synthetic')}
        self.packet = dict(repo='o/r', sources=[dict(
            url='https://raw.githubusercontent.com/o/r/'+'a'*40+'/a.go',
            text='first', start_line=1, end_line=1)])
        self.view = make_view(self.packet, repo='o/r', commit='a'*40, assets=self.assets)

    def test_cache_conventions_and_unknown(self):
        self.assertEqual(normalized_usage('kimi', dict(input_tokens=100, output_tokens=10,
                                                      cached_input_tokens=80)), 110)
        self.assertEqual(normalized_usage('m3', dict(input_tokens=20, output_tokens=10,
            cache_read_input_tokens=80, cache_creation_input_tokens=0)), 110)
        self.assertIsNone(normalized_usage('m3', dict(input_tokens=20, output_tokens=10)))
        self.assertIsNone(normalized_usage('kimi', dict(input_tokens=True, output_tokens=2)))

    def test_two_ranges_and_no_silent_shortening(self):
        selected = choice(dict(path='a.go', ranges=[dict(start_line=1, line_count=1),
            dict(start_line=3, line_count=1)], reason='closure'), self.view['catalog'])
        observation = observe(selected, self.assets)
        self.assertEqual(observation['status'], 'ACQUIRED')
        self.assertEqual(observation['excerpts']['selected_lines'], 2)
        self.assertEqual(observation['logical_source_bytes'], 19)
        selected['ranges'][1]['line_count'] = 2
        self.assertEqual(observe(selected, self.assets)['status'], 'FAILED')

    def test_reject_bad_actions(self):
        for ranges in ([dict(start_line=1, line_count=81)],
                       [dict(start_line=1, line_count=2), dict(start_line=2, line_count=1)],
                       [dict(start_line=True, line_count=1)]):
            self.assertEqual(choice(dict(path='a.go', ranges=ranges, reason='x'),
                                    self.view['catalog'])['status'], 'INVALID_SELECTION')
        self.assertEqual(choice(dict(path='../secret', ranges=[], reason='x'),
                                self.view['catalog'])['status'], 'INVALID_SELECTION')
        self.assertEqual(choice(dict(path=[], ranges=[], reason='x'),
                                self.view['catalog'])['status'], 'INVALID_SELECTION')
        self.assertEqual(choice(dict(path=None, ranges=[], reason='x'),
                                self.view['catalog'])['status'], 'ABSTAIN')

    def test_quote_is_not_hypothesis_or_other_range(self):
        verdict = dict(verdict='SUPPORTED_FAILURE', decisive_evidence='second',
                       reason='x', next_native_check=None)
        observation = dict(status='NO_ADDITIONAL_SOURCE')
        self.assertFalse(validate_verdict(verdict, self.view, observation))
        verdict['decisive_evidence'] = 'first'
        self.assertTrue(validate_verdict(verdict, self.view, observation))
        verdict['decisive_evidence'] = None
        self.assertFalse(validate_verdict(verdict, self.view, observation))
        verdict['verdict'] = 'INSUFFICIENT'
        self.assertTrue(validate_verdict(verdict, self.view, observation))

    def test_completion_and_strict_json(self):
        self.assertIsNone(parsed(dict(response=dict(ok=False, text='{}'))))
        self.assertIsNone(parsed(dict(response=dict(ok=True, text='```json\n{}\n```'))))

    def test_malformed_verdict_is_invalid_not_a_crash(self):
        verdict = dict(verdict=[], decisive_evidence='first', reason='x', next_native_check=None)
        self.assertFalse(validate_verdict(verdict, self.view, dict(status='NO_ADDITIONAL_SOURCE')))

    def test_numbered_delivery_keeps_exact_quote_contract(self):
        selected = dict(status='SELECTED', path='a.go', ranges=[dict(start_line=2, line_count=2)])
        observation = observe(selected, self.assets, numbered=True)
        self.assertEqual(observation['excerpts']['windows'][0]['text'], '2: second\n3: third')
        self.assertEqual(observation['excerpts']['selected_chars'], len('second\nthird'))
        verdict = dict(verdict='REFUTED_PREMISE', decisive_evidence='2: second\n3: third', reason='x', next_native_check=None)
        self.assertTrue(validate_verdict(verdict, self.view, observation))
        verdict['decisive_evidence'] = 'second\nthird'
        self.assertFalse(validate_verdict(verdict, self.view, observation))

    def test_equal_calls_reflection_and_selection(self):
        verdict = dict(verdict='INSUFFICIENT', decisive_evidence=None,
                       reason='x', next_native_check='test')
        for action in ('none', 'rule', 'select'):
            seen = []
            def invoke(provider, prompt, cap):
                import json
                seen.append((provider, cap))
                value = (dict(path='a.go', ranges=[dict(start_line=2, line_count=1)], reason='x')
                         if action == 'select' and len(seen) == 1 else verdict)
                return dict(response=dict(ok=True, text=json.dumps(value)),
                            normalized_total_tokens=5)
            record = run_arm(self.view, self.assets, ('test', 'kimi', action, 'kimi'), invoke)
            self.assertEqual(seen, [('kimi', 768), ('kimi', 1024)])
            self.assertTrue(record['protocol_valid'])
            self.assertEqual(record['normalized_total_tokens'], 10)

    def test_no_retry_on_prompt_limit(self):
        def forbidden(*args):
            self.fail('must not call provider on oversized prompt')
        result = run_arm(self.view, self.assets, ('t', 'kimi', 'none', 'kimi'), forbidden,
                         each_prompt_bytes=5, total_prompt_bytes=10)
        self.assertFalse(result['protocol_valid'])
        self.assertEqual(len(result['calls']), 2)
        self.assertTrue(all(not c['attempted'] for c in result['calls']))

    def test_revision_and_private_material_rejected(self):
        with self.assertRaises(ValueError):
            make_view(self.packet, repo='o/r', commit='b'*40, assets=self.assets)
        self.packet['question'] = '/workspace/kernel-opt/private/x'
        with self.assertRaises(ValueError):
            make_view(self.packet, repo='o/r', commit='a'*40, assets=self.assets)

    def test_future_rule_reads_before_eof_not_beyond_it(self):
        source = self.view['packet']['sources'][0]
        source.update(start_line=3, end_line=3, text='3: third')
        self.assertEqual(rule_choice(self.view)['error_kind'], 'WINDOW_BEYOND_SOURCE')
        selected = bidirectional_rule_choice(self.view)
        self.assertEqual(selected['ranges'], [dict(start_line=1, line_count=2)])
        self.assertEqual(observe(selected, self.assets)['status'], 'ACQUIRED')

    def test_future_rule_preserves_forward_and_abstains_on_complete_file(self):
        self.assertEqual(bidirectional_rule_choice(self.view), rule_choice(self.view))
        self.view['packet']['sources'][0].update(start_line=1, end_line=3)
        self.assertEqual(bidirectional_rule_choice(self.view)['status'], 'ABSTAIN')

    def test_future_rule_rejects_inconsistent_eof_metadata(self):
        self.view['packet']['sources'][0].update(start_line=2, end_line=4)
        self.assertEqual(bidirectional_rule_choice(self.view)['status'], 'UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
