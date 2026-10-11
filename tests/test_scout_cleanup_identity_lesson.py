"""Identity-loss advice is retrievable without excusing all resource leaks."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class CleanupIdentityLessonTests(unittest.TestCase):
    def test_rebound_root_and_reused_descriptor_find_one_scoped_counterexample(self):
        for query in (
            "recursive cleanup replaced root INSTALL_BASE_CHANGED rollback",
            "filelock fork reused fd unknown device inode descriptor identity",
        ):
            with self.subTest(query=query):
                result = lesson_suggestions(query)
                self.assertEqual(result["status"], "ADVISORY_MATCH")
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertEqual(len(result["matches"]), 1)
                card = result["matches"][0]
                self.assertEqual(card["id"], "cleanup-after-ownership-loss")
                self.assertEqual(card["status"], "counterexample")
                self.assertLessEqual(
                    len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
                )
                self.assertIn(
                    "first retries unverified descriptor identities", card["lesson"]
                )
                self.assertIn("normal owned cleanup", card["lesson"])
                self.assertIn(
                    "seven selected Linux CPython fork cases", card["avoid_when"]
                )
                self.assertIn("source/test inspection only", card["avoid_when"])
                self.assertIn(
                    "Retained resources can still have operational costs",
                    card["avoid_when"],
                )
                self.assertNotIn("qualified", result)

    def test_late_owned_arrivals_still_retrieve_their_cleanup_obligation(self):
        result = lesson_suggestions("fd receiver timeout SCM_RIGHTS ownership")
        self.assertEqual(
            result["matches"][0]["id"], "timed-out-receivers-retain-fd-ownership"
        )

    def test_async_cache_replacement_reuses_identity_advice_not_duplicate_credit(self):
        result = lesson_suggestions(
            "async cache callback old task same key replacement invalidation TTL"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "cleanup-after-ownership-loss")
        self.assertIn("not a new contribution", card["avoid_when"])
        self.assertIn("cross-thread or distributed", card["avoid_when"])
        evidence = [item for item in card["evidence"] if "async-lru" in item["url"]]
        self.assertEqual(len(evidence), 2)
        self.assertTrue(any("prematurely start" in item["note"] for item in evidence))
        self.assertTrue(any("No competing PR" in item["note"] for item in evidence))
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
