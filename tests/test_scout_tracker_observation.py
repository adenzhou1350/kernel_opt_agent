"""Offline tracker observation tests: no model, network, GPU or WSL."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from tests.test_kimi_scout_research import Context


class TrackerObservationTests(unittest.TestCase):
    def test_valid_declared_range_and_truncation(self):
        result = research.tracker_observation(
            {
                "body": "<!-- ci-failure-tracker:start -->\n"
                '{"last_seen": "2026-09-03"}\n{"last_seen": "2026-09-01"}\n'
                '{"last_seen": "2026-99-99"}',
                "truncated": True,
            }
        )
        self.assertEqual(result["declared_last_seen_min"], "2026-09-01")
        self.assertEqual(result["declared_last_seen_max"], "2026-09-03")
        self.assertTrue(result["body_truncated"])
        self.assertIn("do not discard", result["scope"])

    def test_missing_dates_are_unknown(self):
        result = research.tracker_observation(
            {"body": "<!-- ci-failure-tracker:start --> no retained dates"}
        )
        self.assertIsNone(result["declared_last_seen_min"])
        self.assertIsNone(result["declared_last_seen_max"])

    def test_ordinary_report_is_not_a_tracker(self):
        self.assertIsNone(
            research.tracker_observation({"body": '{"last_seen": "2026-09-01"}'})
        )
        self.assertIsNone(research.tracker_observation({"body": None}))

    def test_issue_packet_keeps_hint_and_timestamp_update_does_not_requeue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scout.initialize(root)
            config = root / "config.json"
            spec = {
                "repo": "a/b",
                "source_prefixes": ["src/"],
                "question": "Check boundaries",
            }
            config.write_text(
                json.dumps(
                    {
                        "objective": "Find falsifiable leads",
                        "queue_target": 4,
                        "repos": [spec],
                    }
                ),
                encoding="utf-8",
            )
            context = Context()
            producer = research.ResearchProducer(root, config, context=context)
            item = context.issue_page("a/b")[0]
            item["body"] = (
                "<!-- ci-failure-tracker:start --> src/kernel.py\n"
                + "retained history\n" * 500
                + '{"last_seen": "2026-09-01"}\n'
            )
            with patch.object(context, "issue_page", return_value=[item]):
                self.assertTrue(producer.issue(spec, {}))
            with scout.connect(root) as db:
                packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            observation = packet["sources"][0]["tracker_observation"]
            self.assertEqual(observation["declared_last_seen_max"], "2026-09-01")
            identity = research.evidence_identity(packet["sources"][0])
            altered = dict(
                packet["sources"][0], tracker_observation={"different": True}
            )
            self.assertEqual(research.evidence_identity(altered), identity)
            item["updated_at"] = "second"
            with patch.object(context, "issue_page", return_value=[item]):
                self.assertFalse(producer.issue(spec, {}))
            with scout.connect(root) as db:
                self.assertEqual(
                    db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1
                )
