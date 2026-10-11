"""Ensure native ownership advice is actually available to Scout, not a gate."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class BorrowedStreamLessonTests(unittest.TestCase):
    def test_tls_ownership_advice_is_retrieved_with_counterconditions(self):
        result = lesson_suggestions("TLSStream wrap handshake borrowed transport acquired TLSConnectable")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "borrowed-stream-versus-acquired-transport")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("existing transport", card["lesson"])
        self.assertIn("BaseException", card["lesson"])
        self.assertIn("ClientHello", card["lesson"])
        self.assertIn("explicitly transfer ownership", card["avoid_when"])
        self.assertIn("not an automatic no-bug verdict", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn("does not establish", result["caution"])


if __name__ == "__main__":
    unittest.main()
