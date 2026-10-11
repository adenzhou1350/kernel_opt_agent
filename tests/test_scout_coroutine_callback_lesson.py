"""Coroutine dispatch evidence stays bounded and advisory in Scout retrieval."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class CoroutineCallbackLessonTests(unittest.TestCase):
    def test_callback_dispatch_matrix_is_retrievable(self):
        result = lesson_suggestions("coroutine callback thread hints is_async partial")
        card = next(
            match
            for match in result["matches"]
            if match["id"] == "coroutine-callback-thread-hints"
        )
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("synchronous thread-identity controls", card["lesson"])
        self.assertIn("unchanged production source", card["lesson"])
        self.assertNotIn("qualified", result)

    def test_backend_and_research_limits_remain_explicit(self):
        card = lesson_suggestions("coroutine callback thread hints is_async partial")[
            "matches"
        ][0]
        self.assertEqual(card["id"], "coroutine-callback-thread-hints")
        self.assertIn("custom awaitable", card["avoid_when"])
        self.assertIn("not maintainer acceptance", card["avoid_when"])
        self.assertIn("not a prospective", card["avoid_when"])
        self.assertTrue(any(e["url"].endswith("/pull/1159") for e in card["evidence"]))


if __name__ == "__main__":
    unittest.main()
