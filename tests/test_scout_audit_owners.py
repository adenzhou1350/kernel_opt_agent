"""Pinned Python ownership hints never execute code or fetch more evidence."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_audit_context import contextual_audit_owners

REPO, COMMIT, PATH = "owner/project", "a" * 40, "src/producers.py"


class AuditOwnersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.context = PublicContext(self.tmp.name)

    def acquire(self, raw, start=1, count=120):
        with patch.object(self.context, "snapshot", return_value={"files": [PATH]}), \
                patch.object(self.context, "_read", return_value=raw):
            return self.context.source(REPO, COMMIT, PATH, start=start, max_lines=count)

    def annotate(self, source, path=PATH):
        with patch.object(self.context, "source", side_effect=AssertionError("fetch")), \
                patch.object(self.context, "_read", side_effect=AssertionError("network")):
            return contextual_audit_owners(self.context, REPO, COMMIT, path, source)

    def test_mid_function_window_identifies_two_distinct_producers(self):
        raw = ("def compile_topk_reduce():\n    return (1, 2, 3, 4, 5)\n\n"
               "def compile_persistent_topk_reduce():\n"
               + "    x = 1\n" * 125 + "    return (1, 2, 3, 4, 5, 6, 7)\n\n"
               "def launch_compiled_topk_reduce(a, b, c, d, e):\n    pass\n")
        source = self.acquire(raw, start=120)
        result = self.annotate(source)
        info = result["python_definition_context"]
        self.assertEqual([d["qualified_name"] for d in info["definitions"]],
                         ["compile_persistent_topk_reduce", "launch_compiled_topk_reduce"])
        self.assertEqual(info["definitions"][0]["start_line"], 4)
        self.assertEqual(result["text"], source["text"])
        self.assertNotIn("complete", info["definitions"][0])

    def test_nested_async_methods_keep_qualified_names(self):
        raw = "class A:\n    async def run(self):\n        def inner():\n            return 1\n        return inner()\n"
        info = self.annotate(self.acquire(raw, 4, 1))["python_definition_context"]
        self.assertEqual([d["qualified_name"] for d in info["definitions"]],
                         ["A.run", "A.run.inner"])
        self.assertEqual((info["window_start_line"], info["window_end_line"]), (4, 4))

    def test_string_fake_declaration_is_not_a_definition(self):
        raw = 'payload = """def counterfeit():\n    return 7\n"""\n'
        source = self.acquire(raw)
        self.assertIs(self.annotate(source), source)

    def test_syntax_cache_content_and_identity_uncertainty_abstain(self):
        source = self.acquire("def real():\n    return 1\n")
        for record in ({"url": source["url"], "text": "def (:"},
                       {"url": source["url"], "text": "def fake():\n    return 1\n"},
                       {"url": "https://example.invalid", "text": "def real():\n    return 1\n"},
                       None):
            with self.subTest(record=record), patch.object(self.context, "_load", return_value=record):
                self.assertIs(self.annotate(source), source)
        wrong_url = {**source, "url": source["url"].replace(COMMIT, "b" * 40)}
        self.assertIs(self.annotate(wrong_url), wrong_url)

    def test_non_python_bounds_and_partially_clipped_line_abstain(self):
        source = self.acquire("def real():\n    return 1\n")
        for changed in ({**source, "start_line": True}, {**source, "end_line": 99},
                        {**source, "text": source["text"][:-1]}):
            self.assertIs(self.annotate(changed), changed)
        self.assertIs(self.annotate(source, path="src/producers.cpp"), source)

    def test_metadata_is_bounded_and_marks_omitted_definitions(self):
        raw = "\n".join(f"def f{i}():\n    pass" for i in range(40))
        info = self.annotate(self.acquire(raw))["python_definition_context"]
        self.assertEqual(len(info["definitions"]), 4)
        self.assertTrue(info["omitted"])
        self.assertLess(len(json.dumps(info)), 1600)

    def test_invalid_full_file_and_oversize_cache_do_not_parse(self):
        source = self.acquire("def real():\n    return 1\ntrailing(\n")
        self.assertIs(self.annotate(source), source)
        with patch.object(self.context, "_load", return_value={"url": source["url"], "text": "x" * 1_000_001}):
            self.assertIs(self.annotate(source), source)

    def test_long_unicode_names_are_omitted_under_byte_budget(self):
        raw = "def short():\n    pass\ndef " + "界" * 100 + "():\n    pass\n"
        info = self.annotate(self.acquire(raw))["python_definition_context"]
        self.assertEqual(len(info["definitions"]), 1)
        self.assertTrue(info["omitted"])
        self.assertLess(len(json.dumps(info).encode()), 1600)


if __name__ == "__main__":
    unittest.main()
