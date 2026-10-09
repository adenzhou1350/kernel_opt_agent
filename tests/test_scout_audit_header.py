"""Import discovery preserves original evidence, using only immutable cache."""

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_audit_context import contextual_audit_header
import kimi_scout as scout
from kimi_scout_research import ResearchProducer


REPO, COMMIT, PATH = "owner/project", "a" * 40, "src/runner.py"


def raw_source():
    # The original 120-line excerpt ends inside a multiline import. Parsing
    # only that excerpt cannot distinguish it from an implementation fragment.
    return "\n".join(
        ['"""Module API."""'] + ["# retained comment"] * 116
        + ["from provider import (", "    a,", "    b,", "    c,", ")", ""]
        + ["class Runner:", "    def forward(self, x):", "        return x"]
        + ["# rest"] * 50
    )


class AuditHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.context = PublicContext(self.tmp.name)
        self.case = 0
        snapshot = patch.object(self.context, "snapshot", return_value={"files": [PATH]})
        snapshot.start()
        self.addCleanup(snapshot.stop)

    def acquire(self, raw):
        # Distinct fixture content must not masquerade as a changed immutable
        # cache entry for the same revision in one context.
        self.case += 1
        context = PublicContext(Path(self.tmp.name) / str(self.case))
        with patch.object(context, "snapshot", return_value={"files": [PATH]}), \
                patch.object(context, "_read", return_value=raw) as read:
            source = context.source(REPO, COMMIT, PATH, start=1)
            expanded = contextual_audit_header(context, REPO, COMMIT, PATH, source)
        self.assertEqual(read.call_count, 1)  # No second public GET.
        return source, expanded

    def test_incomplete_import_prefix_gains_body_without_omitting_imports(self):
        source, result = self.acquire(raw_source())
        self.assertTrue(result["text"].startswith(source["text"] + "\n"))
        self.assertIn("124: class Runner:", result["text"])
        self.assertEqual(result["end_line"], 160)
        self.assertTrue(result["truncated"])  # Not complete file/reachability.

    def test_same_version_cache_required_and_no_cache_fill(self):
        source = {"start_line": 1, "end_line": 1, "total_lines": 3, "text": "1: import a"}
        with patch.object(self.context, "source", side_effect=AssertionError("network")):
            self.assertIs(contextual_audit_header(self.context, REPO, COMMIT, PATH, source), source)

    def test_existing_context_cache_interface_without_reference_hints(self):
        with patch.object(self.context, "_read", return_value=raw_source()):
            source = self.context.source(REPO, COMMIT, PATH, start=1)
        class CacheOnly:
            _cache_path = self.context._cache_path
            _load = self.context._load
        with patch.object(self.context, "_read", side_effect=AssertionError("network")):
            result = contextual_audit_header(CacheOnly(), REPO, COMMIT, PATH, source)
        self.assertEqual(result["end_line"], 160)
        self.assertTrue(result["text"].startswith(source["text"] + "\n"))

    def test_export_assignments_probes_calls_and_existing_body_unchanged(self):
        for line in ("__all__ = ['a']", "available = probe()", "register()", "def f():\n    pass"):
            with self.subTest(line=line):
                source, result = self.acquire("import a\n" + line + "\n" + "# rest\n" * 170)
                self.assertIs(result, source)

    def test_forwarding_only_file_and_out_of_cap_body_unchanged(self):
        for raw in ("import a\n" * 180, "import a\n" * 161 + "def f():\n    pass"):
            source, result = self.acquire(raw)
            self.assertIs(result, source)

    def test_nonfirst_nonpython_and_missing_bounds_do_not_fetch(self):
        for path, source in (
            ("src/runner.ts", {"start_line": 1, "end_line": 120, "total_lines": 180, "text": "1: import a"}),
            (PATH, {"start_line": 121, "end_line": 240, "total_lines": 300, "text": "121: import a"}),
            (PATH, {"text": "import a"}),
        ):
            with patch.object(self.context, "source") as fetch:
                self.assertIs(contextual_audit_header(self.context, REPO, COMMIT, path, source), source)
                fetch.assert_not_called()

    def test_changed_cached_content_or_invalid_syntax_abstains(self):
        for raw in (raw_source().replace("class Runner:", "class ("), raw_source().replace("Module API", "Other API")):
            with patch.object(self.context, "_read", return_value=raw_source()):
                source = self.context.source(REPO, COMMIT, PATH, start=1)
            with patch.object(self.context, "_load", return_value={"url": source["url"], "text": raw}):
                self.assertIs(contextual_audit_header(self.context, REPO, COMMIT, PATH, source), source)

    def test_large_body_cannot_clip_retained_prefix_or_exceed_excerpt_cap(self):
        raw = raw_source().replace("# rest", "# " + "x" * 1000)
        source, result = self.acquire(raw)
        self.assertIs(result, source)

    def test_expansion_never_calls_source_or_network_and_keeps_short_full_file(self):
        raw = "import a\n" * 120 + "def f():\n    return a\n"
        with patch.object(self.context, "_read", return_value=raw):
            source = self.context.source(REPO, COMMIT, PATH, start=1)
        with patch.object(self.context, "source", side_effect=AssertionError("fetch")), \
                patch.object(self.context, "_read", side_effect=AssertionError("network")):
            result = contextual_audit_header(self.context, REPO, COMMIT, PATH, source)
        self.assertEqual(result["end_line"], 122)
        self.assertFalse(result["truncated"])
        self.assertTrue(result["text"].startswith(source["text"] + "\n"))

    def test_producer_admits_expansion_under_original_key_without_skipping_remaining_body(self):
        for total in (122, 300):
            with self.subTest(total=total), tempfile.TemporaryDirectory() as root:
                context = PublicContext(root)
                config = Path(root) / "config.json"
                config.write_text(json.dumps({"objective": "find boundary evidence",
                    "queue_target": 4, "source_windows": 3, "repos": [
                        {"repo": REPO, "question": "check boundary", "source_prefixes": ["src/"]}
                    ]}), encoding="utf-8")
                scout.initialize(root)
                producer = ResearchProducer(root, config, context=context)
                progress = {}
                raw = "import a\n" * 120 + "def f():\n    return a\n" + "# rest\n" * (total - 122)
                snapshot = {"commit": COMMIT, "files": [PATH], "blobs": {PATH: "b" * 40}}
                with patch.object(context, "snapshot", return_value=snapshot), \
                        patch.object(context, "_read", return_value=raw) as read:
                    self.assertTrue(producer.source_audit(producer.config["repos"][0], progress))
                    self.assertEqual(read.call_count, 1)
                    with scout.connect(root) as db:
                        row = db.execute("SELECT state,packet,result FROM jobs").fetchone()
                    packet = json.loads(row["packet"])
                    self.assertEqual(row["state"], "PENDING")
                    self.assertIsNone(row["result"])
                    self.assertEqual(packet["sources"][0]["end_line"], min(160, total))
                    owners = packet["sources"][0]["python_definition_context"]
                    self.assertEqual(owners["definitions"], [
                        {"qualified_name": "f", "start_line": 121, "end_line": 122}
                    ])
                    self.assertTrue(producer.seen(f"source:{REPO}:{PATH}:{'b' * 40}:1"))
                    # Complete file has no missing next-window evidence. A long
                    # file still gets its ordinary next window, not suppressed.
                    self.assertEqual(progress["source_cursor"], 3 if total == 122 else 1)
                    if total == 300:
                        self.assertTrue(producer.source_audit(producer.config["repos"][0], progress))
                        self.assertTrue(producer.seen(f"source:{REPO}:{PATH}:{'b' * 40}:121"))
                    else:
                        self.assertFalse(producer.source_audit(producer.config["repos"][0], progress))


if __name__ == "__main__":
    unittest.main()
