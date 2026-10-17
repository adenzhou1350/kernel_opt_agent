"""Scoped advice retrieval, not replaying or improving frozen model predictions."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class IntegerValidationLessonTests(unittest.TestCase):
    def test_exact_source_keeps_range_guard_and_duplicate_boundary(self):
        result = lesson_suggestions(
            'ordinal integer float finiteness validation OverflowError',
            source_urls=['https://github.com/python-humanize/humanize/blob/'
                         '785e5dcc0d0308ad0dff3f6cc0faa7085ad0375b/src/humanize/number.py'],
        )
        self.assertEqual(result['status'], 'ADVISORY_MATCH')
        card = result['matches'][0]
        self.assertEqual(card['id'], 'intermediate-range-before-reassociation')
        self.assertIn('finiteness guard', card['lesson'])
        self.assertIn('NaN/infinity', card['lesson'])
        self.assertIn('not a novel Scout discovery', card['avoid_when'])
        self.assertIn('population recall', card['avoid_when'])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)


if __name__ == '__main__':
    unittest.main()
