"""Advice retrieval is not a model or live transport qualification."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class CLIInputLessonTests(unittest.TestCase):
    def test_exact_mode_warning_is_retrievable(self):
        result = lesson_suggestions('CLI Windows messages-file stdin input preflight')
        card = result['matches'][0]
        self.assertEqual(card['id'], 'preflight-exact-cli-input-mode')
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn('unseen cases', card['lesson'])
        self.assertIn('Matching output/call caps', card['avoid_when'])

    def test_no_new_upstream_or_model_quality_claim(self):
        card = json.loads((knowledge_notes.DEFAULT_DIRECTORY /
                           'preflight-exact-cli-input-mode.json').read_text())
        self.assertIn('existing author-owned work', card['evidence'][0]['note'])
        self.assertIn('local adapter failed', card['avoid_when'])


if __name__ == '__main__':
    unittest.main()
