"""Offline cached C-family/Python references and follow-up packet tests."""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research
from scout_symbol_references import reference_requests

REPO, COMMIT, PATH = "a/b", "a" * 40, "src/kernel.cu"
URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{PATH}"


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.raw = (
            "#error Do not compile or execute this source\n"
            '#define target 31744\n// target\nconst char* s = "target";\n'
            + "\n" * 200
            + "void producer() { write(target); }\n"
            + "\n" * 200
            + "void consumer() { read(target); }\n"
        )
        self.packet = {
            "repo": REPO,
            "sources": [
                {
                    "url": URL,
                    "text": "2: #define target 31744",
                    "start_line": 1,
                    "end_line": 50,
                }
            ],
        }
        self.snapshot = {"commit": COMMIT, "files": [PATH]}
        self.cache = Mock(side_effect=lambda *args: self.raw)

    def requests(self, request="Inspect references(target)", **kwargs):
        return reference_requests(
            self.packet, self.snapshot, {"next_check": request}, self.cache, **kwargs
        )

    def test_selects_first_and_last_unseen_code_hits_not_comments_or_defines(self):
        result = self.requests()
        self.assertEqual([r["start"] for r in result], [197, 398])
        self.assertEqual([r["max_lines"] for r in result], [80, 80])
        self.cache.assert_called_once_with(REPO, COMMIT, PATH)

    def test_nearby_hits_need_only_one_window(self):
        self.raw = "\n" * 100 + "void f(){ target(); target(); }\n"
        self.assertEqual(len(self.requests()), 1)

    def test_existing_complete_ranges_and_macro_only_abstain(self):
        self.packet["sources"][0].update(start_line=1, end_line=1000)
        self.assertEqual(self.requests(), [])
        self.packet["sources"][0].update(end_line=1)
        self.raw = (
            '#define X(a) \\\n    target(a)\n// target\nconst char* msg = "target";\n'
        )
        self.assertEqual(self.requests(), [])

    def test_explicit_syntax_and_small_budget_only(self):
        for request in (
            "Inspect target",
            "references(url/target)",
            "references(a) references(b) references(c)",
            None,
        ):
            self.assertEqual(self.requests(request), [])
        self.assertEqual(len(self.requests(limit=1)), 1)
        for limit in (0, 3, True):
            with self.assertRaises(ValueError):
                self.requests(limit=limit)

    def test_raw_strings_unterminated_comment_oversize_missing_cache_abstain(self):
        for raw in (
            'R"(target)"; target();',
            "/* target",
            "x" * 131073,
            None,
            "target\x00",
        ):
            self.raw = raw
            self.assertEqual(self.requests(), [])

    def test_revision_path_and_language_do_not_create_fetch_targets(self):
        for url in (
            URL.replace(COMMIT, "b" * 40),
            URL + "?x=1",
            URL.replace("src/kernel.cu", "src/../kernel.cu"),
            URL.replace("src/kernel.cu", "src/kernel.ts"),
            URL.replace("raw.githubusercontent.com", "evil.example"),
        ):
            self.packet["sources"][0]["url"] = url
            self.cache.reset_mock()
            self.assertEqual(self.requests(), [])
            self.cache.assert_not_called()

    def python_source(self, raw):
        self.path = "src/kernel.py"
        self.packet["sources"][0]["url"] = URL.replace(PATH, self.path)
        self.snapshot["files"] = [self.path]
        self.raw = raw

    def test_python_refs_ignore_docs_definitions_imports_and_stores_without_execution(
        self,
    ):
        self.python_source(
            'raise RuntimeError("must never execute cached source")\n'
            '# target\n"""target()"""\nfrom external import target\n'
            'target = None\ndef target():\n    """target"""\n    pass\n'
            + "\n" * 200
            + "def producer():\n    return target()\n"
            + "\n" * 200
            + "def consumer():\n    return other.target()\n"
        )
        result = self.requests()
        self.assertEqual([r["start"] for r in result], [202, 404])
        self.cache.assert_called_once_with(REPO, COMMIT, self.path)
        self.packet["sources"][0].update(end_line=1000)
        self.assertEqual(self.requests(), [])

    def test_python_invalid_missing_dynamic_and_unsupported_syntax_abstain(self):
        for raw in (
            "def broken(:",
            'getattr(obj, "target")()\n',
            'text = f"target()"\n',
            "target = 1\n",
            None,
        ):
            self.python_source(raw)
            self.assertEqual(self.requests(), [])

    def test_python_shadowed_and_conditional_refs_are_not_reachability_proof(self):
        self.python_source(
            "def f(target):\n    if False:\n        return target()\n"
            + "\n" * 200
            + 'def g():\n    return f"{other.target()}"\n'
        )
        self.packet["sources"][0].update(start_line=1, end_line=1)
        self.assertEqual(len(self.requests()), 2)

    def test_python_emitted_followup_supplies_consumer_not_repeat_definition(self):
        self.python_source(
            "def target(value):\n    return value\n"
            + "\n" * 200
            + "def producer():\n    return target(value)\n"
            + "\n" * 200
            + "def consumer():\n    return other.target(value)\n"
        )
        self.check_emitted_followup(self.path, ("target(value)", "other.target(value)"))

    def test_emitted_followup_replaces_reads_and_keeps_exact_pin_and_bounds(self):
        self.check_emitted_followup(PATH, ("write(target)", "read(target)"))

    def check_emitted_followup(self, path, expected):
        raw = self.raw
        url = self.packet["sources"][0]["url"]

        class Reader(context.PublicContext):
            def snapshot(self, repo, ref="main"):
                return {"commit": COMMIT, "files": [path], "blobs": {path: "b" * 40}}

            def cached_source_text(self, repo, commit, path):
                return raw

            def _read(self, *args, **kwargs):
                return raw

            def duplicate_sources(self, *args):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "objective": "Offline context test",
                        "queue_target": 4,
                        "repos": [
                            {
                                "repo": REPO,
                                "source_prefixes": ["src/"],
                                "question": "Check consumers",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            reader = Reader(root)
            with patch.object(
                research, "lesson_suggestions", return_value={"status": "NO_MATCH"}
            ):
                producer = research.ResearchProducer(root, config, context=reader)
                producer.lessons = []
                spec = producer.config["repos"][0]
                producer.emit("old", spec, self.packet["sources"], "source_audit")
                with scout.connect(root) as db:
                    db.execute(
                        "UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?",
                        (
                            time.time(),
                            scout.dumps(
                                {
                                    "analysis": {
                                        "title": "kernel.cu consumer",
                                        "hypothesis": "Unverified alias",
                                        "decision": "needs_context",
                                        "next_check": "Inspect references(target)",
                                        "evidence": [],
                                    }
                                }
                            ),
                        ),
                    )
                with patch.object(reader, "source", wraps=reader.source) as reads:
                    self.assertTrue(producer.followup(spec, {}))
                self.assertEqual(reads.call_count, 2)
                with scout.connect(root) as db:
                    rows = [
                        json.loads(row[0])
                        for row in db.execute("SELECT packet FROM jobs")
                    ]
                emitted = next(row for row in rows if "untrusted_prior_analysis" in row)
                evidence = emitted["sources"]
                self.assertTrue(any(expected[0] in s["text"] for s in evidence))
                self.assertTrue(any(expected[1] in s["text"] for s in evidence))
                self.assertTrue(all(s["url"] == url for s in evidence))
                self.assertTrue(
                    all(len(s["text"].splitlines()) <= 80 for s in evidence[1:])
                )
                self.assertFalse(
                    any("requested_definition_complete" in s for s in evidence)
                )


if __name__ == "__main__":
    unittest.main()
