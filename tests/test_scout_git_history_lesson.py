"""Keep partial-object and shallow-history cautions usable by the real reader."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import knowledge_notes  # noqa: E402
from scout_lesson_context import lesson_suggestions  # noqa: E402


class GitHistoryLessonTests(unittest.TestCase):
    def test_shallow_history_advice_is_complete_not_a_global_unshallow_gate(self):
        result = lesson_suggestions('shallow clone first-parent nonmerge missing ancestry history')
        self.assertEqual(result['status'], 'ADVISORY_MATCH')
        card = result['matches'][0]
        self.assertEqual(card['id'], 'partial-clone-query-fetch-budget')
        self.assertIn('--is-shallow-repository', card['lesson'])
        self.assertIn('cannot recover absent ancestry', card['lesson'])
        self.assertIn('Do not require unshallowing every repository', card['avoid_when'])
        self.assertIn("not a frozen sample's outcomes", card['avoid_when'])
        self.assertTrue(any(e['url'] == 'https://git-scm.com/docs/shallow'
                            for e in card['evidence']))
        self.assertEqual(result['oversized_matches_omitted'], 0)
        self.assertLessEqual(len(json.dumps(card).encode()), 8192)

    def test_existing_partial_object_commands_and_cost_limits_are_retained(self):
        card = knowledge_notes.read_card(ROOT / 'knowledge/lessons/partial-clone-query-fetch-budget.json')
        self.assertIn('--no-lazy-fetch', card['lesson'])
        self.assertIn('GIT_NO_LAZY_FETCH=1', card['lesson'])
        self.assertIn('charge setup cost', card['lesson'])
        self.assertIn('lower total cost/greater PR yield', card['avoid_when'])
        self.assertEqual(card['status'], 'validated')


if __name__ == '__main__':
    unittest.main()
