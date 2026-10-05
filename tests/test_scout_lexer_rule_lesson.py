"""A scoped lexical lesson stays intact, advisory and findable by real queries."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class LexerRuleLessonTests(unittest.TestCase):
    def test_native_tokenization_queries_find_the_scoped_card(self):
        for query in (
            "lexer tokenizer rule precedence keyword function dotted identifiers",
            "sqlparse JOIN parenthesis subquery function name lookahead",
            "first-match regex lexer whitespace clause keyword",
        ):
            with self.subTest(query=query):
                result = lesson_suggestions(query)
                self.assertEqual(result["status"], "ADVISORY_MATCH")
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertEqual(len(result["matches"]), 1)
                card = result["matches"][0]
                self.assertEqual(card["id"], "lexer-rule-precedence-with-identifier-controls")
                self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
                self.assertNotIn("qualified", result)

    def test_lesson_keeps_negative_controls_and_acceptance_boundary(self):
        path = knowledge_notes.DEFAULT_DIRECTORY / "lexer-rule-precedence-with-identifier-controls.json"
        card = knowledge_notes.read_card(path)
        self.assertIn("dotted-name guards", card["lesson"])
        self.assertIn("ordinary function names", card["lesson"])
        self.assertIn("ANY/UNNEST", card["avoid_when"])
        self.assertIn("non-validating", card["avoid_when"])
        evidence = next(item for item in card["evidence"] if item["url"].endswith("/pull/919"))
        self.assertIn("unchanged baseline fails 2", evidence["note"])
        self.assertIn("not maintainer acceptance", evidence["note"])


if __name__ == "__main__":
    unittest.main()
