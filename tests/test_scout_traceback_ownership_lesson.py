"""Keep the real-resource lesson reachable without overstating its scope."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import lesson_suggestions


class TracebackOwnershipLessonTests(unittest.TestCase):
    def test_socket_failure_query_retrieves_the_complete_scoped_card(self):
        result = lesson_suggestions("socket failed initialization traceback descriptor GC")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "traceback-retention-versus-resource-cleanup")
        self.assertIn("retained exception tracebacks", card["lesson"])
        self.assertIn("successful ownership transfer", card["lesson"])
        self.assertIn("not an uncollectable-leak claim", card["lesson"])
        self.assertIn("not evidence of typical production", card["avoid_when"])
        self.assertTrue(any("/discussions/1125" in e["url"] for e in card["evidence"]))
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
