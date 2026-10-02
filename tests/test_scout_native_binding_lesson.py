"""Scoped binding evidence stays retrievable without enlarging prompt budgets."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class NativeBindingLessonTests(unittest.TestCase):
    def test_existing_configuration_counterexample_is_retrievable_again(self):
        result = lesson_suggestions("configuration CLI parser plugin consumer backend")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "consumer-contract-before-regression")
        self.assertTrue(
            any("/arg_groups/fields/exec_.py" in e["url"] for e in card["evidence"])
        )

    def test_range_constructor_counterexample_is_complete_and_advisory(self):
        result = lesson_suggestions("TVM Range Pipelined constructor FromMinExtent")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "native-binding-semantics-before-field-inference")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("extent=end-begin", card["lesson"])
        self.assertIn("later pipeline lowering or GPU execution", card["avoid_when"])
        self.assertTrue(
            any("/src/ir/expr.cc#L194-L195" in e["url"] for e in card["evidence"])
        )
        self.assertNotIn("qualified", result)

    def test_tma_encoding_advice_does_not_qualify_generated_kernels(self):
        result = lesson_suggestions(
            "cuTensorMapEncodeTiled boxDim globalDim TMA descriptor"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(
            card["id"], "native-binding-semantics-before-field-inference"
        )
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("native descriptor-only call", card["lesson"])
        self.assertIn("Descriptor acceptance does not prove", card["avoid_when"])
        self.assertIn(
            "other generated variants or target architectures", card["avoid_when"]
        )
        self.assertTrue(
            any(
                "cuda/archive/13.0.1/cuda-driver-api" in e["url"]
                for e in card["evidence"]
            )
        )
        self.assertNotIn("qualified", result)

    def test_split_retains_existing_api_specific_evidence(self):
        root = Path(__file__).resolve().parents[1] / "knowledge" / "lessons"
        card = json.loads(
            (root / "native-binding-semantics-before-field-inference.json").read_text(
                encoding="utf-8"
            )
        )
        urls = [e["url"] for e in card["evidence"]]
        for fragment in (
            "/tile-ai/tilelang/pull/3382",
            "/tilelang/language/customize.py",
            "/prototype/attention/shared_utils/attention.py",
            "/test/prototype/attention/test_rope_fusion_detection.py",
            "/flashinfer/utils.py",
            "/TensorAdvancedIndexing.cpp",
            "/inference/contexts/fused_kv_append_kernel.py",
        ):
            self.assertEqual(sum(fragment in url for url in urls), 1, fragment)
        consumer = json.loads(
            (root / "consumer-contract-before-regression.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertLessEqual(
            len(json.dumps(consumer, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertFalse(set(urls) & {e["url"] for e in consumer["evidence"]})


if __name__ == "__main__":
    unittest.main()
