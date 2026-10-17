"""Offline coordinator tests; fake adapters are not prospective study cases."""
import json
import unittest

from scripts.scout_observation_pilot import ARMS, StudyBudget, run_case


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events, self.requests, self.reads = [], [], []
        self.budget = StudyBudget()
        self.menu = {i: dict(label=f'action {i}', available=True, reason='') for i in (1, 2, 3)}
        self.fingerprints = dict(glm='a' * 64, m3='b' * 64)
        self.select = [1, 2]

    def invoke(self, provider, prompt, *, max_output_tokens, timeout_seconds):
        self.assertEqual(self.events[-1]['event'], 'call_started')
        self.assertEqual(self.events[-1]['prompt'], prompt)
        self.assertLessEqual(timeout_seconds, 90)
        self.requests.append(dict(provider=provider, prompt=prompt, cap=max_output_tokens,
                                  timeout=timeout_seconds))
        self.clock.value += 1
        if max_output_tokens == 1024:
            data = json.loads(prompt.split('\n', 1)[1])
            action = self.select[min(len(data['used_ids']), len(self.select) - 1)]
            text = json.dumps(dict(action_id=action))
        else:
            text = '{"hypothesis":null}'
        return dict(response=dict(ok=True, text=text), normalized_total_tokens=10)

    def acquire(self, identifier, *, timeout_seconds):
        self.assertEqual(self.events[-1]['event'], 'observation_started')
        self.assertLessEqual(timeout_seconds, 60)
        self.reads.append(identifier)
        self.clock.value += 2
        return dict(status='ACQUIRED', text=f'observation {identifier}')

    def run_case(self, **kwargs):
        values = dict(case_id='fake-case', packet_text='original public packet', menu=self.menu,
                      case_index=0, provider_fingerprints=self.fingerprints,
                      invoke=self.invoke, acquire=self.acquire, journal=self.events.append,
                      budget=self.budget, clock=self.clock)
        values.update(kwargs)
        return run_case(**values)

    def test_six_arms_ten_calls_rotated_and_distinct_observations(self):
        result = self.run_case(case_index=2)
        self.assertEqual([a['arm'] for a in result['arms']], list(ARMS[2:] + ARMS[:2]))
        self.assertEqual(len(self.requests), 10)
        self.assertEqual(self.budget.attempts, 10)
        self.assertEqual(self.budget.known_tokens, 100)
        self.assertEqual([r['cap'] for r in self.requests].count(2048), 6)
        arms = {a['arm']: a for a in result['arms']}
        self.assertEqual(arms['source_only']['observations'], [])
        self.assertEqual(arms['rule']['observations'][0]['observation_id'], 2)
        self.assertEqual(arms['fixed_native']['observations'][0]['observation_id'], 3)
        self.assertEqual([o['observation_id'] for o in arms['glm_sequential']['observations']], [1, 2])
        self.assertTrue(all(a['valid_review'] for a in result['arms']))
        self.assertFalse(result['correctness_adjudicated'])
        self.assertEqual(self.events[0]['event'], 'case_started')
        self.assertEqual(self.events[-1]['event'], 'case_finished')

    def test_unavailable_native_retains_slot_without_acquire_or_fallback(self):
        self.menu[3].update(available=False, reason='native package absent')
        result = self.run_case()
        native = next(a for a in result['arms'] if a['arm'] == 'fixed_native')
        self.assertNotIn(3, self.reads)
        self.assertEqual(native['observations'], [dict(status='UNAVAILABLE',
            text='native package absent', observation_id=3)])
        self.assertTrue(native['valid_review'])

    def test_rule_uses_continuation_if_companion_test_unavailable(self):
        self.menu[2].update(available=False, reason='no companion test')
        result = self.run_case()
        rule = next(a for a in result['arms'] if a['arm'] == 'rule')
        self.assertEqual(rule['observations'][0]['observation_id'], 1)

    def test_selector_stop_still_has_one_common_review(self):
        self.select = [0]
        result = self.run_case()
        sequential = next(a for a in result['arms'] if a['arm'] == 'glm_sequential')
        self.assertEqual(len(sequential['calls']), 2)
        self.assertEqual(sequential['acquisition_stop'], 'SELECTED_STOP')
        self.assertEqual(sequential['observations'], [])
        self.assertTrue(sequential['valid_review'])

    def test_repeated_choice_stops_without_repeated_acquisition(self):
        self.select = [1]
        result = self.run_case()
        sequential = next(a for a in result['arms'] if a['arm'] == 'glm_sequential')
        self.assertEqual(len(sequential['observations']), 1)
        self.assertEqual(sequential['acquisition_stop'], 'INVALID_OR_REPEATED_SELECTION')
        self.assertTrue(sequential['valid_review'])

    def test_invalid_choice_not_repaired_or_retried(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            if limits['max_output_tokens'] == 1024:
                record['response']['text'] = '{"action_id":true,"reason":"guess"}'
            return record
        result = self.run_case(invoke=invoke)
        self.assertEqual(len(self.requests), 9)
        self.assertEqual(self.reads, [2, 3])
        self.assertTrue(all(a['valid_review'] for a in result['arms']))

    def test_unknown_usage_stops_case_even_with_valid_text(self):
        for usage in (None, True, -1, '10'):
            with self.subTest(usage=usage):
                self.setUp()
                def invoke(provider, prompt, **limits):
                    record = self.invoke(provider, prompt, **limits)
                    record['normalized_total_tokens'] = usage
                    return record
                result = self.run_case(invoke=invoke)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.reads, [])
                self.assertTrue(result['case_usage_unknown'])
                self.assertEqual(result['study_unknown_usage_records'], 1)
                self.assertEqual(len(result['arms']), 6)

    def test_known_usage_survives_incomplete_answer(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            record['response'] = dict(ok=False, error='incomplete_response')
            return record
        result = self.run_case(invoke=invoke)
        self.assertEqual(self.budget.known_tokens, 90)
        self.assertFalse(result['case_usage_unknown'])
        self.assertTrue(all(not a['valid_review'] for a in result['arms']))

    def test_partial_usage_lower_bound_retained_without_becoming_complete(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            record.update(normalized_total_tokens=None, reported_token_lower_bound=7,
                          usage=dict(input_tokens=7))
            return record
        result = self.run_case(invoke=invoke)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(result['case_usage_unknown'])
        self.assertEqual(result['study_known_token_lower_bound'], 7)
        restored = StudyBudget.from_events(self.events)
        self.assertEqual(restored.known_tokens, 7)
        self.assertEqual(restored.unknown_usage_records, 1)

    def test_post_call_token_stop_keeps_actual_overshoot(self):
        self.budget.known_tokens = 149995
        result = self.run_case()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result['study_known_token_lower_bound'], 150005)
        self.assertTrue(result['study_budget_stopped'])
        self.assertEqual(self.reads, [])

    def test_attempt_ceiling_no_acquisition_or_calls_after_limit(self):
        self.budget.attempts = 40
        result = self.run_case()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.reads, [])
        self.assertEqual(len(result['arms']), 6)

    def test_no_call_when_request_journal_fails(self):
        def journal(event):
            self.events.append(event)
            if event['event'] == 'call_started':
                raise OSError('disk full')
        with self.assertRaises(OSError):
            self.run_case(journal=journal)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.budget.attempts, 0)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.run_case()  # Crash cannot implicitly replay the case.

    def test_prompt_overflow_retains_six_uncalled_slots(self):
        result = self.run_case(packet_text='x' * 16000)
        self.assertEqual(self.requests, [])
        self.assertEqual(len(result['arms']), 6)
        self.assertTrue(all(not a['review_attempted'] for a in result['arms']))

    def test_reserve_review_time_before_second_selector(self):
        selections = 0
        def invoke(provider, prompt, **limits):
            nonlocal selections
            record = self.invoke(provider, prompt, **limits)
            if (self.events[-1]['arm'] == 'glm_sequential'
                    and limits['max_output_tokens'] == 1024):
                selections += 1
                self.clock.value += (88 if selections == 1
                                     else limits['timeout_seconds'] - 1)
            return record
        def acquire(identifier, **limits):
            result = self.acquire(identifier, **limits)
            self.clock.value += min(57, limits['timeout_seconds'] - 2)
            return result
        result = self.run_case(invoke=invoke, acquire=acquire)
        sequential = result['arms'][-1]
        self.assertEqual(len(sequential['observations']), 1)
        self.assertEqual(sequential['acquisition_stop'], 'REVIEW_TIME_RESERVED')
        self.assertEqual(sequential['calls'][-1]['output_cap'], 2048)
        self.assertEqual(self.requests[-2]['timeout'], 62)
        self.assertEqual(self.requests[-1]['timeout'], 90)
        self.assertTrue(sequential['review_attempted'])

    def test_no_cross_arm_or_selector_text_in_common_review(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            if limits['max_output_tokens'] == 2048:
                record['response']['text'] = 'OTHER_ARM_SECRET'
            else:
                # Extra prose makes this invalid; it must not enter review.
                record['response']['text'] += ' SELECTOR_SECRET'
            return record
        self.run_case(invoke=invoke)
        for request in self.requests:
            self.assertNotIn('OTHER_ARM_SECRET', request['prompt'])
            self.assertNotIn('SELECTOR_SECRET', request['prompt'])

    def test_oversize_observation_becomes_failure_not_clipped_success(self):
        result = self.run_case(acquire=lambda identifier, **limits:
                               dict(status='ACQUIRED', text='x' * 4501))
        for arm in result['arms']:
            for observation in arm['observations']:
                self.assertEqual(observation['status'], 'FAILED')
                self.assertEqual(observation['text'], 'OBSERVATION_LIMIT_OR_ENCODING_FAILURE')

    def test_adapter_exception_keeps_attempt_and_stops_unknown_usage(self):
        def invoke(*args, **kwargs):
            raise TimeoutError('private endpoint and secret must not be retained')
        result = self.run_case(invoke=invoke)
        self.assertEqual(result['study_attempts'], 1)
        record = result['arms'][0]['calls'][0]
        self.assertEqual(record['response']['error'], 'TimeoutError')
        self.assertNotIn('private endpoint', json.dumps(result))

    def test_reject_answer_bearing_menu_before_dispatch(self):
        self.menu[1]['text'] = 'hidden oracle answer'
        with self.assertRaises(ValueError):
            self.run_case()
        self.assertEqual(self.events, [])
        self.assertEqual(self.requests, [])

    def test_literal_evidence_is_from_this_arm_only(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            if limits['max_output_tokens'] == 2048:
                record['response']['text'] = json.dumps(dict(hypothesis=dict(
                    public_entrypoint='package.call', contract='documented contract',
                    failure='falsifiable failure', reproduction='native check',
                    evidence=[dict(observation_id=3, quote='observation 3')]
                )))
            return record
        result = self.run_case(invoke=invoke)
        accepted = [a['arm'] for a in result['arms'] if a['valid_review']]
        self.assertEqual(accepted, ['fixed_native'])

    def test_restored_journal_preserves_costs_and_forbids_case_replay(self):
        self.run_case()
        restored = StudyBudget.from_events(self.events)
        self.assertEqual(restored.attempts, 10)
        self.assertEqual(restored.known_tokens, 100)
        self.assertEqual(restored.case_ids, {'fake-case'})
        self.assertFalse(restored.stopped)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.run_case(budget=restored)

    def test_unfinished_journal_start_is_uncertain_not_retry_permission(self):
        events = [dict(event='case_started', case_id='old-case'),
                  dict(event='call_started', case_id='old-case', attempt_id='old:0')]
        restored = StudyBudget.from_events(events)
        self.assertEqual(restored.unsettled_attempts, {'old:0'})
        self.assertTrue(restored.stopped)
        result = self.run_case(budget=restored)
        self.assertEqual(self.requests, [])
        self.assertEqual(result['study_attempts'], 1)

    def test_duplicate_or_unbound_journal_records_rejected(self):
        self.run_case()
        for extra in (self.events[0], self.events[1], self.events[2]):
            with self.subTest(event=extra['event']):
                with self.assertRaises(ValueError):
                    StudyBudget.from_events([*self.events, extra])
        with self.assertRaises(ValueError):
            StudyBudget.from_events([dict(event='call_finished', record={})])

    def test_late_model_answer_not_accepted_but_tokens_retained(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            self.clock.value += limits['timeout_seconds']
            return record
        result = self.run_case(invoke=invoke)
        self.assertTrue(all(not a['valid_review'] for a in result['arms']))
        self.assertTrue(all(a['adapter_time_limit_exceeded'] for a in result['arms']))
        self.assertEqual(self.budget.known_tokens, 60)

    def test_adapter_cannot_mutate_the_frozen_menu(self):
        def invoke(provider, prompt, **limits):
            record = self.invoke(provider, prompt, **limits)
            self.menu[3].update(available=False, reason='changed after freeze')
            return record
        result = self.run_case(invoke=invoke)
        native = next(a for a in result['arms'] if a['arm'] == 'fixed_native')
        self.assertEqual(native['observations'][0]['status'], 'ACQUIRED')

    def test_observation_limit_includes_delivered_metadata(self):
        result = self.run_case(acquire=lambda identifier, **limits:
                               dict(status='ACQUIRED', text='x' * 4500))
        for arm in result['arms']:
            self.assertTrue(all(o['status'] == 'FAILED' for o in arm['observations']))


if __name__ == '__main__':
    unittest.main()
