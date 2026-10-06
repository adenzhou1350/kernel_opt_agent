"""Scoped budget-unit knowledge must remain available without a verdict."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class BudgetUnitsLessonTests(unittest.TestCase):
    def test_fractional_gb_budget_counterexample_is_retrievable_and_scoped(self):
        result = lesson_suggestions(
            "host_size hicache_size fractional GB budget integer allocation geometry"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "resource-budget-units-before-geometry")
        self.assertEqual(card["status"], "counterexample")
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("ratio-based sizing", card["lesson"])
        self.assertIn("aggregate over-budget", card["avoid_when"])
        self.assertIn("not native SGLang", card["avoid_when"])
        self.assertIn("does not establish", result["caution"])
        self.assertNotIn("qualified", result)
        self.assertTrue(all("60878c3f" in item["url"] for item in card["evidence"]))


if __name__ == "__main__":
    unittest.main()
