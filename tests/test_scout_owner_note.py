"""Owner feedback writing preserves evidence and uses the deployed projection."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_owner_note as writer


class OwnerNoteWriterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = "public/project"
        self.raw = f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/file.py"
        self.blob = f"https://github.com/{self.repo}/blob/{'a' * 40}/src/file.py"
        self.note = dict(repo=self.repo, prior_hypothesis="FileWrapper loses current value",
                         source_url=self.raw, reason="Native pair reproduced a supported boundary",
                         reopen_when="Changed source, contract or substantive feedback",
                         evidence_url=self.blob)
        self.target = writer.memory.owner_source_note_path(self.root, self.repo)

    def write_existing(self, rows):
        self.target.parent.mkdir(exist_ok=True)
        self.target.write_text(json.dumps(rows), encoding="utf-8")
        return self.target.read_bytes()

    def test_raw_and_blob_sources_use_one_canonical_file(self):
        for url in (self.raw, self.blob, self.blob + "#L12-L15"):
            with self.subTest(url=url):
                self.assertEqual(writer.canonical_source(url, self.repo), self.raw)
        actual = writer.write_note(self.root, {**self.note, "source_url": self.blob + "#L12"})
        self.assertEqual(actual["status"], "STORED")
        self.assertEqual(actual["source_url"], self.raw)
        self.assertEqual(actual["context_status"], "SELECTED_NOW")
        self.assertEqual(actual["projection"]["reason"], self.note["reason"])
        self.assertEqual(json.loads(self.target.read_text()), [self.note])
        self.assertFalse((self.root / "delivery").exists())

    def test_repeat_is_byte_identical_and_does_not_refresh_recency(self):
        before = self.write_existing([self.note, {**self.note, "prior_hypothesis": "Other", "reason": "Different evidence"}])
        result = writer.write_note(self.root, copy.deepcopy(self.note))
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertEqual(self.target.read_bytes(), before)

    def test_update_replaces_only_same_hypothesis_and_full_file(self):
        older = {**self.note, "source_url": self.raw.replace("a" * 40, "b" * 40)}
        other_file = {**self.note, "source_url": self.raw.replace("src/file.py", "tests/file.py")}
        unrelated = {**self.note, "prior_hypothesis": "Another helper", "reason": "Keep this evidence"}
        before = [older, other_file, unrelated, {"legacy": "preserve uninterpreted entries"}]
        self.write_existing(before)
        new = {**self.note, "reason": "A changed source invalidated the old explanation"}
        writer.write_note(self.root, new)
        self.assertEqual(json.loads(self.target.read_text()), before[1:] + [new])

    def test_unrelated_same_file_notes_are_preserved(self):
        old = [{**self.note, "prior_hypothesis": f"Other {i}", "reason": f"Distinct evidence {i}"} for i in range(23)]
        self.write_existing(old)
        writer.write_note(self.root, self.note)
        self.assertEqual(json.loads(self.target.read_text()), old + [self.note])
        self.assertEqual(len(writer.memory.owner_note_rows(self.root, self.repo)), 24)

    def test_existing_repeat_hidden_by_reader_dedup_is_reported_not_rewritten(self):
        before = self.write_existing([self.note, {**self.note, "prior_hypothesis": "Same facts, later title"}])
        with self.assertRaisesRegex(ValueError, "context window"):
            writer.write_note(self.root, self.note)
        self.assertEqual(self.target.read_bytes(), before)

    def test_invalid_source_forms_are_rejected_without_target_creation(self):
        for url in (
            self.raw.replace("a" * 40, "main"), self.blob.replace("a" * 40, "HEAD"),
            self.raw.replace("public/project", "personal/project"),
            self.blob.replace("public/project", "personal/project"),
            self.raw.replace("https:", "http:"), self.raw + "?token=secret",
            self.raw.replace("https://", "https://user:secret@"),
            self.raw.replace("/src/", "/src/../"), self.raw.replace("/src/", "/src/%2e%2e/"),
            self.raw.replace("/src/", "/src\\"), self.blob + "#secret",
            self.raw.replace("raw.githubusercontent.com", "raw.githubusercontent.com.invalid"),
            self.blob.replace("github.com", "github.com:443"), "not a URL", None,
            self.raw.replace("https", "htt\nps"), self.raw.replace("file.py", "file name.py"),
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "source_url"):
                    writer.write_note(self.root, {**self.note, "source_url": url})
                self.assertFalse(self.target.exists())

    def test_fork_evidence_has_an_actionable_error_and_preserves_history(self):
        before = self.write_existing([self.note])
        bad = {**self.note, "evidence_url": self.blob.replace("public/project", "personal/project")}
        with self.assertRaisesRegex(ValueError, "same-repository"):
            writer.write_note(self.root, bad)
        self.assertEqual(self.target.read_bytes(), before)

    def test_schema_limits_and_private_paths_do_not_write(self):
        bad_notes = [
            {**self.note, "execution_authorized": True},
            {key: value for key, value in self.note.items() if key != "reopen_when"},
            {**self.note, "prior_hypothesis": "x" * 201},
            {**self.note, "reason": "x" * 1001},
            {**self.note, "reopen_when": " "},
            {**self.note, "reason": "Read D:/private/evidence.json"},
            {**self.note, "repo": "../escape"},
        ]
        for note in bad_notes:
            with self.subTest(note=note):
                with self.assertRaises(ValueError):
                    writer.write_note(self.root, note)
                self.assertFalse(self.target.exists())

    def test_existing_malformed_oversized_or_nonlist_history_is_not_replaced(self):
        self.target.parent.mkdir()
        for raw in (b"", b"not JSON", b"null", b"{}", b"[" * 2000, b" " * 65537):
            with self.subTest(size=len(raw)):
                self.target.write_bytes(raw)
                with self.assertRaises(ValueError):
                    writer.write_note(self.root, self.note)
                self.assertEqual(self.target.read_bytes(), raw)

    def test_capacity_failure_preserves_unknown_rows(self):
        before = self.write_existing([{"legacy": "x" * 65000}])
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            writer.write_note(self.root, {**self.note, "reason": "x" * 1000})
        self.assertEqual(self.target.read_bytes(), before)

    def test_expected_snapshot_refuses_stale_writer(self):
        before = self.write_existing([self.note])
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            writer.write_note(self.root, self.note, expected_sha256="0" * 64)
        self.assertEqual(self.target.read_bytes(), before)
        actual = writer.write_note(self.root, self.note, expected_sha256=hashlib.sha256(before).hexdigest())
        self.assertEqual(actual["status"], "UNCHANGED")

    def test_missing_file_uses_empty_byte_snapshot(self):
        result = writer.write_note(self.root, self.note, expected_sha256=hashlib.sha256(b"").hexdigest())
        self.assertEqual(result["status"], "STORED")

    def test_intervening_change_is_not_overwritten(self):
        before = self.write_existing([self.note])
        real = writer.snapshot
        observed = 0
        def changed(path):
            nonlocal observed
            observed += 1
            if observed == 2:
                path.write_bytes(before + b"\n")
            return real(path)
        with patch.object(writer, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during validation"):
                writer.write_note(self.root, {**self.note, "reason": "New"})
        self.assertEqual(self.target.read_bytes(), before + b"\n")

    def test_atomic_replace_failure_preserves_old_file_and_cleans_own_temp(self):
        before = self.write_existing([self.note])
        with patch.object(writer.os, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                writer.write_note(self.root, {**self.note, "reason": "New"})
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(list(self.target.parent.glob(".reviewed-note-*.tmp")), [])

    def test_report_exposes_clipping_not_invented_full_visibility(self):
        long = {**self.note, "reason": "x" * 600, "reopen_when": "y" * 600}
        result = writer.write_note(self.root, long)
        self.assertTrue(result["projection"]["truncated"])
        self.assertEqual(len(result["projection"]["reason"]), 350)
        self.assertEqual(json.loads(self.target.read_text())[0]["reason"], long["reason"])

    def test_report_does_not_claim_selection_when_live_context_omits_note(self):
        real = writer.memory.owner_deferral_context
        def lookup(root, *args, **kwargs):
            if Path(root) == self.root:
                return None
            return real(root, *args, **kwargs)
        with patch.object(writer.memory, "owner_deferral_context", side_effect=lookup):
            result = writer.write_note(self.root, self.note)
        self.assertEqual(result["status"], "STORED")
        self.assertEqual(result["context_status"], "NOT_SELECTED_NOW")
        self.assertIsNone(result["projection"])

    def test_reader_disagreement_prevents_a_write(self):
        with patch.object(writer.memory, "owner_note_rows", return_value=[]):
            with self.assertRaisesRegex(ValueError, "not admitted"):
                writer.write_note(self.root, self.note)
        self.assertFalse(self.target.exists())

    def test_write_does_not_touch_unrelated_scout_state_or_make_calls(self):
        untouched = [self.root / "scout.sqlite", self.root / "STOP", self.root / "runtime.json"]
        for path in untouched:
            path.write_bytes(b"sentinel")
        other = self.root / "owner-source-notes" / "other%2Frepo.json"
        other.parent.mkdir()
        other.write_bytes(b"unrelated")
        with patch.object(subprocess, "run", side_effect=AssertionError("no process launch")):
            result = writer.write_note(self.root, self.note)
        self.assertEqual(result["status"], "STORED")
        self.assertTrue(all(p.read_bytes() == b"sentinel" for p in untouched))
        self.assertEqual(other.read_bytes(), b"unrelated")

    def test_symlink_target_or_parent_is_rejected(self):
        other = self.root / "other.json"
        other.write_text("[]")
        self.target.parent.mkdir()
        try:
            self.target.symlink_to(other)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ValueError, "symlink"):
            writer.write_note(self.root, self.note)
        self.assertEqual(other.read_text(), "[]")

    def test_cli_uses_the_same_writer_and_fails_before_invalid_note_changes(self):
        path = self.root / "note.json"
        path.write_text(json.dumps(self.note))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            writer.main(["--root", str(self.root), "--note", str(path)])
        self.assertEqual(json.loads(output.getvalue())["status"], "STORED")
        before = self.target.read_bytes()
        path.write_text(json.dumps({**self.note, "evidence_url": "invalid"}))
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                writer.main(["--root", str(self.root), "--note", str(path)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(self.target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
