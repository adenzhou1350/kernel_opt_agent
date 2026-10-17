"""Ensure native ownership advice is actually available to Scout, not a gate."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class BorrowedStreamLessonTests(unittest.TestCase):
    def test_zip_source_retrieves_the_cross_platform_ownership_counterexample(self):
        result = lesson_suggestions("ZipFileSystem close __exit__", source_urls=[
            "https://raw.githubusercontent.com/fsspec/filesystem_spec/"
            "b7505a613a6901d6f9c3df0c5147908de38c4a9e/fsspec/implementations/zip.py"])
        self.assertEqual(result["matches"][0]["id"],
                         "borrowed-stream-versus-acquired-transport")
        self.assertTrue(result["source_path_match"])
        notes = " ".join(item["note"] for item in result["matches"][0]["evidence"])
        self.assertIn("Linux CPython3.12", notes)
        self.assertIn("49-test ZIP suite", notes)
        self.assertIn("arbitrary context-manager qualification", notes)

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
