"""The KDA counterexample is available advice, not kernel qualification."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import knowledge_notes as notes  # noqa: E402


class KernelDistributionLessonTests(unittest.TestCase):
    def test_distribution_shortcut_advice_is_retrievable_and_scoped(self):
        for query in (
            "hardcoded normalization random input distribution",
            "cu_seqlens packed boundaries recurrent history truncation",
        ):
            with self.subTest(query=query):
                result = notes.search(query, limit=1)
                card = result["matches"][0]["card"]
                self.assertEqual(card["id"], "test-distribution-is-not-contract")
                self.assertEqual(card["status"], "counterexample")
                self.assertLessEqual(len(json.dumps(card).encode()), 8192)
                self.assertIn("documented specialization", card["avoid_when"])
                self.assertIn(
                    "not independently reproduced", card["evidence"][0]["note"]
                )
                self.assertIn("Advisory", result["caution"])


if __name__ == "__main__":
    unittest.main()
