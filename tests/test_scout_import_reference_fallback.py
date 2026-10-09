"""Cache-only import declarations after unseen reference uses are exhausted."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_symbol_references import reference_requests


class ImportReferenceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.path = "package/parser.py"
        self.sha = "a" * 40
        self.url = f"https://raw.githubusercontent.com/a/b/{self.sha}/{self.path}"
        self.packet = {
            "repo": "a/b",
            "sources": [{"url": self.url, "start_line": 90, "end_line": 170}],
        }
        self.snapshot = {"commit": self.sha, "files": [self.path]}
        self.raw = (
            "from urllib.parse import scheme_chars\n"
            + "\n" * 100
            + ("def split(value):\n    return value[0] in scheme_chars\n")
        )
        self.cache = Mock(side_effect=lambda *args: self.raw)

    def requests(self, name="scheme_chars", **kwargs):
        return reference_requests(
            self.packet,
            self.snapshot,
            {"next_check": f"references({name})"},
            self.cache,
            **kwargs,
        )

    def excerpt(self, request):
        return "\n".join(
            self.raw.splitlines()[request["start"] - 1 : request["start"] + 79]
        )

    def test_hidden_external_import_with_already_visible_uses(self):
        result = self.requests()
        self.assertEqual(result, [{"path": self.path, "start": 1, "max_lines": 80}])
        self.assertIn("from urllib.parse import scheme_chars", self.excerpt(result[0]))
        self.cache.assert_called_once_with("a/b", self.sha, self.path)

    def test_existing_unseen_consumers_still_take_priority(self):
        self.raw += "\n" * 200 + "value = scheme_chars\n"
        result = self.requests()
        self.assertEqual(len(result), 1)
        self.assertIn("value = scheme_chars", self.excerpt(result[0]))
        self.assertNotIn("from urllib", self.excerpt(result[0]))

    def test_already_supplied_import_does_not_repeat(self):
        self.packet["sources"].append(
            {"url": self.url, "start_line": 1, "end_line": 80}
        )
        self.assertEqual(self.requests(), [])

    def test_aliases_and_dotted_plain_import_bind_only_local_name(self):
        for statement, name in (
            ("from external import original as scheme_chars", "scheme_chars"),
            ("import external.module as scheme_chars", "scheme_chars"),
            ("import external.module", "external"),
        ):
            with self.subTest(statement=statement):
                self.raw = statement + "\n"
                result = self.requests(name)
                self.assertEqual(len(result), 1)
                self.assertIn(statement, self.excerpt(result[0]))
        self.assertEqual(self.requests("module"), [])
        self.assertEqual(self.requests("owner.external"), [])

    def test_ambiguous_wildcard_conditional_and_nested_imports_abstain(self):
        for raw in (
            "from a import scheme_chars\nfrom b import scheme_chars\n",
            "from external import *\n",
            "if True:\n    from external import scheme_chars\n",
            "def load():\n    from external import scheme_chars\n",
            "text = 'from external import scheme_chars'\n",
            "scheme_chars = 1\n",
        ):
            with self.subTest(raw=raw):
                self.raw = raw
                self.assertEqual(self.requests(), [])

    def test_multiline_import_is_complete_and_oversized_statement_abstains(self):
        self.raw = (
            "\n" * 20
            + "from external import (\n"
            + "\n" * 70
            + "    scheme_chars,\n)\n"
        )
        result = self.requests()
        self.assertEqual(len(result), 1)
        self.assertIn("from external import (", self.excerpt(result[0]))
        self.assertIn("scheme_chars,\n)", self.excerpt(result[0]))
        self.raw = self.raw.replace("\n" * 70, "\n" * 90)
        self.assertEqual(self.requests(), [])

    def test_no_source_execution_dependency_lookup_or_unpinned_target(self):
        self.raw = "raise RuntimeError('must not execute')\nfrom external import scheme_chars\n"
        self.assertEqual(len(self.requests()), 1)
        self.cache.assert_called_once_with("a/b", self.sha, self.path)
        self.cache.reset_mock()
        self.packet["sources"][0]["url"] = self.url.replace(self.sha, "b" * 40)
        self.assertEqual(self.requests(), [])
        self.cache.assert_not_called()

    def test_two_imports_share_existing_read_budget(self):
        self.raw = "from a import first\n" + "\n" * 120 + "from b import second\n"
        packet = {
            "repo": "a/b",
            "sources": [{"url": self.url, "start_line": 300, "end_line": 400}],
        }
        for limit in (1, 2):
            result = reference_requests(
                packet,
                self.snapshot,
                {"next_check": "references(first), references(second)"},
                self.cache,
                limit=limit,
            )
            self.assertEqual(len(result), limit)
            self.assertTrue(all(r["max_lines"] == 80 for r in result))

    def test_real_producer_emits_import_with_one_existing_source_read(self):
        import kimi_scout as scout
        from kimi_scout_context import PublicContext
        from kimi_scout_research import ResearchProducer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            spec = {
                "repo": "a/b",
                "source_prefixes": ["package/"],
                "question": "Inspect missing definitions",
            }
            config = root / "config.json"
            scout.write_json(
                config,
                {
                    "objective": "Offline import context",
                    "queue_target": 4,
                    "repos": [spec],
                },
            )
            reader = PublicContext(root)
            producer = ResearchProducer(root, config, context=reader)
            sources = [
                {
                    **self.packet["sources"][0],
                    "text": "103: return value[0] in scheme_chars",
                }
            ]
            producer.emit("old", spec, sources, "source_audit")
            with scout.connect(root) as db:
                db.execute(
                    "UPDATE jobs SET state='NEEDS_CONTEXT',finished=1,result=?",
                    (
                        json.dumps(
                            {
                                "analysis": {
                                    "title": "scheme parsing",
                                    "hypothesis": "Definition unseen",
                                    "decision": "needs_context",
                                    "next_check": "references(scheme_chars)",
                                    "evidence": [],
                                }
                            }
                        ),
                    ),
                )
            with (
                patch.object(reader, "snapshot", return_value=self.snapshot),
                patch.object(
                    reader, "cached_source_text", return_value=self.raw
                ) as cache,
                patch.object(reader, "_read", return_value=self.raw) as fetch,
                patch.object(reader, "source", wraps=reader.source) as reads,
                patch.object(reader, "duplicate_sources", return_value=[]),
            ):
                self.assertTrue(producer.followup(spec, {}))
                cache.assert_called_once_with("a/b", self.sha, self.path)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(reads.call_count, 1)
            with scout.connect(root) as db:
                emitted = json.loads(
                    db.execute(
                        "SELECT packet FROM jobs WHERE state='PENDING'"
                    ).fetchone()[0]
                )
            self.assertIn("from urllib.parse import scheme_chars", scout.dumps(emitted))
            self.assertTrue(all(s["url"] == self.url for s in emitted["sources"]))
            self.assertFalse(
                any("requested_definition_complete" in s for s in emitted["sources"])
            )


if __name__ == "__main__":
    unittest.main()
