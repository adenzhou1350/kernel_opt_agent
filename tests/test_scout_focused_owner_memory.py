"""Relevant old advice must survive newer same-file notes, without suppression."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout  # noqa: E402
import kimi_scout_research as research  # noqa: E402
import scout_publication_context as memory  # noqa: E402


class FocusedOwnerMemoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = "public/project"
        self.source = {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/temp.py",
            "text": "1: class NamedTemporaryFile:\n2:     pass",
        }
        self.path = self.root / "owner-source-notes.json"

    def note(self, title, **changes):
        return {
            "repo": self.repo,
            "prior_hypothesis": title,
            "source_url": self.source["url"],
            "reason": "Native control for " + title,
            "reopen_when": "A distinct native failure or changed supported contract",
            "evidence_url": f"https://github.com/{self.repo}/blob/{'a' * 40}/src/temp.py",
            **changes,
        }

    def write(self, notes):
        self.path.write_text(json.dumps(notes), encoding="utf-8")

    def read(self, title):
        return memory.owner_deferral_context(
            self.root,
            self.repo,
            [self.source],
            prior_analysis=json.dumps({"title": title}),
        )

    def test_older_exact_identifier_note_survives_two_newer_same_file_notes(self):
        self.write(
            [
                self.note("NamedTemporaryFile construction cancellation"),
                self.note("TemporaryDirectory acquisition cancellation"),
                self.note("SpooledTemporaryFile rollover cancellation"),
            ]
        )
        before = self.path.read_bytes()
        items = self.read("NamedTemporaryFile.__aenter__ may leak")["items"]
        self.assertEqual(
            items[0]["prior_hypothesis"], "NamedTemporaryFile construction cancellation"
        )
        self.assertEqual(
            items[1]["prior_hypothesis"], "SpooledTemporaryFile rollover cancellation"
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root / "delivery").exists())

    def test_only_prior_title_not_model_explanation_selects_advice(self):
        self.write(
            [
                self.note("NamedTemporaryFile cancellation"),
                self.note("TemporaryDirectory cancellation"),
                self.note("SpooledTemporaryFile cancellation"),
            ]
        )
        result = memory.owner_deferral_context(
            self.root,
            self.repo,
            [self.source],
            prior_analysis=json.dumps(
                {"title": "ordinary prose", "hypothesis": "NamedTemporaryFile"}
            ),
        )
        self.assertEqual(
            result, memory.owner_deferral_context(self.root, self.repo, [self.source])
        )

    def test_identifier_substrings_do_not_promote_unrelated_note(self):
        self.write(
            [
                self.note("NamedTemporaryFileV2 cancellation"),
                self.note("TemporaryDirectory cancellation"),
                self.note("SpooledTemporaryFile cancellation"),
            ]
        )
        self.assertEqual(
            self.read("NamedTemporaryFile cancellation"),
            memory.owner_deferral_context(self.root, self.repo, [self.source]),
        )

    def test_snake_case_match_and_recency_tie(self):
        self.write(
            [
                self.note("restore_state older"),
                self.note("other_helper newer"),
                self.note("restore_state latest"),
            ]
        )
        titles = [
            x["prior_hypothesis"] for x in self.read("restore_state failure")["items"]
        ]
        self.assertEqual(titles, ["restore_state latest", "restore_state older"])

    def test_invalid_private_foreign_or_other_file_notes_still_cannot_enter(self):
        self.write(
            [
                self.note("AllowedOtherClass"),
                self.note("NamedTemporaryFile", reason="Read D:/private/log"),
                self.note(
                    "NamedTemporaryFile",
                    evidence_url="https://github.com/other/repo/pull/1",
                ),
                self.note(
                    "NamedTemporaryFile",
                    source_url=self.source["url"].replace("temp.py", "other.py"),
                ),
            ]
        )
        self.assertEqual(
            [x["prior_hypothesis"] for x in self.read("NamedTemporaryFile")["items"]],
            ["AllowedOtherClass"],
        )

    def test_malformed_oversized_or_non_object_analysis_keeps_recency(self):
        self.write([self.note("NamedTemporaryFile"), self.note("OtherClass")])
        expected = memory.owner_deferral_context(self.root, self.repo, [self.source])
        for value in (
            None,
            {},
            "{broken",
            "[]",
            "[" * 3000,
            json.dumps({"title": 123}),
            json.dumps({"title": "x" * 201}),
        ):
            with self.subTest(value=str(value)[:50]):
                self.assertEqual(
                    memory.owner_deferral_context(
                        self.root, self.repo, [self.source], prior_analysis=value
                    ),
                    expected,
                )

    def test_emitter_uses_prior_focus_without_replaying_same_source(self):
        self.write(
            [
                self.note("NamedTemporaryFile refuted"),
                self.note("TemporaryDirectory unrelated"),
                self.note("SpooledTemporaryFile unrelated"),
            ]
        )
        scout.initialize(self.root)
        config = self.root / "config.json"
        spec = {"repo": self.repo, "question": "test", "source_prefixes": ["src/"]}
        config.write_text(
            json.dumps(
                {
                    "objective": "test",
                    "queue_target": 8,
                    "source_windows": 2,
                    "repos": [spec],
                }
            ),
            encoding="utf-8",
        )
        producer = research.ResearchProducer(self.root, config, context=object())
        parent = {
            "id": "prior",
            "root": "prior",
            "depth": 0,
            "analysis": json.dumps({"title": "NamedTemporaryFile may leak"}),
        }
        self.assertTrue(
            producer.emit(
                "first", spec, [self.source], "source_followup", parent=parent
            )
        )
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(
            packet["owner_deferrals"]["items"][0]["prior_hypothesis"],
            "NamedTemporaryFile refuted",
        )
        self.assertIn("Never reject", packet["owner_deferrals"]["caution"])
        self.assertEqual(packet["sources"], [self.source])
        self.assertFalse(
            producer.emit("same", spec, [self.source], "source_followup", parent=parent)
        )


if __name__ == "__main__":
    unittest.main()
