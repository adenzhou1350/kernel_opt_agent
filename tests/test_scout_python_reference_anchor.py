"""A pinned code-search window must not mistake an import for a Python caller."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext  # noqa: E402
from scout_symbol_references import python_invocation_hint_line  # noqa: E402
import kimi_scout as scout  # noqa: E402
from kimi_scout_research import ResearchProducer  # noqa: E402


class PythonReferenceAnchorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.reader = PublicContext(Path(temporary.name))

    def source(self, raw, *, request="references(target)", exact_hint="target", path="pkg/caller.py", start=None):
        data = raw.encode()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        snapshot = {"commit": "a" * 40, "files": [path], "blobs": {path: blob}}
        with (
            patch.object(self.reader, "snapshot", return_value=snapshot),
            patch.object(self.reader, "_read", return_value=raw) as read,
        ):
            result = self.reader.source(
                "a/b", "a" * 40, path, exact_hint=exact_hint, request_hints=request,
                start=start, max_lines=80,
            )
        return result, read.call_count

    def test_explicit_reference_shows_literal_two_item_caller_not_import(self):
        raw = (
            "from .concurrency import target\n"
            "# target([]) is a comment\n"
            'example = "target([])"\n'
            + "\n" * 200
            + "async def info(self):\n"
            "    async with target([self.object(), self.directory()]):\n"
            "        pass\n"
        )
        result, reads = self.source(raw)
        self.assertGreater(result["start_line"], 100)
        self.assertIn("async with target([self.object(), self.directory()])", result["text"])
        self.assertNotIn("from .concurrency", result["text"])
        self.assertEqual(reads, 1)
        self.assertEqual(result["python_reference_anchor"]["kind"], "call_expression")
        self.assertLessEqual(len(result["text"].splitlines()), 80)
        repeated, reads = self.source(raw)
        self.assertEqual(repeated, result)
        self.assertEqual(reads, 0)

    def test_declarations_and_literals_without_a_call_keep_literal_fallback(self):
        for raw in (
            "from .concurrency import target\n" + "\n" * 200,
            'text = "target()"\n' + "\n" * 200,
            "def target():\n    pass\n" + "\n" * 200,
        ):
            with self.subTest(raw=raw[:30]):
                result, _ = self.source(raw)
                self.assertEqual(result["start_line"], 1)
                self.assertNotIn("python_reference_anchor", result)

    def test_other_requests_non_python_and_explicit_start_are_unchanged(self):
        raw = "from .concurrency import target\n" + "\n" * 120 + "target()\n"
        for index, request in enumerate(("", "definition(target)", "references(other)")):
            result, _ = self.source(raw, request=request, path=f"pkg/other{index}.py")
            self.assertEqual(result["start_line"], 1)
            self.assertNotIn("python_reference_anchor", result)
        result, _ = self.source(raw, exact_hint=None, start=1)
        self.assertEqual(result["start_line"], 1)
        self.assertNotIn("python_reference_anchor", result)
        result, _ = self.source(raw, path="pkg/other.txt")
        self.assertEqual(result["start_line"], 1)
        self.assertNotIn("python_reference_anchor", result)

    def test_parse_failure_and_bounded_invalid_input_do_not_claim_absence(self):
        raw = "from .concurrency import target\n" + "\n" * 120 + "invalid : Python : target()\n"
        result, _ = self.source(raw)
        self.assertEqual(result["start_line"], 1)
        self.assertNotIn("python_reference_anchor", result)
        for raw, name in (("target()", None), ("target()", "a.target"), ("#" * 1_000_001, "target"), ("target()\x00", "target")):
            self.assertIsNone(python_invocation_hint_line(raw, name))

    def test_attribute_shadowed_and_unreachable_calls_are_only_syntax_hints(self):
        for raw, expected in (
            ("def f(target):\n    target()\n", 1),
            ("if False:\n    owner.target()\n", 1),
            ("from a import target\n@target()\ndef f(): pass\n", 1),
            ("other_target()\nowner.target()\n", 1),
        ):
            self.assertEqual(python_invocation_hint_line(raw, "target"), expected)
        self.assertIsNone(python_invocation_hint_line("def target(): pass\n", "target"))

    def test_opted_in_followup_delivers_caller_with_same_two_source_read_limit(self):
        root = self.reader.cache.parent
        scout.initialize(root)
        spec = {"repo": "a/b", "source_prefixes": ["pkg/"], "question": "Check actual callers", "followup_code_search": True}
        config = root / "research-config.json"
        config.write_text(json.dumps({"objective": "Evidence", "queue_target": 4, "repos": [spec]}))
        helper, caller = "pkg/helper.py", "pkg/caller.py"
        raw = {
            helper: "async def target(coros):\n    return await run(coros)\n",
            caller: "from .helper import target\n" + "\n" * 200 + "async def info():\n    async with target([object(), directory()]):\n        pass\n",
        }
        snapshot = {"repo": "a/b", "commit": "a" * 40, "files": list(raw), "blobs": {}}
        for path, text in raw.items():
            data = text.encode()
            snapshot["blobs"][path] = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            scout.write_json(self.reader._cache_path("raw", ["a/b", "a" * 40, path]), {
                "url": f"https://raw.githubusercontent.com/a/b/{'a' * 40}/{path}", "text": text,
            })
        producer = ResearchProducer(root, config, context=self.reader)
        source = {"url": f"https://raw.githubusercontent.com/a/b/{'a' * 40}/{helper}", "text": "1: async def target(coros):\n2:     return await run(coros)", "start_line": 1, "end_line": 2, "total_lines": 2, "truncated": False}
        producer.emit("caller-anchor", spec, [source], "source_audit")
        with scout.connect(root) as db:
            parent = db.execute("SELECT id FROM jobs").fetchone()[0]
            db.execute("UPDATE jobs SET state='REVIEW',result=? WHERE id=?", (json.dumps({"analysis": {"title": "target caller", "decision": "lead", "hypothesis": "Unverified empty caller", "next_check": "references(target)"}}), parent))
        with (
            patch.object(self.reader, "snapshot", return_value=snapshot),
            patch.object(self.reader, "code_search_paths", return_value=[caller, helper]) as lookup,
            patch.object(self.reader, "duplicate_sources", return_value=[]),
            patch.object(self.reader, "_read", side_effect=AssertionError("cached source must not fetch")),
            patch.object(self.reader, "source", wraps=self.reader.source) as reads,
        ):
            self.assertTrue(producer.followup(spec, {}))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(reads.call_count, 2)
        with scout.connect(root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs WHERE id<>?", (parent,)).fetchone()[0])
        evidence = next(source for source in packet["sources"] if source["url"].endswith(caller))
        self.assertIn("async with target([object(), directory()])", evidence["text"])
        self.assertNotIn("from .helper import target", evidence["text"])
        self.assertEqual(evidence["python_reference_anchor"]["kind"], "call_expression")
        self.assertLessEqual(len(evidence["text"].splitlines()), 80)


if __name__ == "__main__":
    unittest.main()
