"""Frozen pilot schema controls; no provider calls or held cases."""
import json
import unittest

from scripts.scout_shadow_comparison import parse_observation_hypothesis


class ObservationHypothesisTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {0: 'public API contract', 2: 'native result: passed'}
        self.answer = {'hypothesis': {
            'public_entrypoint': 'package.public_api',
            'contract': 'A documented requirement',
            'failure': 'A falsifiable proposed violation',
            'reproduction': 'A bounded package-level reproduction',
            'evidence': [{'observation_id': 0, 'quote': 'API contract'},
                         {'observation_id': 2, 'quote': 'result: passed'}],
        }}

    def parse(self, value):
        return parse_observation_hypothesis(json.dumps(value), self.evidence)

    def test_valid_answer_and_abstention_distinct_from_invalid(self):
        self.assertEqual(self.parse(self.answer), self.answer)
        self.assertEqual(self.parse({'hypothesis': None}), {'hypothesis': None})
        for invalid in ({}, {'hypothesis': False}, [], None, {'hypothesis': None, 'reason': 'extra'}):
            with self.subTest(invalid=invalid):
                self.assertIsNone(self.parse(invalid))

    def test_duplicate_keys_rejected_at_each_level_even_when_equal(self):
        raw = json.dumps(self.answer)
        for malformed in (
            '{"hypothesis":null,"hypothesis":null}',
            raw.replace('"contract":', '"contract":"duplicate","contract":'),
            raw.replace('"observation_id": 0', '"observation_id":0,"observation_id":0'),
        ):
            self.assertIsNone(parse_observation_hypothesis(malformed, self.evidence))

    def test_unavailable_wrong_and_boolean_evidence_ids_rejected(self):
        for identifier in (1, 3, 4, -1, True, False, '0', 0.0, None):
            self.answer['hypothesis']['evidence'][0]['observation_id'] = identifier
            with self.subTest(identifier=identifier):
                self.assertIsNone(self.parse(self.answer))

    def test_quote_matches_only_named_observation_without_normalization(self):
        for literal in ('result: passed', 'api contract', '', 'API  contract', 'invented'):
            self.answer['hypothesis']['evidence'][0]['quote'] = literal
            with self.subTest(literal=literal):
                self.assertIsNone(self.parse(self.answer))

    def test_text_fields_exact_keys_types_and_limits(self):
        for key in ('public_entrypoint', 'contract', 'failure', 'reproduction'):
            old = self.answer['hypothesis'][key]
            for invalid in ('', ' \n', 'x' * 2001, '\ud800', True, 12, None, []):
                self.answer['hypothesis'][key] = invalid
                with self.subTest(key=key, invalid_type=type(invalid)):
                    self.assertIsNone(self.parse(self.answer))
            self.answer['hypothesis'][key] = 'x' * 2000
            self.assertIsNotNone(self.parse(self.answer))
            del self.answer['hypothesis'][key]
            self.assertIsNone(self.parse(self.answer))
            self.answer['hypothesis'][key] = old
        self.answer['hypothesis']['reasoning'] = 'not requested'
        self.assertIsNone(self.parse(self.answer))

    def test_one_to_four_exact_quote_objects(self):
        valid = self.answer['hypothesis']['evidence'][0]
        for quotes in ([], [valid] * 5, {}, None, [None], [{'observation_id': 0}],
                       [dict(valid, confidence=1)]):
            self.answer['hypothesis']['evidence'] = quotes
            self.assertIsNone(self.parse(self.answer))
        # Duplicate IDs/quotes are not forbidden by the frozen protocol.
        self.answer['hypothesis']['evidence'] = [valid] * 4
        self.assertIsNotNone(self.parse(self.answer))

    def test_quote_character_limit_and_exact_unicode_membership(self):
        self.evidence[2] = '测' * 1001
        self.answer['hypothesis']['evidence'] = [{'observation_id': 2, 'quote': '测' * 1000}]
        self.assertEqual(self.parse(self.answer), self.answer)
        self.answer['hypothesis']['evidence'][0]['quote'] += '测'
        self.assertIsNone(self.parse(self.answer))
        self.evidence[2] = 'cafe\u0301'
        self.answer['hypothesis']['evidence'][0]['quote'] = 'caf\u00e9'
        self.assertIsNone(self.parse(self.answer))

    def test_malformed_nonfinite_oversized_and_non_unicode_input(self):
        for raw in ('not JSON', '```json\n{"hypothesis":null}\n```',
                    '{"hypothesis":NaN}', '{"hypothesis":Infinity}',
                    '[' * 2000, ' ' * 131073, '\ud800', None, b'{}'):
            with self.subTest(raw_type=type(raw)):
                self.assertIsNone(parse_observation_hypothesis(raw, self.evidence))

    def test_bad_caller_evidence_is_not_a_model_format_failure(self):
        for invalid in ({}, {False: 'original'}, {0: None}, {0: 'original', 1: None},
                        {0: 'original', 4: 'unknown'}, {0: 'original', '2': 'result'},
                        {0: '\ud800'}, []):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_observation_hypothesis('{"hypothesis":null}', invalid)


if __name__ == '__main__':
    unittest.main()
