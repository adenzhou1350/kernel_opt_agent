"""The narrow permission/selection counterexample stays reusable and scoped."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class TuningPermissionLessonTests(unittest.TestCase):
    def test_field_names_retrieve_advice_in_mixed_language_queries(self):
        # Development regressions from owner-reviewed historical candidates,
        # not a held-out or prospective quality/conversion measurement.
        queries = (
            "MegaMoeConfig 缺少 enable_in_kernel_fc2_reduce 与 combine_dtype 的交叉校验 config.py 共60行未截断 __post_init__ 只校验 swiglu 配对 量化 wire 要求 enable_in_kernel_fc2_reduce=False",
            'config 缺少 enable_in_kernel_fc2_reduce 与 combine_dtype 的交叉校验 apply_topk_in_fc1=True combine_dtype="bf16"',
            'MegaMoeConfig combine_dtype="nvfp4" enable_in_kernel_fc2_reduce=True 配置层静默通过 下游 shim 是否有同等校验未知',
        )
        for query in queries:
            with self.subTest(query=query):
                result = lesson_suggestions(query)
                self.assertEqual(result["status"], "ADVISORY_MATCH")
                self.assertEqual(
                    result["matches"][0]["id"], "tuning-permission-versus-selection"
                )

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
        self.assertGreaterEqual(len(lesson["evidence"]), 3)
        self.assertTrue(any("shim/tuner.py" in e["url"] for e in lesson["evidence"]))
        self.assertTrue(any("shim/nvfp4.py" in e["url"] for e in lesson["evidence"]))


if __name__ == "__main__":
    unittest.main()
