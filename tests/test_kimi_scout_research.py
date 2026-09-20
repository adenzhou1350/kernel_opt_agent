"""Offline frontier tests: no GitHub, credentials, Kimi, or GPU activity."""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research


class Context:
    def __init__(self):
        self.calls = []
        self.revision = "a" * 40
        self.blob = "b" * 40
        self.issue_version = "first"

    def snapshot(self, repo, ref="main"):
        return {
            "commit": self.revision,
            "files": ["src/kernel.py", "tests/test_kernel.py"],
            "blobs": {"src/kernel.py": self.blob, "tests/test_kernel.py": "c" * 40},
        }

    def source(self, repo, commit, path, hints="", start=None):
        self.calls.append((repo, commit, path, start))
        start = start or 1
        if start > 10:
            raise ValueError("source start line is beyond end of file")
        return {
            "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
            "text": f"{start}: kernel boundary {self.blob}",
            "total_lines": 10,
        }

    def issue_page(self, repo, page=1):
        if page > 1:
            return []
        return [
            {
                "number": 42,
                "title": "kernel.py boundary",
                "body": "src/kernel.py index",
                "updated_at": self.issue_version,
                "html_url": f"https://github.com/{repo}/issues/42",
            }
        ]

    def issue_sources(self, repo, number):
        return [
            {
                "url": f"https://github.com/{repo}/issues/{number}",
                "text": "Full public report kernel.py index",
            },
            {
                "url": f"https://github.com/{repo}/issues/{number}#issuecomment-1",
                "text": "More context",
            },
        ]

    def duplicate_sources(self, repo, title):
        return [
            {
                "url": f"https://github.com/{repo}/pull/3",
                "text": "Related existing implementation",
            }
        ]


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        scout.initialize(self.root)
        self.config = self.root / "config.json"
        self.value = {
            "objective": "Find falsifiable public leads",
            "queue_target": 4,
            "repos": [
                {
                    "repo": "a/b",
                    "source_prefixes": ["src/"],
                    "question": "Check boundaries",
                }
            ],
        }
        self.config.write_text(json.dumps(self.value), encoding="utf-8")
        self.context = Context()
        self.producer = research.ResearchProducer(
            self.root, self.config, context=self.context
        )
        self.spec = self.value["repos"][0]

    def jobs(self):
        with scout.connect(self.root) as db:
            return list(db.execute("SELECT * FROM jobs ORDER BY created"))

    def finish(self, row, decision="lead"):
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state=?,result=?,finished=? WHERE id=?",
                (
                    "REVIEW" if decision == "lead" else "NO_LEAD",
                    json.dumps(
                        {
                            "analysis": {
                                "title": "kernel.py issue",
                                "next_check": "src/kernel.py boundary",
                            }
                        }
                    ),
                    time.time(),
                    row["id"],
                ),
            )

    def test_short_file_skips_past_eof_and_dedups_restart(self):
        progress = self.producer.state["repos"].setdefault("a/b", {})
        self.assertTrue(self.producer.source_audit(self.spec, progress))
        self.assertFalse(self.producer.source_audit(self.spec, progress))
        self.producer.save()
        again = research.ResearchProducer(self.root, self.config, context=self.context)
        self.assertFalse(again.source_audit(self.spec, again.state["repos"]["a/b"]))
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.context.calls[0][-1], 1)

    def test_only_changed_blob_creates_fresh_source_work(self):
        self.assertTrue(self.producer.source_audit(self.spec, {}))
        self.context.revision = "d" * 40
        self.assertFalse(self.producer.source_audit(self.spec, {}))
        self.context.blob = "e" * 40
        self.assertTrue(self.producer.source_audit(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_no_rephrasing_followup_and_two_step_cap(self):
        self.assertTrue(self.producer.issue(self.spec, {}))
        self.finish(self.jobs()[0])
        self.assertTrue(self.producer.followup(self.spec, {}))
        child = self.jobs()[-1]
        data = json.loads(child["packet"])["research"]
        self.assertEqual(data["depth"], 1)
        self.assertEqual(data["parent_job_id"], self.jobs()[0]["id"])
        self.finish(child)
        # Identical second-stage evidence costs no model call.
        self.assertFalse(self.producer.followup(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_depth_two_is_handoff_even_with_new_evidence(self):
        self.producer.issue(self.spec, {})
        root = self.jobs()[0]
        packet = json.loads(root["packet"])
        packet["research"].update(depth=2, root_job_id=root["id"])
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET packet=? WHERE id=?", (json.dumps(packet), root["id"])
            )
        self.finish(root)
        self.assertFalse(self.producer.followup(self.spec, {}))

    def test_no_lead_does_not_spawn(self):
        self.producer.issue(self.spec, {})
        self.finish(self.jobs()[0], "no_lead")
        self.assertFalse(self.producer.followup(self.spec, {}))

    def test_queue_ceiling_and_stop_are_enforced(self):
        for i in range(4):
            self.assertTrue(
                self.producer.emit(
                    str(i),
                    self.spec,
                    [{"url": "https://github.com/a/b/issues/1", "text": str(i)}],
                    "issue_triage",
                )
            )
        self.assertFalse(self.producer.tick())
        self.producer.halt.set()
        self.assertFalse(
            self.producer.emit(
                "new",
                self.spec,
                [{"url": "https://github.com/a/b/issues/1", "text": "new"}],
                "issue_triage",
            )
        )
        self.assertEqual(len(self.jobs()), 4)

    def test_hints_cannot_introduce_arbitrary_fetch_paths(self):
        paths = research.relevant_paths(
            self.context.snapshot("a/b"),
            "../../secret /etc/passwd https://evil.test/kernel.py src/kernel.py",
        )
        self.assertEqual(paths, ["src/kernel.py"])
        self.assertNotIn("secret", paths)

    def test_oversize_evidence_trimmed_with_explicit_flag(self):
        self.producer.emit(
            "large",
            self.spec,
            [{"url": "https://github.com/a/b/issues/1", "text": "汉" * 30000}],
            "issue_triage",
        )
        packet = json.loads(self.jobs()[0]["packet"])
        self.assertLessEqual(
            len((scout.SYSTEM + scout.dumps(packet)).encode()), scout.MAX_INPUT_BYTES
        )
        self.assertTrue(packet["sources"][0]["truncated"])

    def test_issue_updated_at_only_new_issue_packets(self):
        self.assertTrue(self.producer.issue(self.spec, {}))
        self.assertFalse(self.producer.issue(self.spec, {}))
        self.context.issue_version = "second"
        # Content dedup in enqueue still prevents paying for identical evidence.
        self.assertFalse(self.producer.issue(self.spec, {}))
        self.assertEqual(len(self.jobs()), 1)

    def test_config_rejects_unsafe_prefix_and_duplicate_repos(self):
        self.value["repos"][0]["source_prefixes"] = ["../private"]
        self.config.write_text(json.dumps(self.value))
        with self.assertRaises(ValueError):
            research.configuration(self.config)

    def test_snapshot_published_no_model_or_credential_data(self):
        self.producer.publish("READY")
        value = json.loads((self.root / "research.json").read_text())
        self.assertEqual(value["queue_target"], 4)
        self.assertEqual(value["phase"], "READY")
        self.assertEqual(value["goals"][0]["repo"], "a/b")

    def test_unsupported_source_does_not_stall_frontier(self):
        progress = {}
        with patch.object(
            self.context,
            "source",
            side_effect=ValueError("binary source is not supported"),
        ):
            self.assertFalse(self.producer.source_audit(self.spec, progress))
        self.assertEqual(progress["skipped_sources"], 1)
        self.assertGreater(progress["sources_after"], time.time())

    def test_stop_during_context_prevents_later_fetch_and_enqueue(self):
        self.producer.issue(self.spec, {})
        self.finish(self.jobs()[0])
        original = self.context.issue_sources

        def cancel(*args):
            self.producer.halt.set()
            return original(*args)

        with (
            patch.object(self.context, "issue_sources", side_effect=cancel),
            patch.object(self.context, "duplicate_sources") as duplicate,
        ):
            self.assertFalse(self.producer.followup(self.spec, {}))
        duplicate.assert_not_called()
        self.assertEqual(len(self.jobs()), 1)

    def test_duplicate_search_does_not_replace_full_issue_context(self):
        self.producer.emit(
            "one",
            self.spec,
            [
                {"url": "https://github.com/a/b/issues/1", "text": "full source"},
                {"url": "https://github.com/a/b/issues/1", "text": "search snippet"},
            ],
            "source_followup",
        )
        self.assertEqual(
            json.loads(self.jobs()[0]["packet"])["sources"][0]["text"], "full source"
        )

    def test_cli_rejects_two_producers_and_once(self):
        with self.assertRaises(SystemExit):
            scout.main(
                [
                    "--root",
                    str(self.root),
                    "run",
                    "--kimi-python",
                    sys.executable,
                    "--research",
                    str(self.config),
                    "--feeds",
                    "unused",
                ]
            )
        self.assertEqual(
            scout.main(
                [
                    "--root",
                    str(self.root),
                    "run",
                    "--kimi-python",
                    sys.executable,
                    "--research",
                    str(self.config),
                    "--once",
                ]
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
