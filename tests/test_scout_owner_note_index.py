"""Indexed feedback preserves legacy evidence and bounds actual reader work."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_owner_note as writer
import scout_publication_context as memory


class IndexedOwnerNoteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = "public/project"
        self.note = dict(
            repo=self.repo, prior_hypothesis="ImageProcessor checkpoint stats",
            source_url=f"https://raw.githubusercontent.com/{self.repo}/{'a'*40}/src/image.py",
            reason="Matched native pair reproduced the pixel difference",
            reopen_when="Changed checkpoint contract or new source evidence",
            evidence_url=f"https://github.com/{self.repo}/issues/12")
        self.index = memory.owner_note_index_path(self.root)

    def projection(self, note=None):
        return writer.indexed_projection(self.root, note or self.note)

    def records(self):
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            return db.execute("SELECT repo,source_path,hypothesis,revision,note FROM owner_notes ORDER BY revision").fetchall()

    def legacy(self, rows):
        path = memory.owner_source_note_path(self.root, self.repo)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path

    def test_full_legacy_file_no_longer_blocks_explicit_indexed_writer(self):
        path = self.legacy([{"legacy": "x" * 65000}])
        before = path.read_bytes()
        note = {**self.note, "reason": "x" * 1000}
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            writer.write_note(self.root, note)
        self.assertFalse(self.index.exists())
        result = writer.write_indexed_note(self.root, note)
        self.assertEqual(result["status"], "STORED")
        self.assertEqual(result["context_status"], "SELECTED_NOW")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.projection(note)["reason"], "x" * 350)

    def test_old_file_survives_many_newer_unrelated_paths(self):
        writer.write_indexed_note(self.root, self.note)
        for i in range(36):
            writer.write_indexed_note(self.root, {
                **self.note, "source_url": self.note["source_url"].replace("image.py", f"other{i}.py")})
        self.assertEqual(len(memory.owner_note_rows(self.root, self.repo)), 24)
        self.assertIsNotNone(self.projection())
        self.assertEqual(len(memory.owner_note_rows(
            self.root, self.repo, sources=[{"url": self.note["source_url"]}])), 1)

    def test_repeat_is_logically_idempotent_without_refreshing_revision(self):
        first = writer.write_indexed_note(self.root, self.note)
        before = self.records()
        again = writer.write_indexed_note(self.root, dict(reversed(list(self.note.items()))))
        self.assertEqual(again["status"], "UNCHANGED")
        self.assertEqual(first["sha256"], again["sha256"])
        self.assertEqual(self.records(), before)

    def test_supersession_changes_only_the_same_logical_note(self):
        old = self.legacy([self.note])
        legacy_before = old.read_bytes()
        first = writer.write_indexed_note(self.root, self.note)
        other = {**self.note, "prior_hypothesis": "Different bug", "reason": "Keep this"}
        writer.write_indexed_note(self.root, other)
        saved_other = self.records()[-1]
        new = {**self.note, "source_url": self.note["source_url"].replace("a" * 40, "b" * 40),
               "reason": "Changed source invalidated the old explanation"}
        writer.write_indexed_note(self.root, new, expected_sha256=first["sha256"])
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.records()[0], saved_other)
        self.assertEqual(self.records()[-1][-1], json.dumps(new, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        self.assertEqual(old.read_bytes(), legacy_before)
        rows = memory.owner_note_rows(self.root, self.repo,
                                      sources=[{"url": new["source_url"]}])
        self.assertEqual(len(rows), 2)
        self.assertNotIn(self.note["reason"], json.dumps(rows))

    def test_snapshot_is_per_note_not_the_whole_database(self):
        first = writer.write_indexed_note(self.root, self.note)
        writer.write_indexed_note(self.root, {**self.note, "prior_hypothesis": "Other"})
        result = writer.write_indexed_note(self.root, self.note, expected_sha256=first["sha256"])
        self.assertEqual(result["status"], "UNCHANGED")
        before = self.records()
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            writer.write_indexed_note(self.root, {**self.note, "reason": "New"}, expected_sha256="0" * 64)
        self.assertEqual(self.records(), before)

    def test_missing_indexed_note_uses_empty_byte_hash(self):
        result = writer.write_indexed_note(self.root, self.note,
                                           expected_sha256=hashlib.sha256(b"").hexdigest())
        self.assertEqual(result["status"], "STORED")

    def test_repository_and_source_path_scope_is_exact(self):
        writer.write_indexed_note(self.root, self.note)
        sources = [{"url": self.note["source_url"]}]
        self.assertEqual(memory.indexed_owner_notes(self.root, "other/project", sources), [])
        self.assertEqual(memory.indexed_owner_notes(self.root, self.repo, []), [])
        changed = [{"url": self.note["source_url"].replace("image.py", "image.py.extra")}]
        self.assertEqual(memory.indexed_owner_notes(self.root, self.repo, changed), [])
        changed_revision = [{"url": self.note["source_url"].replace("a" * 40, "b" * 40)}]
        self.assertEqual(memory.indexed_owner_notes(self.root, self.repo, changed_revision), [self.note])

    def test_row_and_serialized_byte_bounds_stay_bounded(self):
        for i in range(30):
            writer.write_indexed_note(self.root, {
                **self.note, "prior_hypothesis": f"Hypothesis{i}",
                "reason": "界" * 1000, "reopen_when": "新" * 1000})
        result = memory.indexed_owner_notes(self.root, self.repo,
                                           [{"url": self.note["source_url"]}])
        self.assertLessEqual(len(result), 24)
        self.assertLess(len(result), 30)
        size = sum(len(json.dumps(n, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode()) for n in result)
        self.assertLessEqual(size, memory.OWNER_NOTE_LIMIT_BYTES)
        sources = [{"url": self.note["source_url"].replace("image.py", f"x{i}.py")}
                   for i in range(memory.OWNER_INDEX_PATH_LIMIT + 1)]
        self.assertEqual(memory.indexed_owner_notes(self.root, self.repo, sources), [])

    def test_source_lookup_uses_the_path_index(self):
        writer.write_indexed_note(self.root, self.note)
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            plan = db.execute("EXPLAIN QUERY PLAN SELECT revision,note FROM owner_notes "
                              "WHERE repo=? AND source_path=? ORDER BY revision DESC LIMIT 24",
                              (self.repo, "src/image.py")).fetchall()
        self.assertTrue(any("owner_notes_path" in row[-1] for row in plan))
        self.assertFalse(any("SCAN owner_notes" in row[-1] for row in plan))

    def test_invalid_indexed_note_cannot_shadow_valid_legacy_note(self):
        path = self.legacy([self.note])
        writer.write_indexed_note(self.root, self.note)
        bad = {**self.note, "reason": "Read D:/private/raw.json"}
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            db.execute("UPDATE owner_notes SET note=?", (json.dumps(bad),))
        self.assertEqual(len(memory.owner_note_rows(self.root, self.repo)), 1)
        self.assertEqual(self.projection()["reason"], self.note["reason"])
        self.assertEqual(json.loads(path.read_text()), [self.note])

    def test_corrupt_unknown_or_locked_index_keeps_legacy_advice(self):
        self.legacy([self.note])
        self.index.write_bytes(b"not a database")
        self.assertEqual(len(memory.owner_note_rows(self.root, self.repo)), 1)
        self.index.unlink()
        writer.write_indexed_note(self.root, self.note)
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            db.execute("PRAGMA user_version=99")
        before = self.index.read_bytes()
        with self.assertRaisesRegex(ValueError, "unknown"):
            writer.write_indexed_note(self.root, self.note)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(len(memory.owner_note_rows(self.root, self.repo)), 1)
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            db.execute("PRAGMA user_version=1")
            db.execute("BEGIN EXCLUSIVE")
            self.assertEqual(len(memory.owner_note_rows(self.root, self.repo)), 1)
            with self.assertRaises(sqlite3.OperationalError):
                writer.write_indexed_note(self.root, self.note)

    def test_indexed_cli_and_reader_disagreement_do_not_claim_success(self):
        note_path = self.root / "input.json"
        note_path.write_text(json.dumps(self.note))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            writer.main(["--root", str(self.root), "--note", str(note_path), "--indexed"])
        self.assertEqual(json.loads(output.getvalue())["storage"], "indexed")
        other = self.root / "new"
        other.mkdir()
        with patch.object(writer, "indexed_projection", return_value=None):
            with self.assertRaisesRegex(ValueError, "not projected"):
                writer.write_indexed_note(other, self.note)
        self.assertFalse(memory.owner_note_index_path(other).exists())

    def test_index_is_read_only_during_context_lookup_and_jobs_stay_untouched(self):
        writer.write_indexed_note(self.root, self.note)
        before = self.index.read_bytes()
        sentinels = [self.root / name for name in ("scout.sqlite", "STOP", "runtime.json")]
        for path in sentinels:
            path.write_bytes(b"sentinel")
        with patch.object(writer.os, "replace", side_effect=AssertionError("No JSON rewrite")):
            self.assertIsNotNone(self.projection())
            writer.write_indexed_note(self.root, {**self.note, "reason": "Updated"})
        self.assertTrue(all(path.read_bytes() == b"sentinel" for path in sentinels))
        read_before = self.index.read_bytes()
        self.assertIsNotNone(self.projection({**self.note, "reason": "Updated"}))
        self.assertEqual(self.index.read_bytes(), read_before)
        self.assertNotEqual(before, read_before)

    def test_symlink_index_is_not_followed(self):
        outside = self.root / "outside.sqlite"
        outside.write_bytes(b"sentinel")
        try:
            self.index.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable")
        self.assertEqual(memory.owner_note_rows(self.root, self.repo), [])
        with self.assertRaisesRegex(ValueError, "nonsymlink"):
            writer.write_indexed_note(self.root, self.note)
        self.assertEqual(outside.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
