"""Scoped source advice is retrievable without implying runtime qualification."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class AsyncInputLessonTests(unittest.TestCase):
    def card(self):
        result = lesson_suggestions('async submit in-place tensor masking CPU worker copy stream')
        self.assertEqual(result['status'], 'ADVISORY_MATCH')
        self.assertNotIn('qualified', result)
        return next(card for card in result['matches']
                    if card['id'] == 'async-input-copy-consumer-order')

    def test_copy_consumer_advice_is_bounded(self):
        card = self.card()
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn('pinned CPU buffers', card['lesson'])
        self.assertIn('ownership contract', card['lesson'])

    def test_runtime_and_wrong_stream_counterconditions_remain(self):
        card = self.card()
        self.assertIn('Not a native KT correctness result', card['avoid_when'])
        self.assertIn('different copy/mutation streams', card['avoid_when'])
        self.assertIn('buffer reuse', card['avoid_when'])
        self.assertTrue(all(item['url'].startswith('https://') for item in card['evidence']))


if __name__ == '__main__':
    unittest.main()
