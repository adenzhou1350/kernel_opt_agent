"""Small default lessons must remain available within Scout's existing budget."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes  # noqa: E402
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class DefaultKnowledgeBudgetTests(unittest.TestCase):
    def test_cutlass_array_advice_uses_receiver_contract_not_python_list_semantics(self):
        result = lesson_suggestions("CUTLASS Array slice vector start count")
        card = result["matches"][0]
        self.assertEqual(card["id"], "native-binding-semantics-before-field-inference")
        self.assertIn("arr[start:count]", card["lesson"])
        self.assertIn("nonzero offset", card["lesson"])
        self.assertIn("receiver's construction", card["lesson"])
        self.assertTrue(any("not an installed dependency or GPU-kernel test" in item["note"]
                            for item in card["evidence"]))
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_backend_state_advice_keeps_reference_and_native_scopes_distinct(self):
        result = lesson_suggestions(
            "backend conv_state cache update missing tuple return assignment mutation"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "backend-state-mutation-contract")
        self.assertIn("dependency version", card["lesson"])
        self.assertIn("state alias", card["lesson"])
        self.assertIn("do not prove native CUDA", card["avoid_when"])
        self.assertIn("Reopen", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_mode_advice_preserves_the_warmup_transition_and_limits(self):
        result = lesson_suggestions(
            "training no-grad inference-mode warmup checkpoint policy memory budget"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "training-and-grad-mode-dispatch")
        self.assertIn("grad-enabled training", card["lesson"])
        self.assertIn("explicit", card["lesson"])
        self.assertIn("measured memory-budget", card["avoid_when"])
        self.assertNotIn("qualified", result)

    def test_default_cards_fit_the_existing_advisory_budget(self):
        for path in knowledge_notes.DEFAULT_DIRECTORY.glob("*.json"):
            with self.subTest(card=path.name):
                card = json.loads(path.read_text(encoding="utf-8"))
                self.assertLessEqual(
                    len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
                )

    def test_configuration_advice_retains_its_contract_and_scope(self):
        result = lesson_suggestions("configuration CLI parser plugin consumer backend")
        card = result["matches"][0]
        self.assertEqual(card["id"], "consumer-contract-before-regression")
        self.assertEqual(card["status"], "counterexample")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertIn("supported caller", card["lesson"])
        self.assertIn("External or dynamic callers", card["avoid_when"])

    def test_native_guard_advice_distinguishes_storage_and_logical_region(self):
        result = lesson_suggestions(
            "torch.as_strided raw capacity out of bounds storage view validation"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "native-operation-inherited-guards")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("logical subregion", card["avoid_when"])
        self.assertIn("meta/symbolic", card["avoid_when"])
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
