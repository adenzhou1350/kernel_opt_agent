"""Opted-in evaluator YAML stays bounded inert public-source evidence."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research


PREFIX = "model/evaluators/"
YAML = PREFIX + "accuracy.yaml"


class Context:
    def source(self, repo, commit, path, **kwargs):
        return {"url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                "text": "1: evaluate: |\n2:   return 0.0", "total_lines": 2}

    def snapshot(self, repo, ref="main"):
        raise AssertionError("Tests must supply their observed snapshot explicitly")


class DeclarativeSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scout.initialize(self.root)
        self.spec = {"repo": "a/b", "source_prefixes": [PREFIX],
                     "question": "Check evaluator numerical contracts."}
        self.config = self.root / "config.json"
        self.snapshot = {"commit": "a" * 40, "files": [YAML],
                         "blobs": {YAML: "b" * 40}}
        self.context = Context()

    def configure(self):
        self.config.write_text(json.dumps({"objective": "test", "queue_target": 4,
                                          "source_windows": 1, "repos": [self.spec]}))
        return research.ResearchProducer(self.root, self.config, context=self.context)

    def test_default_and_unselected_declarative_paths_remain_excluded(self):
        files = [YAML, PREFIX + "other.yml", PREFIX + "kernel.py",
                 PREFIX + "tests/test_fixture.yaml", PREFIX + "vendor/raw.yaml",
                 PREFIX + "generated/raw.yaml", "ee/evaluator.yaml",
                 "model/evaluators-other/accuracy.yaml", PREFIX + "secret.toml"]
        snapshot = dict(self.snapshot, files=files)
        self.assertEqual(research.source_paths(snapshot, self.spec), [PREFIX + "kernel.py"])
        self.spec["declarative_source_prefixes"] = [PREFIX]
        self.assertEqual(research.source_paths(snapshot, self.spec),
                         [YAML, PREFIX + "kernel.py", PREFIX + "other.yml"])
        self.assertNotIn(".yaml", research.SOURCE_SUFFIXES)

    def test_configuration_rejects_unscoped_or_unsafe_declarative_directories(self):
        for value in (None, True, PREFIX, [None], [""], ["/"], ["ee/"],
                      ["model/"], [PREFIX + "../"], [PREFIX + "*/"],
                      [PREFIX + "bad\\/"], [PREFIX + "bad\n/"], [YAML],
                      [PREFIX] * 9):
            with self.subTest(value=value):
                self.spec["declarative_source_prefixes"] = value
                with self.assertRaisesRegex(ValueError, "declarative source"):
                    self.configure()
        self.spec["declarative_source_prefixes"] = [PREFIX]
        self.configure()

    def test_changed_selection_reopens_empty_sweep_and_preserves_seen_keys(self):
        producer = self.configure()
        progress = {}
        with patch.object(self.context, "snapshot", return_value=self.snapshot):
            self.assertFalse(producer.source_audit(self.spec, progress))
            self.assertGreater(progress["sources_after"], 0)
            self.spec["declarative_source_prefixes"] = [PREFIX]
            self.assertTrue(producer.source_audit(self.spec, progress))
            self.assertEqual(progress["available_sources"], 1)
            self.assertFalse(producer.source_audit(self.spec, progress))
            self.spec["declarative_source_prefixes"] = []
            self.assertFalse(producer.source_audit(self.spec, progress))
            self.spec["declarative_source_prefixes"] = [PREFIX]
            self.assertFalse(producer.source_audit(self.spec, progress))
        with scout.connect(self.root) as db:
            rows = db.execute("SELECT packet FROM jobs").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn(YAML, json.loads(rows[0][0])["sources"][0]["url"])

    def test_yaml_payload_is_queued_as_text_without_parsing_or_execution(self):
        self.spec["declarative_source_prefixes"] = [PREFIX]
        producer = self.configure()
        text = "1: !!python/object/apply:os.system\n2: evaluate: |\n3:   raise RuntimeError('inert')"
        def source(repo, commit, path, **kwargs):
            return {"url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                    "text": text, "total_lines": 3}
        with patch.object(self.context, "snapshot", return_value=self.snapshot), \
                patch.object(self.context, "source", side_effect=source):
            self.assertTrue(producer.source_audit(self.spec, {}))
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertIn(text, packet["sources"][0]["text"])

    def test_followup_ranking_and_continuation_use_same_opt_in_scope(self):
        self.spec["declarative_source_prefixes"] = [PREFIX]
        snapshot = dict(self.snapshot, files=[YAML, "ee/accuracy.yaml"])
        self.assertEqual(research.relevant_paths(snapshot, "accuracy.yaml"), [])
        self.assertEqual(research.relevant_paths(snapshot, "accuracy.yaml", spec=self.spec), [YAML])
        packet = {"repo": "a/b", "sources": [{
            "url": "https://raw.githubusercontent.com/a/b/" + "a" * 40 + "/" + YAML,
            "start_line": 1, "end_line": 120, "total_lines": 180, "truncated": True}]}
        analysis = {"next_check": "Read after line 120"}
        self.assertIsNone(research.continuation_request(packet, snapshot, analysis))
        self.assertEqual(research.continuation_request(packet, snapshot, analysis, spec=self.spec),
                         {"path": YAML, "start": 101, "max_lines": 120})
        packet["sources"][0]["url"] = packet["sources"][0]["url"].replace(YAML, "ee/accuracy.yaml")
        self.assertIsNone(research.continuation_request(packet, snapshot, analysis, spec=self.spec))


if __name__ == "__main__":
    unittest.main()
