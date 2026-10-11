"""Keep the validated call-binding lesson small, retrievable and scoped."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class PosonlyDefaultLessonTests(unittest.TestCase):
    def test_parameter_kind_and_gap_queries_retrieve_complete_advice(self):
        for query in (
            "Pluggy positional-only default hook wrapper TypeError",
            "default presence parameter kind positional keyword gaps",
        ):
            with self.subTest(query=query):
                result = lesson_suggestions(query)
                card = result["matches"][0]
                self.assertEqual(card["id"], "default-presence-is-not-parameter-kind")
                self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertIn("trailing omitted defaults implicit", card["lesson"])
                self.assertIn("maintainer acceptance", card["avoid_when"])
                self.assertTrue(any("/issues/774" in e["url"] for e in card["evidence"]))
                self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
