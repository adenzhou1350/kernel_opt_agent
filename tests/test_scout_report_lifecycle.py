"""Preserve current report lifecycle without inventing fix/merge verdicts."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context
import kimi_scout as scout
import kimi_scout_research as research

REPO = "owner/project"
API = f"https://api.github.com/repos/{REPO}"


class ReportLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.context = context.PublicContext(Path(temp.name), github_auth=True)
        self.item = {
            "number": 42,
            "title": "An old report",
            "body": "Unchanged body",
            "comments": 0,
            "state": "open",
            "state_reason": None,
        }
        self.calls = []
        mock = patch.object(context.scout, "fetch", side_effect=self.fetch)
        mock.start()
        self.addCleanup(mock.stop)

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        if url == API:
            return json.dumps(
                {"private": False, "visibility": "public", "full_name": REPO}
            )
        if url == API + "/issues/42":
            return json.dumps(self.item)
        raise AssertionError(f"Unexpected added request: {url}")

    def test_open_closed_reopened_are_refetched_without_extra_gets(self):
        reports = []
        for state, reason in [
            ("open", None),
            ("closed", "completed"),
            ("open", "reopened"),
        ]:
            self.item.update(state=state, state_reason=reason)
            with patch.object(context.time, "time", return_value=1000):
                reports.append(self.context.issue_sources(REPO, 42)[0])
            self.assertEqual(reports[-1]["observed_report_state"], state)
            self.assertEqual(reports[-1]["observed_report_state_reason"], reason)
            self.assertEqual(reports[-1]["lifecycle_observed_at"], 1000)
        self.assertEqual(
            len(self.calls), 4
        )  # One public check, three existing issue GETs.
        self.assertEqual(len({report["text"] for report in reports}), 1)
        self.assertEqual(reports[1]["observed_report_kind"], "issue")
        self.assertIn("not fix, merge", reports[1]["lifecycle_scope"])
        self.assertNotIn("fixed", reports[1])

    def test_closed_unplanned_is_not_discarded(self):
        self.item.update(state="closed", state_reason="not_planned")
        report = self.context.issue_sources(REPO, 42)[0]
        self.assertEqual(report["observed_report_state_reason"], "not_planned")
        self.assertIn("Unchanged body", report["text"])
        self.assertNotIn("decision", report)
        self.assertEqual(len(self.calls), 2)

    def test_closed_pull_is_not_inferred_merged(self):
        self.item.update(state="closed", pull_request={"url": API + "/pulls/42"})
        report = self.context.issue_sources(REPO, 42)[0]
        self.assertEqual(report["observed_report_kind"], "pull_request")
        self.assertEqual(report["url"], f"https://github.com/{REPO}/pull/42")
        self.assertNotIn("merged", report)
        self.assertEqual(len(self.calls), 2)

    def test_unknown_or_malformed_lifecycle_is_explicit_not_assumed_open(self):
        for state, reason in [(None, None), ("unsupported", "new_reason"), ([], {})]:
            with self.subTest(state=state, reason=reason):
                self.item.update(state=state, state_reason=reason)
                report = self.context.issue_sources(REPO, 42)[0]
                self.assertEqual(report["observed_report_state"], "unknown")
                self.assertIsNone(report["observed_report_state_reason"])

    def test_closed_report_keeps_bounded_comments(self):
        self.item.update(state="closed", comments=1)
        original_fetch = self.fetch

        def with_comments(url, **kwargs):
            if "/comments?" in url:
                self.calls.append(url)
                return json.dumps(
                    [{"id": 9, "body": "Still broken on the release branch"}]
                )
            return original_fetch(url, **kwargs)

        with patch.object(context.scout, "fetch", side_effect=with_comments):
            reports = self.context.issue_sources(REPO, 42)
        self.assertEqual(len(reports), 2)
        self.assertIn("Still broken", reports[1]["text"])
        self.assertEqual(len(self.calls), 3)

    def test_dedup_keeps_state_change_but_ignores_observation_time(self):
        first = self.context.issue_sources(REPO, 42)[0]
        later = dict(first, lifecycle_observed_at=first["lifecycle_observed_at"] + 100)
        closed = dict(
            later,
            observed_report_state="closed",
            observed_report_state_reason="completed",
        )
        unplanned = dict(closed, observed_report_state_reason="not_planned")
        for identity in (research.evidence_identity, research.retrieval_identity):
            self.assertEqual(identity(first), identity(later))
            self.assertNotEqual(identity(first), identity(closed))
            self.assertNotEqual(identity(closed), identity(unplanned))
            self.assertEqual(identity(closed), identity(dict(closed)))
        trimmed = dict(first, text="Shorter excerpt", _scout_pretrim_sha256="a" * 64)
        self.assertEqual(
            research.retrieval_identity(trimmed),
            research.retrieval_identity(
                dict(trimmed, text="Another trim", lifecycle_observed_at=0)
            ),
        )
        self.assertNotEqual(
            research.retrieval_identity(trimmed),
            research.retrieval_identity(dict(trimmed, observed_report_state="closed")),
        )

    def test_metadata_on_code_or_wrong_report_kind_does_not_change_identity(self):
        report = self.context.issue_sources(REPO, 42)[0]
        for url, kind, state in [
            (
                f"https://raw.githubusercontent.com/{REPO}/{'a' * 40}/src/kernel.py",
                "issue",
                "closed",
            ),
            (report["url"], "pull_request", "closed"),
            (report["url"] + "#issuecomment-1", "issue", "closed"),
            (report["url"], "issue", []),
        ]:
            with self.subTest(url=url, kind=kind, state=state):
                plain = {"url": url, "text": "Same evidence"}
                decorated = dict(
                    plain, observed_report_kind=kind, observed_report_state=state
                )
                for identity in (
                    research.evidence_identity,
                    research.retrieval_identity,
                ):
                    self.assertEqual(identity(plain), identity(decorated))

    def test_actual_emit_preserves_state_only_change_and_dedups_time_only_change(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            scout.initialize(root)
            spec = {
                "repo": REPO,
                "question": "Check current evidence",
                "source_prefixes": ["src/"],
            }
            config = root / "config.json"
            scout.write_json(
                config,
                {
                    "objective": "Test lifecycle evidence",
                    "queue_target": 4,
                    "repos": [spec],
                },
            )
            producer = research.ResearchProducer(root, config, context=self.context)
            report = self.context.issue_sources(REPO, 42)[0]
            self.assertTrue(producer.emit("open", spec, [report], "source_followup"))
            self.assertFalse(
                producer.emit(
                    "time-only",
                    spec,
                    [dict(report, lifecycle_observed_at=0)],
                    "source_followup",
                )
            )
            self.assertTrue(
                producer.emit(
                    "closed",
                    spec,
                    [
                        dict(
                            report,
                            observed_report_state="closed",
                            observed_report_state_reason="completed",
                        )
                    ],
                    "source_followup",
                )
            )
            with scout.connect(root) as db:
                rows = db.execute(
                    "SELECT packet FROM jobs ORDER BY created,id"
                ).fetchall()
            states = {
                json.loads(row["packet"])["sources"][0]["observed_report_state"]
                for row in rows
            }
            self.assertEqual(states, {"open", "closed"})
            self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
