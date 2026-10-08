"""Retrieval scope only; distributed training is tested in DeepSpeed itself."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import lesson_suggestions  # noqa: E402


class SubgroupOptionLessonTests(unittest.TestCase):
    def test_muon_mapping_advice_retains_supported_group_semantics(self):
        result = lesson_suggestions(
            "Muon ns_method sub_group_to_group_id frozen parameter group mixed methods"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "subgroup-option-origin-mapping")
        self.assertIn("instead of banning", card["lesson"])
        self.assertIn("both mixed-option orders", card["lesson"])
        self.assertIn("optimizer-wide", card["avoid_when"])
        self.assertNotIn("qualified", result)
        self.assertEqual(result["oversized_matches_omitted"], 0)

    def test_execution_coverage_is_not_declared_rank_count_coverage(self):
        card = lesson_suggestions(
            "Muon ns_method last group win subgroup original mapping"
        )["matches"][0]
        self.assertIn("before ever reaching two ranks", card["lesson"])
        self.assertIn("long training convergence", card["avoid_when"])
        self.assertTrue(
            any("not a public CI result" in x["note"] for x in card["evidence"])
        )


if __name__ == "__main__":
    unittest.main()
