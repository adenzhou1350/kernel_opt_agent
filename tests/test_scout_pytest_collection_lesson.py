"""Advisory knowledge availability; not model efficacy or target-suite proof."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class PytestCollectionLessonTests(unittest.TestCase):
    def test_query_keeps_joint_collection_caution_within_budget(self):
        result = lesson_suggestions(
            'pytest non-package test module basenames joint collection import modes',
        )
        self.assertEqual(result['status'], 'ADVISORY_MATCH')
        card = result['matches'][0]
        self.assertEqual(card['id'], 'check-imported-source')
        self.assertIn('fail joint collection', card['lesson'])
        self.assertIn("repository's import mode", card['lesson'])
        self.assertIn('same-commit pure-Python shim', card['avoid_when'])
        self.assertTrue(any('pytest.org' in item['url'] for item in card['evidence']))
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)


if __name__ == '__main__':
    unittest.main()
