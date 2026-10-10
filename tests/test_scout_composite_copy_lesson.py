"""Composite copy advice must not be replaced by a DSL slice counterexample."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import lesson_suggestions  # noqa: E402


class CompositeCopyLessonTests(unittest.TestCase):
    def test_real_receiver_contract_is_available_with_source_only_scope(self):
        for query in (
            "DSAFlashMLAMetadata num_splits composite slice copy_",
            "SGLang companion tensor metadata copy_ missing field",
            "composite slice copy_ receiver tensor mock",
        ):
            with self.subTest(query=query):
                result = lesson_suggestions(query)
                card = result["matches"][0]
                self.assertEqual(card["id"], "composite-object-slice-copy-contract")
                self.assertIn("composite object's slice/copy_", card["lesson"])
                self.assertIn("copy_ copies both", card["evidence"][0]["note"])
                self.assertIn("not FlashMLA device", card["evidence"][0]["note"])
                self.assertIn("Other composite objects", card["avoid_when"])
                self.assertLess(len(json.dumps(card).encode()), 2500)
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertNotIn("qualified", result)

    def test_dsl_slice_and_multimodal_count_advice_are_not_displaced(self):
        for query, expected in (
            (
                "CUTLASS Array slice vector start count",
                "cutlass-array-vector-slice-count",
            ),
            (
                "multimodal _item_overlap embedding cache chunk slicing full token count",
                "whole-item-count-before-chunk-slicing",
            ),
            (
                "TVM Range Pipelined constructor FromMinExtent",
                "native-binding-semantics-before-field-inference",
            ),
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    lesson_suggestions(query)["matches"][0]["id"], expected
                )


if __name__ == "__main__":
    unittest.main()
