"""Planner/launch-plan distinction is scoped advice, not a defect verdict."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class PlannerEstimateLessonTests(unittest.TestCase):
    def test_reuse_existing_selection_card_with_execution_countercondition(self):
        result = lesson_suggestions("Cake sampling _launch_is_two_kernels _launch_plan one_launch vocabulary cost prediction")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "tuning-permission-versus-selection")
        self.assertIn("stage 2/3", card["lesson"])
        self.assertIn("rank variants poorly", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
