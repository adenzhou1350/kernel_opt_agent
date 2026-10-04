"""Scoped cache residency evidence is advisory, not a candidate verdict."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class HybridCacheLessonTests(unittest.TestCase):
    def test_hybrid_cache_query_preserves_consumer_and_test_limits(self):
        result = lesson_suggestions(
            "hybrid cache offload prefetch conv recurrent states sliding"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "hybrid-cache-consumer-residency")
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("only KV", card["lesson"])
        self.assertIn("different cache", card["avoid_when"])
        self.assertIn("asynchronous race freedom", card["avoid_when"])
        self.assertIn("de3cc934", card["evidence"][0]["url"])
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
