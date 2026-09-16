"""Check the small public library's editing and retrieval boundaries."""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import knowledge_notes as notes  # noqa: E402


class KnowledgeNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "lessons"
        self.card = {
            "id": "graph-overhead",
            "title": "Graph launch overhead",
            "applies_when": "Measuring graph replay.",
            "lesson": "Measure the production execution mode.",
            "avoid_when": "Only eager execution is used.",
            "evidence": [
                {"url": "https://docs.python.org/3/", "note": "Context only."}
            ],
            "status": "hypothesis",
        }

    def write_card(self, card):
        self.directory.mkdir(exist_ok=True)
        path = self.directory / (card["id"] + ".json")
        path.write_text(json.dumps(card), encoding="utf-8")
        return path

    def test_add_exact_repeat_and_explicit_update(self):
        result = notes.add_note(self.card, self.directory)
        path = Path(result["source"])
        original = path.read_bytes()
        original_time = path.stat().st_mtime_ns
        self.assertEqual(
            "unchanged", notes.add_note(self.card, self.directory)["action"]
        )
        self.assertEqual(original_time, path.stat().st_mtime_ns)
        changed = dict(self.card, status="validated")
        with self.assertRaisesRegex(ValueError, "--replace"):
            notes.add_note(changed, self.directory)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(
            "replaced", notes.add_note(changed, self.directory, replace=True)["action"]
        )
        self.assertEqual("validated", notes.read_card(path)["status"])

    def test_cross_id_title_or_content_duplicates_do_not_write(self):
        notes.add_note(self.card, self.directory)
        variants = [
            dict(
                self.card,
                id="other-title",
                title=" GRAPH: launch overhead! ",
                lesson="Changed lesson.",
            ),
            dict(
                self.card,
                id="other-content",
                title="Another title",
                lesson="MEASURE the production execution mode!",
            ),
        ]
        for variant in variants:
            with self.subTest(id=variant["id"]):
                result = notes.add_note(variant, self.directory)
                self.assertEqual(
                    ("duplicate", self.card["id"]), (result["action"], result["id"])
                )
                self.assertFalse((self.directory / (variant["id"] + ".json")).exists())

    def test_replacement_cannot_duplicate_another_lesson(self):
        notes.add_note(self.card, self.directory)
        other = dict(
            self.card, id="other", title="Different title", lesson="Different lesson"
        )
        notes.add_note(other, self.directory)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            notes.add_note(
                dict(other, lesson=self.card["lesson"]), self.directory, replace=True
            )
        with self.assertRaisesRegex(ValueError, "existing lesson"):
            notes.add_note(
                dict(other, id="missing", title="Missing", lesson="Missing content"),
                self.directory,
                replace=True,
            )
        with self.assertRaisesRegex(ValueError, "existing lesson"):
            notes.add_note(dict(other, id="missing"), self.directory, replace=True)

    def test_bad_ids_and_private_evidence_rejected_before_writing(self):
        for bad_id in (
            "../escape",
            "a/b",
            "a\\b",
            "UPPER",
            "..",
            "C:drive",
            "a" * 81,
            "con",
            "lpt1",
        ):
            with self.subTest(id=bad_id), self.assertRaises(ValueError):
                notes.add_note(dict(self.card, id=bad_id), self.directory)
        for url in (
            "file:///tmp/run",
            "http://127.0.0.1/x",
            "http://10.0.0.2",
            "https://host.internal/run",
            "https://localhost/",
            "https://user:secret@example.com/x",
            "https://example.com:invalid",
        ):
            card = copy.deepcopy(self.card)
            card["evidence"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                notes.add_note(card, self.directory)
        self.assertFalse(self.directory.exists())

    def test_check_catches_hand_edited_duplicates_and_filename_mismatch(self):
        self.write_card(self.card)
        duplicate = dict(self.card, id="duplicate", title="graph LAUNCH overhead!")
        path = self.write_card(duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate title"):
            notes.read_cards(self.directory)
        path.unlink()
        (self.directory / "graph-overhead.json").rename(self.directory / "wrong.json")
        with self.assertRaisesRegex(ValueError, "Filename"):
            notes.read_cards(self.directory)

    def test_cli_invalid_json_and_missing_file_return_json_error(self):
        bad_file = Path(self.temp.name) / "bad.json"
        bad_file.write_text("{broken", encoding="utf-8")
        for source in (bad_file, Path(self.temp.name) / "missing.json"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = notes.main(
                    ["--directory", str(self.directory), "add", "--file", str(source)]
                )
            self.assertEqual(1, status)
            self.assertIn("error", json.loads(output.getvalue()))
        self.assertFalse(self.directory.exists())

    def test_search_is_deterministic_bounded_and_advisory(self):
        for card_id in ("zeta", "alpha", "delta", "beta"):
            notes.add_note(
                dict(
                    self.card,
                    id=card_id,
                    title=f"Graph {card_id}",
                    lesson=f"Recommendation for {card_id}",
                ),
                self.directory,
            )
        result = notes.search("GRAPH", self.directory)
        self.assertEqual(
            ["alpha", "beta", "delta"], [m["card"]["id"] for m in result["matches"]]
        )
        self.assertEqual(result, notes.search("GRAPH", self.directory))
        self.assertEqual(
            1, len(notes.search("graph", self.directory, limit=1)["matches"])
        )
        self.assertEqual([], notes.search("unmatched", self.directory)["matches"])
        self.assertIn("Advisory", result["caution"])
        self.assertTrue(Path(result["matches"][0]["source"]).is_file())
        for query, limit in (("", 3), ("!!!", 3), ("graph", 0)):
            with self.assertRaises(ValueError):
                notes.search(query, self.directory, limit)

    def test_invalid_structure_is_reported_not_silently_skipped(self):
        for card in (
            [],
            dict(self.card, status="ready"),
            dict(self.card, evidence=[]),
            dict(self.card, extra="private receipt"),
        ):
            with self.subTest(card=card), self.assertRaises(ValueError):
                notes.validate(card)
        self.directory.mkdir()
        (self.directory / "broken.json").write_text("[1]", encoding="utf-8")
        with self.assertRaises(ValueError):
            notes.search("graph", self.directory)

    def test_symlink_card_cannot_escape_library(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text(json.dumps(self.card), encoding="utf-8")
        self.directory.mkdir()
        try:
            (self.directory / "graph-overhead.json").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation unavailable on this host")
        with self.assertRaisesRegex(ValueError, "inside the library"):
            notes.add_note(self.card, self.directory, replace=True)
        self.assertEqual(self.card, json.loads(outside.read_text(encoding="utf-8")))

    def test_curated_library_validates_and_excludes_archives(self):
        cards = notes.read_cards(notes.DEFAULT_DIRECTORY)
        self.assertGreaterEqual(len(cards), 4)
        result = notes.search("precision graph production", limit=20)
        self.assertTrue(result["matches"])
        self.assertTrue(
            all(
                Path(m["source"]).parent == notes.DEFAULT_DIRECTORY
                for m in result["matches"]
            )
        )


if __name__ == "__main__":
    unittest.main()
