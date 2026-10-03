"""EOF discovery context preserves evidence; no model/network execution."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_audit_context import contextual_audit_tail


REPO = "owner/project"
COMMIT = "a" * 40
PATH = "src/retry.ts"


class AuditTailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = PublicContext(self.temp.name)
        self.snapshot = patch.object(
            self.context, "snapshot", return_value={"files": [PATH]}
        )
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)

    def expanded(self, raw, start):
        with patch.object(self.context, "_read", return_value=raw) as read:
            source = self.context.source(REPO, COMMIT, PATH, start=start)
            result = contextual_audit_tail(self.context, REPO, COMMIT, PATH, source)
        # The extra excerpt uses the acquired immutable file, not another GET.
        self.assertEqual(read.call_count, 1)
        return source, result

    def test_one_line_closing_brace_gains_context_with_exact_tail_preserved(self):
        raw = "\n".join([f"statement_{i};" for i in range(1, 241)] + ["}"])
        source, result = self.expanded(raw, 241)
        self.assertEqual(source["text"], "241: }")
        self.assertEqual((result["start_line"], result["end_line"]), (122, 241))
        self.assertTrue(result["text"].endswith(source["text"]))
        self.assertEqual(len(result["text"].splitlines()), 120)
        self.assertTrue(result["truncated"])  # Still not full-function coverage.

    def test_short_nontrivial_tail_is_retained_not_suppressed(self):
        raw = "\n".join(["body;" for _ in range(240)] + ["return risky();", "}"])
        source, result = self.expanded(raw, 241)
        self.assertIn("241: return risky();", result["text"])
        self.assertTrue(result["text"].endswith(source["text"]))
        self.assertEqual(result["end_line"], 242)

    def test_first_window_is_unchanged(self):
        source, result = self.expanded("tiny();\n}", 1)
        self.assertIs(result, source)

    def test_24_line_tail_is_unchanged(self):
        source, result = self.expanded("line;\n" * 264, 241)
        self.assertIs(result, source)

    def test_character_clipping_must_not_lose_the_original_tail(self):
        raw = "\n".join(["x" * 200 for _ in range(240)] + ["return meaningful();"])
        source, result = self.expanded(raw, 241)
        self.assertIs(result, source)
        self.assertIn("return meaningful();", result["text"])

    def test_partial_excerpt_or_missing_bounds_does_not_guess(self):
        base = {"start_line": 241, "end_line": 241, "total_lines": 242,
                "text": "241: line;"}
        for source in (base, {**base, "end_line": None}, {"text": "}"}):
            with patch.object(self.context, "source") as fetch:
                self.assertIs(
                    contextual_audit_tail(self.context, REPO, COMMIT, PATH, source),
                    source,
                )
                fetch.assert_not_called()

    def test_mismatched_url_and_optional_budget_failure_keep_original(self):
        source = {"url": "original", "start_line": 241, "end_line": 241,
                  "total_lines": 241, "text": "241: }"}
        with patch.object(self.context, "source", return_value={
            **source, "url": "wrong", "start_line": 122,
        }):
            self.assertIs(
                contextual_audit_tail(self.context, REPO, COMMIT, PATH, source), source
            )
        with patch.object(self.context, "source",
                          side_effect=ValueError("public source exceeds read budget")):
            self.assertIs(
                contextual_audit_tail(self.context, REPO, COMMIT, PATH, source), source
            )


if __name__ == "__main__":
    unittest.main()
