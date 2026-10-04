"""Publication hints are bounded, read-only and do not decide candidate quality."""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
import scout_publication_context as memory


class PublicationContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = "public/project"
        self.source = {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/subject.py",
            "text": "1: primary source",
        }
        self.path = self.root / "delivery" / "delivery.sqlite"

    def initialize(self):
        self.path.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE delivery(id,repo,title,state,updated_at,result,payload)"
            )

    def add(
        self,
        id,
        url,
        *,
        repo=None,
        state="PR_OPEN",
        source=None,
        result=None,
        payload=None,
    ):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO delivery VALUES(?,?,?,?,?,?,?)",
                (
                    id,
                    repo or self.repo,
                    "untrusted hypothesis " + "x" * 300,
                    state,
                    id,
                    result if result is not None else json.dumps({"pr": {"url": url}}),
                    payload
                    if payload is not None
                    else json.dumps({"packet": {"sources": [source or self.source]}}),
                ),
            )

    def read(self, sources=None):
        return memory.publication_context(
            self.root, self.repo, sources or [self.source]
        )

    def defer(self, id, *, source=None, **changes):
        record = {
            "reason": "Old contract lacks a supported caller",
            "reopen_when": "Show a supported caller or distinct new defect",
            "evidence_url": f"https://github.com/{self.repo}/blob/{'a' * 40}/src/subject.py",
            **changes,
        }
        self.add(
            id,
            "",
            state="OWNER_PARKED",
            source=source,
            result=json.dumps(
                {"owner_disposition": record, "private_log": "x" * 200000}
            ),
        )

    def deferrals(self):
        return memory.owner_deferral_context(self.root, self.repo, [self.source])

    def note(self, **changes):
        return {
            "repo": self.repo,
            "prior_hypothesis": "Wrapper drops a field",
            "source_url": self.source["url"],
            "reason": "The producer uses another constructor",
            "reopen_when": "Show a supported consumer of this helper",
            "evidence_url": f"https://github.com/{self.repo}/blob/{'a' * 40}/src/subject.py",
            **changes,
        }

    def write_notes(self, notes):
        path = self.root / "owner-source-notes.json"
        path.write_text(json.dumps(notes), encoding="utf-8")
        return path

    def test_source_notes_work_without_creating_a_delivery_record(self):
        path = self.write_notes([self.note()])
        before = path.read_bytes()
        result = self.deferrals()
        self.assertEqual(result["items"][0]["reason"], self.note()["reason"])
        self.assertIn("Never reject", result["caution"])
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(path.read_bytes(), before)

    def test_same_repo_pr_is_advisory_evidence_not_a_quality_or_state_verdict(self):
        url = f"https://github.com/{self.repo}/pull/123"
        path = self.write_notes([self.note(evidence_url=url)])
        before = path.read_bytes()
        self.assertEqual(len(memory.owner_note_rows(self.root, self.repo)), 1)
        hint = self.deferrals()
        self.assertEqual(hint["items"][0]["evidence_url"], url)
        self.assertIn("Never reject", hint["caution"])
        self.assertIn("current CI/review/merge", hint["caution"])
        self.assertNotIn("quality", hint["items"][0])
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(path.read_bytes(), before)

    def test_pr_advice_rejects_foreign_private_and_ambiguous_evidence_urls(self):
        for url in (
            "https://github.com/other/project/pull/123",
            f"https://github.com/{self.repo}/issues/123",
            f"https://github.com/{self.repo}/pull/0",
            f"https://github.com/{self.repo}/pull/123/files",
            f"https://github.com/{self.repo}/pull/123#discussion",
            f"https://github.com/{self.repo}/pull/123?token=private",
            "http://github.com/public/project/pull/123",
            "https://github.com.evil.test/public/project/pull/123",
            "D:/private/evidence.json",
            None,
        ):
            with self.subTest(url=url):
                self.write_notes([self.note(evidence_url=url)])
                self.assertEqual(memory.owner_note_rows(self.root, self.repo), [])
                self.assertIsNone(self.deferrals())

    def test_source_notes_are_optional_bounded_and_require_explicit_fields(self):
        path = self.write_notes([self.note()])
        for text in (
            "{broken",
            "[]",
            "[" * 2000,
            json.dumps({"not": "a list"}),
            " " * (memory.OWNER_NOTE_LIMIT_BYTES + 1),
            json.dumps([self.note(private_log="do not export")]),
        ):
            with self.subTest(text=text[:30]):
                path.write_text(text, encoding="utf-8")
                self.assertIsNone(self.deferrals())
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_growing_source_memory_retains_advice_without_erasing_history(self):
        notes = [self.note(reason=f"Supported-path audit {i}") for i in range(40)]
        path = self.write_notes(notes)
        before = path.read_bytes()
        rows = memory.owner_note_rows(self.root, self.repo)
        self.assertEqual(len(rows), 24)
        self.assertEqual(
            [json.loads(row[1])["reason"] for row in rows],
            [f"Supported-path audit {i}" for i in range(39, 15, -1)],
        )
        result = self.deferrals()
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["reason"], "Supported-path audit 39")
        self.assertIn("Never reject", result["caution"])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.path.parent.exists())

    def test_other_repositories_and_duplicate_or_invalid_notes_consume_no_slots(self):
        notes = [
            self.note(
                repo="other/project",
                source_url=self.source["url"].replace(self.repo, "other/project"),
            )
            for _ in range(25)
        ]
        valid = self.note()
        invalid = [
            self.note(reason=None),
            self.note(reason="Read D:/private/run.json"),
            self.note(evidence_url="https://github.com/other/project/commit/" + "a" * 40),
            self.note(source_url=self.source["url"].replace("a" * 40, "main")),
            self.note(private_log="do not export"),
        ]
        path = self.write_notes([valid, *notes, *([valid] * 25), *invalid])
        before = path.read_bytes()
        rows = memory.owner_note_rows(self.root, self.repo)
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.deferrals()["items"][0]["reason"], valid["reason"])
        self.assertEqual(path.read_bytes(), before)

    def test_source_notes_deduplicate_with_delivery_and_preserve_scan_caps(self):
        self.initialize()
        self.defer(
            1, reason=self.note()["reason"], reopen_when=self.note()["reopen_when"]
        )
        self.write_notes([self.note(), self.note(), self.note(reason="Newest note")])
        result = self.deferrals()
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["reason"], "Newest note")
        self.assertEqual(result["items"][1]["reason"], self.note()["reason"])

    def test_source_notes_foreign_unpinned_private_and_wrong_file_are_ignored(self):
        for changes in (
            {"repo": "other/project"},
            {"source_url": self.source["url"].replace("subject", "other")},
            {"source_url": self.source["url"].replace("a" * 40, "main")},
            {"evidence_url": "https://github.com/other/project/commit/" + "a" * 40},
            {"evidence_url": "https://github.com/public/project/blob/main/subject.py"},
            {"reason": "Read D:/codes/private/evidence.json"},
            {"prior_hypothesis": "Read /workspace/private/log"},
            {"reopen_when": None},
            {"reason": "r" * 1001},
        ):
            with self.subTest(changes=changes):
                self.write_notes([self.note(**changes)])
                self.assertIsNone(self.deferrals())

    def test_source_notes_survive_optional_unavailable_delivery_history(self):
        self.initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE delivery")
        before = self.path.read_bytes()
        self.write_notes([self.note()])
        self.assertIsNotNone(self.deferrals())
        self.assertEqual(self.path.read_bytes(), before)

    def test_source_notes_cannot_create_paid_work_or_suppress_changed_source(self):
        config = {
            "objective": "test",
            "queue_target": 8,
            "source_windows": 2,
            "repos": [
                {"repo": self.repo, "question": "test", "source_prefixes": ["src/"]}
            ],
        }
        scout.initialize(self.root)
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        producer = research.ResearchProducer(self.root, config_path, context=object())
        spec = producer.config["repos"][0]
        self.assertTrue(producer.emit("before", spec, [self.source], "source_audit"))
        note = self.note(evidence_url=f"https://github.com/{self.repo}/pull/123")
        self.write_notes([note] * 25)
        self.assertFalse(producer.emit("same", spec, [self.source], "source_audit"))
        newer = {**self.source, "text": "1: new supported caller"}
        self.assertTrue(producer.emit("new", spec, [newer], "source_audit"))
        with scout.connect(self.root) as db:
            rows = db.execute("SELECT packet FROM jobs ORDER BY created,id").fetchall()
        self.assertEqual(len(rows), 2)
        packet = json.loads(rows[-1][0])
        self.assertEqual(packet["sources"], [newer])
        self.assertEqual(
            packet["owner_deferrals"]["items"][0]["reason"], self.note()["reason"]
        )
        self.assertEqual(
            packet["owner_deferrals"]["items"][0]["evidence_url"],
            note["evidence_url"],
        )

    def test_deferrals_missing_or_unavailable_history_is_optional(self):
        self.assertIsNone(self.deferrals())
        self.assertFalse(self.path.parent.exists())
        self.initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE delivery")
        before = self.path.read_bytes()
        self.assertIsNone(self.deferrals())
        self.assertEqual(self.path.read_bytes(), before)

    def reject(self, id, *, state="NO_BUG", source=None, **changes):
        rejection = {
            "reason": "The original shared guard rejects this input before the view",
            "evidence_url": f"https://github.com/{self.repo}/blob/{'a' * 40}/src/subject.py",
            **changes,
        }
        self.add(
            id,
            "",
            state=state,
            source=source,
            result=json.dumps(
                {
                    "owner_rejection": rejection,
                    "private_log": "x" * 200000,
                }
            ),
        )

    def test_owner_rejection_is_same_file_advice_not_current_source_verdict(self):
        self.initialize()
        self.reject(1)
        other = {"url": self.source["url"].replace("subject.py", "other.py")}
        self.reject(2, source=other)
        before = self.path.read_bytes()
        hint = self.deferrals()
        self.assertEqual(len(hint["items"]), 1)
        self.assertIn("original shared guard", hint["items"][0]["reason"])
        self.assertIn("distinct bugs", hint["items"][0]["reopen_when"])
        self.assertIn("not a no-bug", hint["caution"])
        self.assertNotIn("private_log", json.dumps(hint))
        self.assertEqual(self.path.read_bytes(), before)

    def test_model_verdict_and_private_or_invalid_rejections_are_not_advice(self):
        self.initialize()
        self.reject(1, state="REPRODUCED")
        self.reject(2, reason="Read /workspace/private/report")
        self.reject(
            3, evidence_url="https://github.com/other/project/commit/" + "a" * 40
        )
        self.reject(4, reason="r" * 1001)
        self.add(5, "", state="NO_BUG", result='{"decision":"reject"}')
        self.add(6, "", state="NO_BUG", result='{"owner_rejection":[]}')
        self.add(7, "", state="NO_BUG", result="{broken")
        self.assertIsNone(self.deferrals())

    def test_rejections_share_existing_scan_and_display_limits_with_deferrals(self):
        self.initialize()
        self.reject(1)
        self.defer(2, reason="A different parked explanation")
        self.reject(3, reason="A second rejected explanation")
        hint = self.deferrals()
        self.assertEqual(len(hint["items"]), 2)
        self.assertEqual(hint["items"][0]["reason"], "A second rejected explanation")
        other = {"url": self.source["url"].replace("subject.py", "other.py")}
        for i in range(4, 28):
            self.reject(i, source=other)
        self.assertIsNone(self.deferrals())

    def test_rejection_hint_does_not_replay_old_source_or_suppress_changed_source(self):
        self.initialize()
        scout.initialize(self.root)
        packet = {
            "name": "fixture",
            "question": "inspect",
            "repo": self.repo,
            "sources": [self.source],
        }
        initial = scout.enqueue(self.root, packet)
        self.reject(1)
        self.assertEqual(
            scout.enqueue(
                self.root,
                {
                    **packet,
                    "owner_deferrals": self.deferrals(),
                },
            ),
            initial,
        )
        newer = {**self.source, "text": "a changed supported caller"}
        self.assertNotEqual(
            scout.enqueue(
                self.root,
                {
                    **packet,
                    "sources": [newer],
                    "owner_deferrals": self.deferrals(),
                },
            ),
            initial,
        )
        with scout.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 2)

    def test_deferrals_same_file_only_capped_deduplicated_without_raw_logs(self):
        self.initialize()
        self.defer(1)
        self.defer(2)  # Same decision is not shown twice.
        other = {"url": self.source["url"].replace("subject.py", "other.py")}
        self.defer(3, source=other, reason="Different file")
        self.defer(4, reason="r" * 800, reopen_when="w" * 800)
        self.defer(5, reason="third note")
        before = self.path.read_bytes()
        context = self.deferrals()
        self.assertEqual(len(context["items"]), 2)
        self.assertEqual(context["items"][0]["reason"], "third note")
        second = context["items"][1]
        self.assertEqual(len(second["reason"]), 350)
        self.assertEqual(len(second["reopen_when"]), 350)
        self.assertTrue(second["truncated"])
        self.assertEqual(second["source_paths"], ["src/subject.py"])
        self.assertNotIn("private_log", json.dumps(context))
        self.assertIn("not a no-bug", context["caution"])
        self.assertIn("Never reject", context["caution"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_deferrals_invalid_foreign_or_model_review_records_are_ignored(self):
        self.initialize()
        self.defer(
            1, evidence_url="https://github.com/other/project/commit/" + "a" * 40
        )
        self.defer(2, evidence_url="https://github.com/public/project/blob/main/x.py")
        self.defer(3, reason="")
        self.defer(4, reopen_when=None)
        self.defer(5, reason="r" * 1001)
        self.add(6, "", state="OWNER_PARKED", result="{broken")
        self.add(7, "", state="OWNER_PARKED", result='{"owner_disposition":[]}')
        self.add(8, "", state="OWNER_PARKED", payload="[]")
        self.add(
            9,
            "",
            state="REPRODUCED",
            result=json.dumps(
                {
                    "owner_disposition": {
                        "reason": "Model verdict",
                        "reopen_when": "x",
                        "evidence_url": "https://github.com/public/project/commit/"
                        + "a" * 40,
                    }
                }
            ),
        )
        self.assertIsNone(self.deferrals())

    def test_deferrals_scan_only_latest_24_without_claiming_exhaustiveness(self):
        self.initialize()
        self.defer(1)
        other = {"url": self.source["url"].replace("subject.py", "other.py")}
        for id in range(2, 27):
            self.defer(id, source=other)
        self.assertIsNone(self.deferrals())

    def test_deferral_local_artifact_locations_are_not_exported_or_erased(self):
        self.initialize()
        examples = [
            "Evidence: runs/private-check/result.json",
            "Evidence: D:/codes/private/result.json",
            r"Evidence: C:\Users\someone\private.txt",
            "Evidence: /workspace/kernel-opt/closures/private",
            r"Evidence: \\server\share\private.txt",
            "Reopen with ./raw/private.log",
            "x" * 600 + " runs/private-after-display-cap/result.json",
        ]
        for i, reason in enumerate(examples, 1):
            self.defer(i, reason=reason)
        self.defer(20, reopen_when="Read /home/user/private/result.json")
        self.defer(21, reason="Public src/subject.py contract is incomplete")
        before = self.path.read_bytes()
        context = self.deferrals()
        self.assertEqual(len(context["items"]), 1)
        self.assertEqual(
            context["items"][0]["reason"],
            "Public src/subject.py contract is incomplete",
        )
        self.assertEqual(self.path.read_bytes(), before)

    def test_pinned_public_runs_directory_remains_eligible_evidence(self):
        self.initialize()
        public = f"https://github.com/{self.repo}/blob/{'a' * 40}/runs/repro.py"
        self.defer(1, reason="Public reproducer: " + public)
        self.assertEqual(
            self.deferrals()["items"][0]["reason"], "Public reproducer: " + public
        )

    def test_deferral_evidence_can_be_an_exact_removal_commit(self):
        self.initialize()
        url = "https://github.com/public/project/commit/" + "b" * 40
        self.defer(1, evidence_url=url)
        self.assertEqual(self.deferrals()["items"][0]["evidence_url"], url)

    def test_deferral_memory_drops_before_publications_and_primary_sources(self):
        packet = {
            "sources": [self.source],
            "owner_publications": {"items": ["small"]},
            "owner_deferrals": {"items": ["x" * 2000]},
        }
        baseline = json.loads(json.dumps(packet["sources"]))
        memory.fit_publication_context(packet, 500, "prefix")
        self.assertNotIn("owner_deferrals", packet)
        self.assertIn("owner_publications", packet)
        self.assertEqual(packet["sources"], baseline)

    def test_new_packets_get_owner_deferrals_without_replaying_seen_source(self):
        self.initialize()
        config = {
            "objective": "test",
            "queue_target": 8,
            "source_windows": 2,
            "repos": [
                {"repo": self.repo, "question": "test", "source_prefixes": ["src/"]}
            ],
        }
        scout.initialize(self.root)
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        producer = research.ResearchProducer(self.root, config_path, context=object())
        spec = producer.config["repos"][0]
        self.assertTrue(producer.emit("before", spec, [self.source], "source_audit"))
        self.defer(1)
        self.assertFalse(producer.emit("same", spec, [self.source], "source_audit"))
        newer = {**self.source, "text": "1: new supported caller"}
        self.assertTrue(producer.emit("new", spec, [newer], "source_audit"))
        with scout.connect(self.root) as db:
            packets = [
                json.loads(row[0])
                for row in db.execute("SELECT packet FROM jobs ORDER BY created,id")
            ]
        self.assertEqual(len(packets), 2)
        self.assertNotIn("owner_deferrals", packets[0])
        self.assertIn("owner_deferrals", packets[1])
        self.assertEqual(packets[1]["sources"], [newer])

    def test_direct_enqueue_deferral_changes_do_not_create_a_new_paid_task(self):
        scout.initialize(self.root)
        packet = {
            "name": "fixture",
            "question": "inspect contract",
            "repo": self.repo,
            "sources": [self.source],
        }
        initial = scout.enqueue(self.root, packet)
        for field in ("owner_deferrals", "owner_publications"):
            for note in ("old history", "new history"):
                changed = {**packet, field: {"items": [note]}}
                self.assertEqual(scout.enqueue(self.root, changed), initial)
        with scout.connect(self.root) as db:
            rows = db.execute("SELECT packet FROM jobs").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("owner_deferrals", json.loads(rows[0][0]))
        changed_source = {**self.source, "text": "new source evidence"}
        self.assertNotEqual(
            scout.enqueue(self.root, {**packet, "sources": [changed_source]}), initial
        )

    def test_missing_or_unavailable_database_is_optional_and_not_created(self):
        self.assertIsNone(self.read())
        self.assertFalse(self.path.parent.exists())
        self.initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE delivery")
        before = self.path.read_bytes()
        self.assertIsNone(self.read())
        self.assertEqual(self.path.read_bytes(), before)

    def test_matching_paths_prioritized_and_urls_deduplicated_without_mutation(self):
        self.initialize()
        self.add(1, "https://github.com/public/project/pull/1")
        for id in range(2, 6):
            other = {"url": self.source["url"].replace("subject.py", "other.py")}
            self.add(id, f"https://github.com/public/project/pull/{id}", source=other)
        self.add(6, "https://github.com/public/project/pull/5", source=other)
        before = self.path.read_bytes()
        context = self.read()
        self.assertEqual(
            [x["url"].rsplit("/", 1)[-1] for x in context["items"]], ["1", "5", "4"]
        )
        self.assertEqual(len(context["items"][0]["prior_hypothesis"]), 200)
        self.assertEqual(context["items"][0]["source_paths"], ["src/subject.py"])
        self.assertIn("Never reject or publish", context["caution"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_cross_repo_and_nonterminal_records_do_not_enter_context(self):
        self.initialize()
        self.add(1, "https://github.com/other/project/pull/1")
        self.add(2, "https://github.com/public/project/pull/2", repo="other/project")
        self.add(3, "https://github.com/public/project/pull/3", state="TESTING")
        self.add(4, "https://github.com/public/project/pull/4", result="{broken")
        self.add(5, "https://github.com/public/project/pull/5", payload="[]")
        self.add(6, "https://github.com/public/project/pull/6", result="x" * 200000)
        self.add(7, "https://github.com/public/project/pull/7/files")
        self.assertIsNone(self.read())
        self.assertEqual(
            memory.source_paths([{"url": "https://[malformed"}], self.repo), set()
        )

    def test_row_scan_is_bounded_and_never_claims_exhaustiveness(self):
        self.initialize()
        for id in range(1, 31):
            other = {"url": self.source["url"].replace("subject.py", "other.py")}
            self.add(
                id,
                f"https://github.com/public/project/pull/{id}",
                source=self.source if id == 1 else other,
            )
        context = self.read()
        self.assertEqual(
            [x["url"].rsplit("/", 1)[-1] for x in context["items"]], ["30", "29", "28"]
        )
        self.assertIn("not an exhaustive", context["caution"])

    def test_optional_memory_drops_before_primary_source_clipping(self):
        packet = {
            "sources": [self.source],
            "owner_publications": {"items": ["x" * 2000]},
        }
        baseline = json.loads(json.dumps(packet["sources"]))
        memory.fit_publication_context(packet, 500, "prefix")
        self.assertNotIn("owner_publications", packet)
        self.assertEqual(packet["sources"], baseline)

    def test_producer_reads_fresh_memory_but_does_not_replay_identical_evidence(self):
        self.initialize()
        config = {
            "objective": "test",
            "queue_target": 8,
            "source_windows": 2,
            "repos": [
                {"repo": self.repo, "question": "test", "source_prefixes": ["src/"]}
            ],
        }
        scout.initialize(self.root)
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        producer = research.ResearchProducer(self.root, config_path, context=object())
        spec = producer.config["repos"][0]
        self.assertTrue(producer.emit("before", spec, [self.source], "source_audit"))
        self.add(1, "https://github.com/public/project/pull/1")
        self.assertFalse(
            producer.emit("same-source-new-memory", spec, [self.source], "source_audit")
        )
        newer = {**self.source, "text": "1: changed primary source"}
        self.assertTrue(producer.emit("new-source", spec, [newer], "source_audit"))
        with scout.connect(self.root) as db:
            packets = [
                json.loads(row[0])
                for row in db.execute("SELECT packet FROM jobs ORDER BY created,id")
            ]
        self.assertEqual(len(packets), 2)
        self.assertNotIn("owner_publications", packets[0])
        self.assertEqual(
            packets[1]["owner_publications"]["items"][0]["url"],
            "https://github.com/public/project/pull/1",
        )
        self.assertEqual(packets[1]["sources"], [newer])


class SourceOnlyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = "public/project"
        self.source = {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/subject.py"
        }
        self.note = {
            "repo": self.repo,
            "prior_hypothesis": "Finite update after genuine overflow",
            "source_url": self.source["url"],
            "pr_url": "https://github.com/public/project/pull/123",
        }
        self.path = self.root / "owner-publication-notes.json"

    def write(self, notes):
        self.path.write_text(json.dumps(notes), encoding="utf-8")

    def read(self):
        return memory.publication_context(self.root, self.repo, [self.source])

    def test_source_only_link_without_queue_creates_no_delivery_or_test_verdict(self):
        self.write([self.note])
        before = self.path.read_bytes()
        context = self.read()
        self.assertEqual(context["items"][0]["url"], self.note["pr_url"])
        self.assertEqual(context["items"][0]["source_paths"], ["src/subject.py"])
        self.assertIn("not an exhaustive", context["caution"])
        self.assertEqual(
            set(context["items"][0]), {"url", "prior_hypothesis", "source_paths"}
        )
        self.assertFalse((self.root / "delivery").exists())
        self.assertEqual(self.path.read_bytes(), before)

    def test_independent_note_survives_corrupt_queue(self):
        self.write([self.note])
        directory = self.root / "delivery"
        directory.mkdir()
        db = directory / "delivery.sqlite"
        db.write_bytes(b"not a database")
        self.assertIsNotNone(self.read())
        self.assertEqual(db.read_bytes(), b"not a database")

    def test_invalid_or_extra_fields_and_private_titles_are_not_exposed(self):
        for change in (
            {"repo": "other/project"},
            {"pr_url": "https://github.com/other/project/pull/123"},
            {"pr_url": "https://github.com/public/project/issues/123"},
            {"pr_url": "https://github.com/public/project/pull/123#discussion"},
            {
                "source_url": "https://raw.githubusercontent.com/public/project/main/src/subject.py"
            },
            {
                "source_url": "https://raw.githubusercontent.com/other/project/"
                + "a" * 40
                + "/src/subject.py"
            },
            {"source_url": None},
            {"prior_hypothesis": "D:/private/run"},
            {"prior_hypothesis": "x" * 201},
            {"prior_hypothesis": None},
            {"correctness": "PASS"},
        ):
            with self.subTest(change=change):
                self.write([{**self.note, **change}])
                self.assertIsNone(self.read())

    def test_malformed_and_oversized_notes_are_optional(self):
        for value in ("null", "{}", "invalid", "[" * 2000, " " * 65537):
            self.path.write_text(value, encoding="utf-8")
            self.assertIsNone(self.read())

    def test_many_duplicates_keep_one_hint_without_discarding_history(self):
        self.write([self.note] * 25)
        before = self.path.read_bytes()
        self.assertEqual(
            [item["url"] for item in self.read()["items"]], [self.note["pr_url"]]
        )
        self.assertEqual(self.path.read_bytes(), before)

    def test_other_repositories_do_not_erase_the_current_repository_hint(self):
        others = [
            {
                **self.note,
                "repo": "other/project",
                "source_url": self.source["url"].replace(self.repo, "other/project"),
                "pr_url": f"https://github.com/other/project/pull/{i}",
            }
            for i in range(1, 25)
        ]
        self.write([self.note, *others])
        self.assertEqual(self.read()["items"][0]["url"], self.note["pr_url"])
        self.assertFalse((self.root / "delivery").exists())

    def test_reader_bounds_recent_distinct_valid_rows_per_repository(self):
        notes = [
            {**self.note, "pr_url": f"https://github.com/public/project/pull/{i}"}
            for i in range(1, 41)
        ]
        self.write([*notes, {"invalid": True}, notes[-1]])
        rows = memory.owner_publication_rows(self.root, self.repo)
        self.assertEqual(len(rows), 24)
        urls = [json.loads(result)["pr"]["url"] for _, result, _ in rows]
        self.assertEqual(
            urls,
            [f"https://github.com/public/project/pull/{i}" for i in range(40, 16, -1)],
        )
        self.assertEqual(len(self.read()["items"]), 3)

    def test_note_and_queue_duplicates_do_not_consume_extra_hint_slots(self):
        self.write([self.note, self.note])
        directory = self.root / "delivery"
        directory.mkdir()
        with closing(sqlite3.connect(directory / "delivery.sqlite")) as db, db:
            db.execute(
                "CREATE TABLE delivery(id,repo,title,state,updated_at,result,payload)"
            )
            db.execute(
                "INSERT INTO delivery VALUES(?,?,?,?,?,?,?)",
                (
                    1,
                    self.repo,
                    "old summary",
                    "PR_OPEN",
                    0,
                    json.dumps({"pr": {"url": self.note["pr_url"]}}),
                    json.dumps({"packet": {"sources": [self.source]}}),
                ),
            )
        self.assertEqual(len(self.read()["items"]), 1)

    def test_same_file_first_with_three_hint_cap(self):
        notes = [
            {
                **self.note,
                "pr_url": f"https://github.com/public/project/pull/{i}",
                "source_url": self.source["url"].replace("subject.py", f"other{i}.py"),
            }
            for i in range(1, 7)
        ]
        self.write([self.note, *notes])
        items = self.read()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["url"], self.note["pr_url"])


if __name__ == "__main__":
    unittest.main()
