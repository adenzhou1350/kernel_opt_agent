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

    def test_deferrals_missing_or_unavailable_history_is_optional(self):
        self.assertIsNone(self.deferrals())
        self.assertFalse(self.path.parent.exists())
        self.initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE delivery")
        before = self.path.read_bytes()
        self.assertIsNone(self.deferrals())
        self.assertEqual(self.path.read_bytes(), before)

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


if __name__ == "__main__":
    unittest.main()
