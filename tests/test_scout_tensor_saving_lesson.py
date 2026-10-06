"""The branch counterexample remains focused, bounded and advisory."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class TensorSavingBranchLessonTests(unittest.TestCase):
    def test_tensor_subclass_query_gets_the_guard_counterexample(self):
        result = lesson_suggestions(
            "Torch Tensor subclass compiler saving first branch reconstruction"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "tensor-subclass-saving-branch-reachability")
        self.assertEqual(card["status"], "counterexample")
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn("isinstance(value, torch.Tensor)", card["lesson"])
        self.assertIn("None object marker", card["lesson"])
        self.assertNotIn("qualified", result)

    def test_advice_keeps_storage_and_runtime_limits(self):
        card = lesson_suggestions(
            "Torch Tensor subclass compiler saving first branch reconstruction"
        )["matches"][0]
        self.assertIn("non-Tensor storage", card["avoid_when"])
        self.assertIn("genuine caller", card["avoid_when"])
        self.assertIn("Dynamo compilation", card["avoid_when"])
        self.assertTrue(all("8cd5e206" in item["url"] for item in card["evidence"]))


if __name__ == "__main__":
    unittest.main()
