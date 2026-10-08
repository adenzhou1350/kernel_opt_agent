"""A useful lexical prefix is partial evidence, never a complete JS parse."""

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

REPO, COMMIT, PATH = "owner/project", "a" * 40, "src/client.ts"
URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{PATH}"


class JavascriptPrefixTests(unittest.TestCase):
    def setUp(self):
        self.packet = {
            "repo": REPO,
            "sources": [
                {
                    "url": URL,
                    "text": "1: interface target {}",
                    "start_line": 1,
                    "end_line": 50,
                }
            ],
        }
        self.snapshot = {"commit": COMMIT, "files": [PATH]}

    def select(self, raw):
        cache = Mock(return_value=raw)
        result = reference_requests(
            self.packet,
            self.snapshot,
            {
                "next_check": "Inspect references(target)",
            },
            cache,
        )
        cache.assert_called_once_with(REPO, COMMIT, PATH)
        return result

    def test_late_unsupported_syntax_retains_safe_prefix_and_discloses_scope(self):
        prefix = "// unrelated\n" * 100 + "function producer() { return target(); }\n"
        for suffix in (
            "const regex = /target/;\ntarget();",
            "const ratio = value / count;\ntarget();",
            "const msg = `${other.call()}`;\ntarget();",
            'const msg = "unterminated; target();',
            "/* unterminated target",
        ):
            with self.subTest(suffix=suffix):
                requests = self.select(prefix + suffix)
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(request["start"], 93)
                self.assertEqual(request["max_lines"], 9)
                self.assertFalse(request["reference_scan"]["complete"])
                self.assertEqual(request["reference_scan"]["scanned_through_line"], 101)
                self.assertIn("not reachability", request["reference_scan"]["scope"])

    def test_partial_line_and_post_boundary_matches_are_not_selected(self):
        for raw in (
            "\n" * 60 + "target(); const regex = /x/;\ntarget();",
            "\n" * 60 + "const regex = /x/;\ntarget();",
            "\n" * 60 + "/* target */\nconst regex = /x/;\ntarget();",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.select(raw), [])

    def test_trivia_before_boundary_is_still_masked(self):
        raw = "\n" * 60 + '// target\nconst s = "target";\n'
        raw += "/* target */\nconst t = `${target}`;\nconst regex = /x/;\ntarget();"
        self.assertEqual(self.select(raw), [])

    def test_complete_scan_retains_existing_request_shape(self):
        requests = self.select("\n" * 100 + "target();\n")
        self.assertEqual(requests, [{"path": PATH, "start": 93, "max_lines": 80}])

    def test_two_windows_stop_before_syntax_boundary(self):
        raw = "\n" * 100 + "target();\n" + "\n" * 160 + "other.target();\n"
        raw += "\n" * 10 + "const regex = /x/;\nlate.target();"
        requests = self.select(raw)
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertLessEqual(request["max_lines"], 80)
            self.assertLessEqual(request["start"] + request["max_lines"] - 1, 272)
            self.assertEqual(request["reference_scan"]["scanned_through_line"], 272)

    def test_emitted_followup_keeps_prefix_scope_and_pinned_read_budget(self):
        raw = (
            "interface target {}\n"
            + "\n" * 100
            + "function producer(): target { return value; }\n"
        )
        raw += "\n" * 160 + "function consumer() { return other.target(); }\n"
        raw += "\n" * 10 + "const regex = /x/;\nlate.target();"

        class Reader(context.PublicContext):
            def snapshot(self, repo, ref="main"):
                return {"commit": COMMIT, "files": [PATH], "blobs": {PATH: "b" * 40}}

            def cached_source_text(self, *args):
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
                                "question": "Check consumer",
                            }
                        ],
                    }
                )
            )
            reader = Reader(root)
            with patch.object(
                research,
                "lesson_suggestions",
                return_value={"status": "NO_MATCH"},
                create=True,
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
                                        "title": "client.ts",
                                        "hypothesis": "Unverified",
                                        "decision": "needs_context",
                                        "next_check": "Inspect references(target)",
                                        "evidence": [],
                                    }
                                }
                            ),
                        ),
                    )
                with (
                    patch.object(reader, "source", wraps=reader.source) as reads,
                    patch.object(reader, "_read", wraps=reader._read) as physical_reads,
                ):
                    self.assertTrue(producer.followup(spec, {}))
                self.assertEqual(reads.call_count, 2)
                self.assertEqual(physical_reads.call_count, 1)
                with scout.connect(root) as db:
                    packets = [
                        json.loads(row[0])
                        for row in db.execute("SELECT packet FROM jobs")
                    ]
                emitted = next(
                    packet for packet in packets if "untrusted_prior_analysis" in packet
                )
                recovered = [
                    source
                    for source in emitted["sources"]
                    if "reference_scan" in source
                ]
                self.assertEqual(len(recovered), 2)
                for source in recovered:
                    self.assertEqual(source["url"], URL)
                    self.assertFalse(source["reference_scan"]["complete"])
                    self.assertLessEqual(
                        source["end_line"],
                        source["reference_scan"]["scanned_through_line"],
                    )
                    self.assertNotIn("late.target", source["text"])
                self.assertLessEqual(
                    len((scout.SYSTEM + scout.dumps(emitted)).encode()),
                    scout.MAX_INPUT_BYTES,
                )


if __name__ == "__main__":
    unittest.main()
