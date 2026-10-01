"""The narrow permission/selection counterexample stays reusable and scoped."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class TuningPermissionLessonTests(unittest.TestCase):
    def test_complete_counterexample_is_retrievable(self):
        result = lesson_suggestions(
            "enable_in_kernel_fc2_reduce tuning permission selected knobs combine wires"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        lesson = result["matches"][0]
        self.assertEqual(lesson["id"], "tuning-permission-versus-selection")
        self.assertLessEqual(
            len(json.dumps(lesson, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertEqual(lesson["status"], "counterexample")
        self.assertIn("permitted-but-unselected", lesson["lesson"])
        self.assertIn("not all knob combinations", lesson["avoid_when"])
        self.assertEqual(len(lesson["evidence"]), 3)
        self.assertTrue(any("shim/tuner.py" in e["url"] for e in lesson["evidence"]))
        self.assertTrue(any("shim/nvfp4.py" in e["url"] for e in lesson["evidence"]))


if __name__ == "__main__":
    unittest.main()
