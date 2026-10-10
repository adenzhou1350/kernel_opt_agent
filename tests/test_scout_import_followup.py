"""Offline real producer integration and cache-only acquisition boundaries."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from kimi_scout_context import PublicContext

COMMIT = "a" * 40


class ImportFollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scout.initialize(self.root)
        self.spec = {
            "repo": "o/r",
            "source_prefixes": ["src/"],
            "question": "Find bugs",
        }
        self.value = {
            "objective": "Test acquisition",
            "queue_target": 4,
            "repos": [self.spec],
        }
        self.config = self.root / "research.json"
        self.config.write_text(json.dumps(self.value), encoding="utf-8")
        self.context = Mock()
        self.context.snapshot.return_value = {
            "commit": COMMIT,
            "files": [
                "src/read.ts",
                "src/read.test.ts",
                "src/contracts.ts",
                "src/version.ts",
            ],
        }
        self.context.cached_source_text.return_value = (
            'import type {Schema} from "./contracts.js"; '
            'import {readVersion} from "./version.js";'
        )
        self.context.source.side_effect = lambda repo, commit, path, **kw: {
            "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
            "text": f"1: content from {path}",
        }
        self.context.duplicate_sources.return_value = []
        self.producer = research.ResearchProducer(
            self.root, self.config, context=self.context
        )
        self.producer.emit(
            "first",
            self.spec,
            [
                {
                    "url": f"https://raw.githubusercontent.com/o/r/{COMMIT}/src/read.ts",
                    "text": "100: cached rows",
                }
            ],
            "source_audit",
        )

    def finish(self, decision):
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?",
                (
                    time.time(),
                    json.dumps(
                        {
                            "analysis": {
                                "decision": decision,
                                "title": "cached read",
                                "hypothesis": "untrusted hypothesis",
                                "next_check": "Inspect Schema and readVersion",
                            }
                        }
                    ),
                ),
            )

    def paths(self):
        return [
            call.args[2] if len(call.args) > 2 else call.kwargs["path"]
            for call in self.context.source.call_args_list
        ]

    def test_opt_in_missing_context_gets_two_definitions_not_another_test_window(self):
        self.spec["followup_import_context"] = True
        self.finish("needs_context")
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertEqual(self.paths(), ["src/contracts.ts", "src/version.ts"])
        self.context.cached_source_text.assert_called_once_with(
            "o/r", COMMIT, "src/read.ts"
        )
        with scout.connect(self.root) as db:
            packet = json.loads(
                db.execute("SELECT packet FROM jobs WHERE state='PENDING'").fetchone()[
                    0
                ]
            )
        self.assertIn("src/contracts.ts", scout.dumps(packet))
        self.assertNotIn("src/read.test.ts", scout.dumps(packet))
        self.assertIn("untrusted_prior_analysis", packet)

    def test_same_file_helper_substitutes_for_another_callsite_window(self):
        self.spec["followup_import_context"] = True
        self.context.cached_source_text.return_value = (
            "\n" * 29
            + """function readVersion() {
  return process.platform !== "win32" || inode !== 0n;
}
"""
            + "\n" * 130
        )
        self.finish("needs_context")
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertLessEqual(len(self.context.source.call_args_list), 2)
        call = self.context.source.call_args_list[-1]
        self.assertEqual(
            call.kwargs, {"path": "src/read.ts", "start": 22, "max_lines": 80}
        )
        self.context.cached_source_text.assert_called_once_with(
            "o/r", COMMIT, "src/read.ts"
        )

    def test_absolute_python_imports_reach_producer_under_same_two_read_budget(self):
        self.spec["followup_import_context"] = True
        primary = "src/pkg/read.py"
        self.context.snapshot.return_value = {
            "commit": COMMIT,
            "files": [
                "src/pkg/__init__.py",
                primary,
                "src/pkg/contracts.py",
                "src/pkg/runtime.py",
            ],
        }
        self.context.cached_source_text.return_value = (
            "from pkg.contracts import Schema\nfrom pkg.runtime import readVersion\n"
        )
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            packet["sources"][0]["url"] = (
                f"https://raw.githubusercontent.com/o/r/{COMMIT}/{primary}"
            )
            db.execute("UPDATE jobs SET packet=?", (scout.dumps(packet),))
        self.finish("needs_context")
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertEqual(self.paths(), ["src/pkg/contracts.py", "src/pkg/runtime.py"])
        self.context.cached_source_text.assert_called_once_with("o/r", COMMIT, primary)
        for call in self.context.source.call_args_list:
            self.assertEqual(call.kwargs["max_lines"], 80)

    def test_lead_local_helper_keeps_companion_test_without_extra_reads(self):
        self.spec["followup_import_context"] = True
        self.context.cached_source_text.return_value = (
            "\n" * 29 + "function readVersion() {}\n" + "\n" * 130
        )
        self.finish("lead")
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertEqual(self.paths(), ["src/read.ts", "src/read.test.ts"])
        self.assertEqual(
            self.context.source.call_args_list[0].kwargs,
            {"path": "src/read.ts", "start": 22, "max_lines": 80},
        )

    def test_lead_keeps_companion_test_with_one_definition_same_two_read_budget(self):
        self.spec["followup_import_context"] = True
        self.finish("lead")
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertEqual(self.paths(), ["src/contracts.ts", "src/read.test.ts"])

    def test_default_is_unchanged_and_does_not_read_import_cache(self):
        self.finish("needs_context")
        with patch.object(research, "relevant_paths", return_value=["src/read.ts"]):
            self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertEqual(self.paths(), ["src/read.ts", "src/read.test.ts"])
        self.context.cached_source_text.assert_not_called()

    def test_absent_import_cache_retains_ordinary_test_path(self):
        self.spec["followup_import_context"] = True
        self.context.cached_source_text.return_value = None
        self.finish("needs_context")
        with patch.object(research, "relevant_paths", return_value=["src/read.ts"]):
            self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertEqual(self.paths(), ["src/read.ts", "src/read.test.ts"])

    def test_opt_in_must_be_boolean_not_truthy_configuration(self):
        self.spec["followup_import_context"] = "yes"
        self.config.write_text(json.dumps(self.value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "followup_import_context"):
            research.configuration(self.config)

    def test_deferred_package_export_then_explicit_runtime_fit_existing_two_reads(self):
        self.spec["followup_import_context"] = True
        wrapper, export, runtime = (
            "src/wrapper.py",
            "src/exports/__init__.py",
            "src/exports/runtime.py",
        )
        raw = (
            "def run(a, out):\n    from .exports import size\n    return size(a, out)\n"
        )
        self.context.snapshot.return_value = {
            "commit": COMMIT,
            "files": [wrapper, export, runtime],
        }
        self.context.cached_source_text.return_value = raw

        def source(repo, commit, path, **kw):
            text = "def size(a, out=None):\n    return 0\n" if path == runtime else raw
            if path == export:
                text = "def __getattr__(name):\n    from . import runtime\n    return getattr(runtime, name)\n"
            return {
                "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                "text": text,
                "start_line": 1,
                "end_line": len(text.splitlines()),
                "total_lines": len(text.splitlines()),
                "truncated": False,
            }

        self.context.source.side_effect = source
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            packet["sources"] = [source("o/r", COMMIT, wrapper)]
            db.execute("UPDATE jobs SET packet=?", (scout.dumps(packet),))
        self.finish("needs_context")
        with scout.connect(self.root) as db:
            result = json.loads(db.execute("SELECT result FROM jobs").fetchone()[0])
            result["analysis"]["next_check"] = "Read size signature"
            db.execute("UPDATE jobs SET result=?", (scout.dumps(result),))
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertIn(export, self.paths())
        self.assertLessEqual(len(self.paths()), 2)

        with scout.connect(self.root) as db:
            result["analysis"]["next_check"] = f"Inspect {runtime} size signature"
            db.execute(
                "UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=? WHERE state='PENDING'",
                (time.time(), scout.dumps(result)),
            )
        self.context.source.reset_mock()
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertIn(runtime, self.paths())
        self.assertNotIn(export, self.paths())
        self.assertLessEqual(len(self.paths()), 2)

    def test_public_context_cache_lookup_never_fetches_or_creates_missing_record(self):
        context = PublicContext(self.root)
        path = context._cache_path("raw", ["o/r", COMMIT, "src/read.ts"])
        with patch.object(scout, "fetch", side_effect=AssertionError("network")):
            self.assertIsNone(context.cached_source_text("o/r", COMMIT, "src/read.ts"))
            self.assertFalse(path.exists())
            scout.write_json(
                path,
                {
                    "url": f"https://raw.githubusercontent.com/o/r/{COMMIT}/src/read.ts",
                    "text": "exact cached text",
                },
            )
            self.assertEqual(
                context.cached_source_text("o/r", COMMIT, "src/read.ts"),
                "exact cached text",
            )
            scout.write_json(
                path, {"url": "https://example.com/foreign", "text": "bad"}
            )
            self.assertIsNone(context.cached_source_text("o/r", COMMIT, "src/read.ts"))

    def test_explicit_imported_method_reaches_real_source_window(self):
        self.spec["followup_import_context"] = True
        primary, target = "src/pkg/read.py", "src/pkg/fileio.py"
        files = ["src/pkg/__init__.py", primary, target]
        self.context.snapshot.return_value = {"commit": COMMIT, "files": files}
        context = PublicContext(self.root / "definition-context")
        context.snapshot = Mock(return_value={"commit": COMMIT, "files": files})
        raw_sources = {
            primary: "from .fileio import AsyncFile\ndef open_file():\n    return AsyncFile()\n",
            target: "class AsyncFile:\n"
            + "\n" * 160
            + "    async def aclose(self):\n        return self.wrapped.close()\n",
        }
        for path, text in raw_sources.items():
            scout.write_json(
                context._cache_path("raw", ["o/r", COMMIT, path]),
                {
                    "url": f"https://raw.githubusercontent.com/o/r/{COMMIT}/{path}",
                    "text": text,
                },
            )
        self.context.cached_source_text.side_effect = context.cached_source_text
        self.context.source.side_effect = context.source
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            packet["sources"] = [
                {
                    "url": f"https://raw.githubusercontent.com/o/r/{COMMIT}/{primary}",
                    "text": "1: from .fileio import AsyncFile",
                }
            ]
            db.execute("UPDATE jobs SET packet=?", (scout.dumps(packet),))
        self.finish("needs_context")
        with scout.connect(self.root) as db:
            result = json.loads(db.execute("SELECT result FROM jobs").fetchone()[0])
            result["analysis"]["next_check"] = (
                "Inspect definition(AsyncFile.aclose) before proposing cleanup"
            )
            db.execute("UPDATE jobs SET result=?", (scout.dumps(result),))
        with patch.object(scout, "fetch", side_effect=AssertionError("network")):
            self.assertTrue(self.producer.followup(self.spec, {}))
        self.assertLessEqual(len(self.paths()), 2)
        self.assertIn(target, self.paths())
        with scout.connect(self.root) as db:
            emitted = json.loads(
                db.execute("SELECT packet FROM jobs WHERE state='PENDING'").fetchone()[
                    0
                ]
            )
        source = next(s for s in emitted["sources"] if s["url"].endswith("/" + target))
        self.assertIn("async def aclose(self)", source["text"])
        self.assertTrue(source["requested_definition_complete"])
        self.assertEqual(source["requested_definition"]["name"], "aclose")


if __name__ == "__main__":
    unittest.main()
