"""Available input-ownership advice is not candidate qualification."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes  # noqa: E402
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class NormalizationOwnershipLessonTests(unittest.TestCase):
    def test_scoped_advice_is_retrievable_and_complete(self):
        result = lesson_suggestions(
            "Normalize caller-owned options without writing results back into them"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertNotIn("qualified", result)
        card = result["matches"][0]
        self.assertEqual(card["id"], "normalization-without-input-writeback")
        knowledge_notes.validate(card)
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("passing control", card["lesson"])
        self.assertIn("native operation", card["lesson"])

    def test_copy_scope_and_native_evidence_limits_survive_retrieval(self):
        card = lesson_suggestions(
            "caller-owned options normalization frozen nested storage maps reused"
        )["matches"][0]
        self.assertEqual(card["id"], "normalization-without-input-writeback")
        self.assertIn("shallow object spread", card["avoid_when"])
        self.assertIn("in-place builder", card["avoid_when"])
        self.assertIn("current-head native-build", card["avoid_when"])
        self.assertTrue(
            all(item["url"].startswith("https://") for item in card["evidence"])
        )
        self.assertIn(
            "https://pkg.go.dev/net/http#RoundTripper",
            [item["url"] for item in card["evidence"]],
        )
        lancedb = next(
            item
            for item in card["evidence"]
            if item["url"] == "https://github.com/lancedb/lancedb/pull/4480"
        )
        self.assertIn("no current-head Rust/native rebuild", lancedb["note"])

    def test_humming_copy_counterexample_is_available_at_the_source_path(self):
        result = lesson_suggestions(
            "Humming allow_fallback pop shared input config mutation",
            source_urls=[
                "https://raw.githubusercontent.com/vllm-project/vllm/"
                "dde9aca41cd3ccceb1ffa902933b6678a09c83ce/"
                "vllm/model_executor/layers/quantization/humming.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "normalization-without-input-writeback")
        self.assertTrue(result["source_path_match"])
        self.assertIn("returned copy", card["avoid_when"])
        self.assertIn("nested mutable values", card["avoid_when"])
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertTrue(
            any(
                "not GPU/model or cache-lifecycle qualification" in item["note"]
                for item in card["evidence"]
            )
        )
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
