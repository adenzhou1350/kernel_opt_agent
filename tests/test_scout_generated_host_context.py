"""Caller-context hints stay pinned, optional and within the existing read budget."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_generated_context import contract_requests

PIN = "a" * 40
SOURCE = "pkg/feature/csrc/pack_0123456789abcdef_kernel.cu"


class GeneratedHostContextTests(unittest.TestCase):
    def setUp(self):
        self.packet = {
            "repo": "owner/repo",
            "sources": [
                {"url": f"https://raw.githubusercontent.com/owner/repo/{PIN}/{SOURCE}"}
            ],
        }
        self.files = [
            SOURCE,
            "pkg/feature/cake_jit.py",
            "pkg/feature/cake_backend.py",
            "pkg/feature/README.md",
            "unrelated/cake_backend.py",
        ]

    def requests(self, hints="grid num_chunks v_amax_partial"):
        return contract_requests(self.packet, {"files": self.files}, hints=hints)

    def test_paired_backend_replaces_readme_without_a_third_request(self):
        requests = self.requests()
        self.assertEqual(
            [r["path"] for r in requests],
            ["pkg/feature/cake_jit.py", "pkg/feature/cake_backend.py"],
        )
        self.assertEqual(requests[1]["max_lines"], 60)
        self.assertEqual(requests[1]["hints"], "grid num_chunks v_amax_partial")
        self.assertEqual(requests[1]["request_hints"], requests[1]["hints"])
        self.assertNotIn("exact_hint", requests[1])
        self.assertNotIn("unrelated/cake_backend.py", str(requests))

    def test_missing_paired_backend_keeps_readme(self):
        self.files.remove("pkg/feature/cake_backend.py")
        self.assertEqual(self.requests()[1]["path"], "pkg/feature/README.md")

    def test_missing_readme_uses_only_the_remaining_contract_slot(self):
        self.files.remove("pkg/feature/README.md")
        requests = self.requests()
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["path"], "pkg/feature/cake_backend.py")
        self.assertEqual([r["max_lines"] for r in requests], [80, 60])

    def test_question_outside_the_hint_budget_keeps_readme(self):
        self.assertEqual(
            self.requests(" " * 2000 + "grid")[1]["path"], "pkg/feature/README.md"
        )

    def test_empty_or_invalid_hints_do_not_replace_readme(self):
        for hints in ("", " \n", None, 123, {"execute": "anything"}):
            with self.subTest(hints=hints):
                self.assertEqual(
                    self.requests(hints)[1]["path"], "pkg/feature/README.md"
                )

    def test_hint_bytes_are_not_executed_and_text_is_bounded(self):
        hints = "references(amax_kwargs) " + "echo $secret; " * 1000
        request = self.requests(hints)[1]
        self.assertEqual(request["hints"], hints[:2000])
        self.assertEqual(request["request_hints"], hints[:2000])

    def test_ambiguous_registry_still_does_not_guess(self):
        self.files.append("pkg/feature/other_jit.py")
        self.assertEqual(self.requests(), [])

    def test_registry_py_does_not_imply_an_arbitrary_backend(self):
        self.files.remove("pkg/feature/cake_jit.py")
        self.files.append("pkg/feature/registry.py")
        self.assertEqual(self.requests()[1]["path"], "pkg/feature/README.md")

    def test_mutable_foreign_or_unobserved_primary_keeps_normal_search(self):
        original = self.packet["sources"][0]["url"]
        for value in (
            original.replace(PIN, "main"),
            original.replace("owner/repo", "elsewhere/repo"),
        ):
            self.packet["sources"][0]["url"] = value
            self.assertEqual(self.requests(), [])
        self.packet["sources"][0]["url"] = original
        self.files.remove(SOURCE)
        self.assertEqual(self.requests(), [])

    def test_followup_wires_the_question_without_increasing_source_reads(self):
        import kimi_scout as scout
        import kimi_scout_research as research

        calls = []
        files = list(self.files)

        class Context:
            def snapshot(self, repo, ref="main"):
                return {"commit": PIN, "files": files}

            def source(self, repo, commit, path, **kwargs):
                calls.append((path, kwargs))
                return {
                    "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                    "text": path + str(kwargs),
                    "truncated": True,
                }

            def duplicate_sources(self, repo, title):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            spec = {
                "repo": "owner/repo",
                "source_prefixes": ["pkg/"],
                "question": "Check reachable launcher contracts",
            }
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "objective": "Inspect evidence",
                        "queue_target": 4,
                        "repos": [spec],
                    }
                ),
                encoding="utf-8",
            )
            producer = research.ResearchProducer(root, config, context=Context())
            old = {
                **self.packet["sources"][0],
                "text": "for (int chunk = bid; chunk < num_chunks; chunk += 512)",
            }
            self.assertTrue(
                producer.emit("generated-launch", spec, [old], "source_audit")
            )
            with scout.connect(root) as db:
                db.execute(
                    "UPDATE jobs SET state='REVIEW', result=?, finished=?",
                    (
                        json.dumps(
                            {
                                "analysis": {
                                    "title": "Fixed launch?",
                                    "next_check": "grid num_chunks v_amax_partial",
                                }
                            }
                        ),
                        time.time(),
                    ),
                )
            with patch.object(
                research,
                "relevant_paths",
                return_value=[SOURCE, "unrelated/cake_backend.py"],
            ):
                self.assertTrue(producer.followup(spec, {}))
            self.assertEqual(
                [path for path, _ in calls],
                [SOURCE, "pkg/feature/cake_jit.py", "pkg/feature/cake_backend.py"],
            )
            self.assertEqual(calls[-1][1]["max_lines"], 60)
            self.assertIn("grid num_chunks v_amax_partial", calls[-1][1]["hints"])
            self.assertEqual(calls[-1][1]["hints"], calls[-1][1]["request_hints"])
            with scout.connect(root) as db:
                packets = [
                    json.loads(row["packet"])
                    for row in db.execute("SELECT packet FROM jobs")
                ]
            followup = next(
                p
                for p in packets
                if p.get("research", {}).get("stage") == "source_followup"
            )
            self.assertEqual(len(followup["sources"]), 4)
            self.assertNotIn("README.md", json.dumps(followup))


if __name__ == "__main__":
    unittest.main()
