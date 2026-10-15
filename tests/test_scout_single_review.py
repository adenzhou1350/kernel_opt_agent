"""Future comparison mechanics only; no provider calls or efficacy oracle."""
import json
import unittest

from scripts.scout_shadow_comparison import (
    make_view, run_arm, summarize_repeated_reviews, summarize_reported_tokens,
)


class SingleReviewTests(unittest.TestCase):
    def setUp(self):
        self.assets = {'a.py': dict(text='first\nsecond\nthird', sha256='fixture')}
        self.view = make_view(dict(repo='o/r', sources=[dict(text='first', start_line=1,
            end_line=1, url='https://raw.githubusercontent.com/o/r/'+'a'*40+'/a.py')]),
            repo='o/r', commit='a'*40, assets=self.assets)

    def answer(self):
        return dict(verdict='INSUFFICIENT', decisive_evidence=None,
                    reason='Not a semantic oracle', next_native_check=None)

    def test_fixed_arm_calls_only_the_final_reviewer_without_prior_answer(self):
        seen = []
        def invoke(provider, prompt, cap):
            seen.append((provider,prompt,cap))
            return dict(response=dict(ok=True,text=json.dumps(self.answer())), normalized_total_tokens=7)
        result = run_arm(self.view,self.assets,('fixed','unused','none','reviewer'),invoke,single_review=True)
        self.assertEqual([(p,c) for p,_,c in seen],[('reviewer',1024)])
        self.assertNotIn('first_pass_untrusted',seen[0][1])
        self.assertTrue(result['protocol_valid'])
        self.assertEqual(result['normalized_total_tokens'],7)
        self.assertEqual(result['token_accounting']['known_token_lower_bound'],7)
        self.assertEqual(result['review_mode'],'single_final_review')

    def test_selector_answer_is_not_given_to_the_common_reviewer(self):
        seen = []
        def invoke(provider,prompt,cap):
            seen.append((provider,prompt,cap))
            value = (dict(path='a.py',ranges=[dict(start_line=2,line_count=1)],
                          reason='selector-private-reason-sentinel') if len(seen)==1 else self.answer())
            return dict(response=dict(ok=True,text=json.dumps(value)), normalized_total_tokens=5)
        result = run_arm(self.view,self.assets,('selector','selector','select','reviewer'),invoke,single_review=True)
        self.assertEqual([(p,c) for p,_,c in seen],[('selector',768),('reviewer',1024)])
        self.assertNotIn('selector-private-reason-sentinel',seen[-1][1])
        self.assertTrue(result['protocol_valid'])
        self.assertEqual(result['normalized_total_tokens'],10)

    def test_legacy_default_still_uses_two_passes(self):
        seen=[]
        def invoke(provider,prompt,cap):
            seen.append(prompt)
            return dict(response=dict(ok=True,text=json.dumps(self.answer())),normalized_total_tokens=3)
        result=run_arm(self.view,self.assets,('legacy','reviewer','none','reviewer'),invoke)
        self.assertEqual(len(seen),2)
        self.assertIn('first_pass_untrusted',seen[-1])
        self.assertNotIn('review_mode',result)
        self.assertEqual(result['normalized_total_tokens'],6)

    def test_non_boolean_mode_fails_before_any_provider_call(self):
        def forbidden(*args):self.fail('invalid protocol must not call a provider')
        with self.assertRaises(ValueError):
            run_arm(self.view,self.assets,('bad','x','none','x'),forbidden,single_review='yes')

    def test_common_review_keeps_prompt_limit_no_call(self):
        def forbidden(*args):self.fail('oversized prompt must not call a provider')
        result=run_arm(self.view,self.assets,('cap','x','none','x'),forbidden,
                       single_review=True,each_prompt_bytes=5,total_prompt_bytes=5)
        self.assertFalse(result['protocol_valid'])
        self.assertEqual(len(result['calls']),1)
        self.assertFalse(result['calls'][0]['attempted'])

    def test_unknown_usage_does_not_erase_a_known_lower_bound(self):
        result=summarize_reported_tokens([dict(normalized_total_tokens=1504),dict(normalized_total_tokens=None)])
        self.assertIsNone(result['normalized_total_tokens'])
        self.assertEqual(result['known_token_lower_bound'],1504)
        self.assertEqual(result['known_usage_records'],1)
        self.assertEqual(result['unknown_usage_records'],1)

    def test_fixed_rule_modes_each_use_one_final_review(self):
        for action in ('rule', 'bidirectional_rule', 'bm25'):
            with self.subTest(action=action):
                seen = []
                def invoke(provider, prompt, cap):
                    seen.append(provider)
                    return dict(response=dict(ok=True, text=json.dumps(self.answer())),
                                normalized_total_tokens=9)
                result = run_arm(self.view, self.assets, ('fixed', 'unused', action, 'reviewer'),
                                 invoke, single_review=True)
                self.assertEqual(seen, ['reviewer'])
                self.assertTrue(result['protocol_valid'])

    def test_invalid_selector_is_not_repaired_by_a_valid_reviewer(self):
        seen = []
        def invoke(provider, prompt, cap):
            seen.append(provider)
            value = dict(path='../unavailable', ranges=[], reason='invalid') if len(seen)==1 else self.answer()
            return dict(response=dict(ok=True, text=json.dumps(value)), normalized_total_tokens=None)
        result = run_arm(self.view, self.assets, ('invalid', 'selector', 'select', 'reviewer'),
                         invoke, single_review=True)
        # This helper retains the legacy final call, not a caller's early-stop policy.
        self.assertEqual(seen, ['selector', 'reviewer'])
        self.assertTrue(result['valid_verdict'])
        self.assertFalse(result['protocol_valid'])
        self.assertIsNone(result['normalized_total_tokens'])
        self.assertEqual(result['token_accounting']['unknown_usage_records'], 2)

    def test_invalid_counters_are_unknown_and_empty_records_are_distinct(self):
        for value in (True,-1,1.5,'3'):
            result=summarize_reported_tokens([dict(normalized_total_tokens=value)])
            self.assertIsNone(result['normalized_total_tokens'])
            self.assertEqual(result['unknown_usage_records'],1)
        empty=summarize_reported_tokens([])
        self.assertEqual(empty['normalized_total_tokens'],0)
        self.assertEqual(empty['call_records'],0)
        with self.assertRaises(ValueError):summarize_reported_tokens([None])


class RepeatedReviewTests(unittest.TestCase):
    def record(self, attempt='one', **changes):
        return dict(dict(attempt_id=attempt, request_sha256='a'*64,
                         valid=True, correct=False, answer={'outcome': 'A'}), **changes)

    def test_equal_json_answers_and_different_request_groups(self):
        rows = [self.record(), self.record('two', answer={'outcome': 'A'}),
                self.record('three', request_sha256='b'*64, correct=True)]
        summary = summarize_repeated_reviews(rows)
        self.assertEqual(summary['actual_review_calls'], 3)
        self.assertEqual(summary['repeated_request_groups'], 1)
        self.assertEqual(summary['varied_request_groups'], 0)
        self.assertEqual(summary['groups'][0]['distinct_valid_answers'], 1)
        self.assertNotIn('outcome', json.dumps(summary))  # no raw answer objects

    def test_variation_is_separate_from_invalid_format_and_unknown_correctness(self):
        rows = [self.record(), self.record('two', answer={'outcome': 'B'}, correct=None),
                self.record('three', valid=False, correct=False, answer='unaccepted prose')]
        group = summarize_repeated_reviews(rows)['groups'][0]
        self.assertTrue(group['accepted_answer_varied'])
        self.assertEqual(group['valid_reviews'], 2)
        self.assertEqual(group['invalid_reviews'], 1)
        self.assertEqual(group['unknown_correctness'], 1)
        self.assertEqual(group['distinct_valid_answers'], 2)

    def test_rejects_duplicate_calls_bad_identity_and_assessments(self):
        with self.assertRaises(ValueError):
            summarize_repeated_reviews([self.record(), self.record()])
        for change in ({'request_sha256': 'short'}, {'request_sha256': 'G'*64},
                       {'valid': 1}, {'correct': 0}, {'valid': False, 'correct': True},
                       {'attempt_id': ''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_repeated_reviews([self.record(**change)])

    def test_rejects_non_json_or_unbounded_accepted_answers(self):
        for answer in (float('nan'), object(), 'x'*131073):
            with self.subTest(answer=type(answer)), self.assertRaises(ValueError):
                summarize_repeated_reviews([self.record(answer=answer)])
        row = self.record()
        del row['answer']
        with self.assertRaises(ValueError):
            summarize_repeated_reviews([row])

    def test_empty_has_no_calls_or_groups_and_does_not_mutate_input(self):
        self.assertEqual(summarize_repeated_reviews([])['actual_review_calls'], 0)
        rows = [self.record()]
        before = json.dumps(rows, sort_keys=True)
        summarize_repeated_reviews(rows)
        self.assertEqual(json.dumps(rows, sort_keys=True), before)


if __name__=='__main__':
    unittest.main()
