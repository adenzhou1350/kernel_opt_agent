"""The opt-in scope retains native-test and real-production-report boundaries."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import kimi_scout_research as research


class MoreItertoolsScopeTests(unittest.TestCase):
    def setUp(self):
        config = research.configuration(ROOT / "templates/kimi-scout-research-wide.json")
        self.spec = next(s for s in config["repos"] if s["repo"] == "more-itertools/more-itertools")

    def test_only_implementation_paths_and_mutable_default_branch(self):
        self.assertEqual(self.spec["ref"], "master")
        self.assertEqual(self.spec["source_windows"], 6)
        self.assertEqual(research.source_paths({"files": [
            "more_itertools/more.py", "more_itertools/recipes.py",
            "more_itertools/__init__.py", "tests/test_more.py", "README.rst",
        ]}, self.spec), ["more_itertools/more.py", "more_itertools/recipes.py"])

    def test_production_report_and_unqualified_sandbox_are_explicit(self):
        question = self.spec["question"]
        for required in ("issue before a PR", "production-code examples", "contrived examples",
                         "do not weaken", "baseline testability", "independent reproduction"):
            self.assertIn(required, question)
        self.assertTrue(self.spec["followup_discussion_context"])
        self.assertTrue(self.spec["followup_issue_body_context"])


if __name__ == "__main__":
    unittest.main()
