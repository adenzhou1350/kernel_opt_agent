"""Offline observed-tree ambiguity controls; no model, GitHub or source reads."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from tests.test_kimi_scout_research import Context

ORACLE = "vllm/model_executor/layers/fused_moe/oracle/mxfp4.py"
QUANT = "vllm/model_executor/layers/quantization/mxfp4.py"


class SameNameChoicesTests(unittest.TestCase):
    def test_wrong_namespace_is_visible_without_claiming_definition(self):
        paths = research.relevant_paths({"files": [QUANT, ORACLE]}, "Inspect mxfp4.py")
        self.assertEqual(paths, [ORACLE, QUANT])
        result = research.same_name_choices(paths, "Inspect mxfp4.py")
        self.assertEqual(result["selected_path"], ORACLE)
        self.assertEqual(result["same_name_candidates"], [ORACLE, QUANT])
        self.assertIn("alternatives are not read", result["scope"])
        self.assertIn("not proof of symbol ownership", result["scope"])

    def test_single_explicit_observed_path_does_not_add_noise(self):
        hints = f"Inspect {QUANT}"
        paths = research.relevant_paths({"files": [ORACLE, QUANT]}, hints)
        self.assertEqual(paths[0], QUANT)
        self.assertIsNone(research.same_name_choices(paths, hints))

    def test_two_explicit_paths_remain_multiple_candidates(self):
        result = research.same_name_choices([ORACLE, QUANT], f"Compare {ORACLE} and {QUANT}")
        self.assertEqual(result["same_name_candidates"], [ORACLE, QUANT])

    def test_absent_or_unique_names_do_not_add_a_choice(self):
        for paths in ([], [ORACLE], [ORACLE, "src/other.py"]):
            self.assertIsNone(research.same_name_choices(paths, "mxfp4.py"))

    def test_candidates_are_unique_bounded_and_omissions_are_explicit(self):
        paths = [f"src/variant{i}/table.rs" for i in range(20)]
        result = research.same_name_choices(paths + paths, "table.rs")
        self.assertEqual(result["same_name_candidates"], paths[:5])
        self.assertEqual(result["omitted_candidates"], 15)

    def test_excluded_absent_paths_cannot_be_suggested(self):
        paths = research.relevant_paths({"files": [ORACLE, QUANT]},
                                        "src/absent/mxfp4.py", exclude=[QUANT])
        self.assertEqual(paths, [ORACLE])
        self.assertIsNone(research.same_name_choices(paths, "src/absent/mxfp4.py"))

    def test_input_bound_matches_the_existing_ranker(self):
        self.assertIsNotNone(research.same_name_choices([ORACLE, QUANT], "x" * 16000 + ORACLE))

    def test_issue_packet_preserves_choices_without_an_extra_source_read(self):
        class Reader(Context):
            def snapshot(self, repo, ref="main"):
                return {"commit": self.revision, "files": [ORACLE, QUANT],
                        "blobs": {ORACLE: self.blob, QUANT: self.blob}}

            def issue_page(self, repo, page=1):
                return [{"number": 42, "title": "Inspect mxfp4.py", "body": "Find its owner",
                         "updated_at": "first", "html_url": f"https://github.com/{repo}/issues/42"}]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            config.write_text(json.dumps({"objective": "Offline source selection", "queue_target": 4,
                                         "repos": [{"repo": "a/b", "source_prefixes": ["vllm/"],
                                                    "question": "Inspect the real implementation"}]}), encoding="utf-8")
            reader = Reader()
            with patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}):
                producer = research.ResearchProducer(root, config, context=reader)
                self.assertTrue(producer.issue(producer.config["repos"][0], {}))
            self.assertEqual(len(reader.calls), 1)
            self.assertEqual(reader.calls[0][2], ORACLE)
            with scout.connect(root) as db:
                packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            primary = next(source for source in packet["sources"]
                           if source["url"].startswith("https://raw.githubusercontent.com/"))
            self.assertIn(f"/{reader.revision}/{ORACLE}", primary["url"])
            self.assertEqual(primary["path_selection"]["same_name_candidates"], [ORACLE, QUANT])
            self.assertLessEqual(len((scout.SYSTEM + scout.dumps(packet)).encode()), scout.MAX_INPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
