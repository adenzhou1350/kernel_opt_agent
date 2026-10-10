"""Recover optional advice only from bytes left after primary-source fitting."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout  # noqa: E402
import kimi_scout_research as research  # noqa: E402
import scout_publication_context as memory  # noqa: E402


def size(packet, prefix=""):
    return len((prefix + scout.dumps(packet)).encode("utf-8"))


class AdviceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.packet = {
            "sources": [{"url": "https://example.com/source", "text": "证据" * 100}],
            "untrusted_prior_analysis": "unchanged prior analysis",
        }
        self.context = {
            "caution": "Advice, never an automatic verdict.",
            "items": [{"reason": "已有对照", "reopen_when": "新证据"}, {"reason": "B"}],
        }

    def test_full_advice_exact_byte_boundary_preserves_primary_fields(self):
        before = copy.deepcopy(self.packet)
        prefix = "系统\n"
        expected = {**self.packet, "owner_deferrals": self.context}
        memory.restore_publication_context(
            self.packet,
            {"owner_deferrals": self.context},
            size(expected, prefix),
            prefix,
        )
        self.assertEqual(self.packet, expected)
        self.assertEqual(self.packet["sources"], before["sources"])
        self.assertEqual(
            self.packet["untrusted_prior_analysis"], before["untrusted_prior_analysis"]
        )

    def test_only_complete_prefix_items_fit_without_mutating_context(self):
        before = copy.deepcopy(self.context)
        one = {**self.context, "items": self.context["items"][:1]}
        expected = {**self.packet, "owner_deferrals": one}
        memory.restore_publication_context(
            self.packet, {"owner_deferrals": self.context}, size(expected)
        )
        self.assertEqual(self.packet, expected)
        self.assertEqual(self.context, before)

    def test_no_space_or_one_byte_short_does_not_change_packet(self):
        before = copy.deepcopy(self.packet)
        one = {**self.context, "items": self.context["items"][:1]}
        for cap in (
            size(self.packet) - 1,
            size({**self.packet, "owner_deferrals": one}) - 1,
        ):
            memory.restore_publication_context(
                self.packet, {"owner_deferrals": self.context}, cap
            )
            self.assertEqual(self.packet, before)

    def test_existing_advice_not_evicted_and_unknown_fields_ignored(self):
        self.packet["owner_deferrals"] = {"items": [{"reason": "already present"}]}
        before = copy.deepcopy(self.packet)
        memory.restore_publication_context(
            self.packet,
            {"owner_deferrals": self.context, "unknown": self.context},
            10000,
        )
        self.assertEqual(self.packet, before)

    def test_both_contexts_share_one_cap(self):
        expected = {**self.packet, "owner_deferrals": self.context}
        memory.restore_publication_context(
            self.packet,
            {"owner_deferrals": self.context, "owner_publications": self.context},
            size(expected),
        )
        self.assertEqual(self.packet, expected)

    def test_emitter_recovers_advice_after_clipping_same_source_without_extra_reads(
        self,
    ):
        source = {
            "url": f"https://raw.githubusercontent.com/public/project/{'a' * 40}/src/x.py",
            "text": "source evidence\n" * 900,
        }
        context = {
            "caution": "Never reject automatically",
            "items": [{"reason": "old"}],
        }

        def emit(restore):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                scout.initialize(root)
                spec = {
                    "repo": "public/project",
                    "question": "test",
                    "source_prefixes": ["src/"],
                }
                config = root / "config.json"
                config.write_text(
                    json.dumps(
                        {"objective": "test", "queue_target": 8, "repos": [spec]}
                    ),
                    encoding="utf-8",
                )
                producer = research.ResearchProducer(root, config, context=object())
                with (
                    patch.object(scout, "MAX_INPUT_BYTES", 12000),
                    patch.object(
                        research, "publication_context", return_value=None
                    ) as pubs,
                    patch.object(
                        research, "owner_deferral_context", return_value=context
                    ) as notes,
                    patch.object(research, "restore_publication_context", restore),
                ):
                    self.assertTrue(
                        producer.emit(
                            "first", spec, [copy.deepcopy(source)], "discovery"
                        )
                    )
                    self.assertFalse(
                        producer.emit(
                            "same", spec, [copy.deepcopy(source)], "discovery"
                        )
                    )
                    self.assertEqual(pubs.call_count, 1)
                    self.assertEqual(notes.call_count, 1)
                with scout.connect(root) as db:
                    rows = db.execute("SELECT packet FROM jobs").fetchall()
                self.assertEqual(len(rows), 1)
                return json.loads(rows[0][0])

        baseline = emit(lambda *args: None)
        actual = emit(memory.restore_publication_context)
        self.assertNotIn("owner_deferrals", baseline)
        self.assertEqual(actual.pop("owner_deferrals"), context)
        self.assertEqual(actual, baseline)
        self.assertLess(len(actual["sources"][0]["text"]), len(source["text"]))
        self.assertLessEqual(
            size({**actual, "owner_deferrals": context}, scout.SYSTEM), 12000
        )


if __name__ == "__main__":
    unittest.main()
