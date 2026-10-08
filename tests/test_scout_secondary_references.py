"""Already-supplied secondary references, without model-created fetch targets."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_symbol_references import reference_requests


class SecondaryReferencesTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha = "a/b", "a" * 40
        self.primary = "src/caller.ts"
        self.secondary = "src/worker.ts"
        self.packet = {
            "repo": self.repo,
            "sources": [
                self.source(self.primary, 1, 80),
                self.source(self.secondary, 1, 80),
            ],
        }
        self.snapshot = {"commit": self.sha, "files": [self.primary, self.secondary]}
        self.raw = (
            "// service is a comment\n"
            + "\n" * 180
            + "service() { binding.service(); }\n"
        )
        self.cache = Mock(return_value=self.raw)

    def source(self, path, first, last):
        return {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{self.sha}/{path}",
            "start_line": first,
            "end_line": last,
        }

    def request(self, text):
        return reference_requests(
            self.packet, self.snapshot, {"next_check": text}, self.cache
        )

    def test_full_path_replaces_primary_cache_lookup(self):
        result = self.request("references(service) in src/worker.ts")
        self.assertEqual(
            result, [{"path": self.secondary, "start": 174, "max_lines": 80}]
        )
        self.cache.assert_called_once_with(self.repo, self.sha, self.secondary)

    def test_unique_basename_in_multilingual_request(self):
        result = self.request("references(service) 于 worker.ts：查看实现")
        self.assertEqual(result[0]["path"], self.secondary)

    def test_explicit_primary_and_no_filename_preserve_default(self):
        for text in ("references(service)", "references(service) in src/caller.ts"):
            with self.subTest(text=text):
                self.cache.reset_mock()
                self.assertEqual(self.request(text)[0]["path"], self.primary)
                self.cache.assert_called_once_with(self.repo, self.sha, self.primary)

    def test_all_shown_secondary_fragments_are_excluded(self):
        self.packet["sources"].append(self.source(self.secondary, 160, 200))
        self.assertEqual(self.request("references(service) in src/worker.ts"), [])
        self.cache.assert_called_once_with(self.repo, self.sha, self.secondary)

    def test_two_named_paths_and_ambiguous_basename_abstain(self):
        self.assertEqual(
            self.request("references(service) in src/worker.ts and src/caller.ts"), []
        )
        self.assertEqual(
            self.request("references(service) in src/worker.ts and caller.ts"), []
        )
        self.packet["sources"].append(self.source("other/worker.ts", 1, 80))
        self.snapshot["files"].append("other/worker.ts")
        self.assertEqual(self.request("references(service) in worker.ts"), [])
        self.cache.assert_not_called()
        # A full path disambiguates the two already-supplied basenames.
        self.assertEqual(
            self.request("references(service) in src/worker.ts")[0]["path"],
            self.secondary,
        )

    def test_drift_absent_tree_untrusted_host_and_missing_cache_abstain(self):
        original = self.packet["sources"][1]["url"]
        for url in (
            original.replace(self.sha, "b" * 40),
            original.replace("raw.githubusercontent.com", "evil.invalid"),
            original + "?override=1",
        ):
            with self.subTest(url=url):
                self.packet["sources"][1]["url"] = url
                self.assertEqual(
                    self.request("references(service) in src/worker.ts"), []
                )
        self.cache.assert_not_called()
        self.packet["sources"][1]["url"] = original
        self.snapshot["files"].remove(self.secondary)
        self.assertEqual(self.request("references(service) in src/worker.ts"), [])
        self.cache.assert_not_called()
        self.snapshot["files"].append(self.secondary)
        self.cache.return_value = None
        self.assertEqual(self.request("references(service) in src/worker.ts"), [])

    def test_unobserved_filename_does_not_create_target(self):
        self.request("references(service) in src/new-worker.ts")
        self.cache.assert_called_once_with(self.repo, self.sha, self.primary)

    def test_unsupported_secondary_syntax_and_strings_are_not_evidence(self):
        for raw in (
            "const ratio = value / count; service();",
            'const text = "service";',
        ):
            self.cache.return_value = raw
            self.assertEqual(self.request("references(service) in src/worker.ts"), [])

    def test_producer_emits_requested_secondary_not_unrelated_search(self):
        import kimi_scout as scout
        from kimi_scout_context import PublicContext
        from kimi_scout_research import ResearchProducer

        snapshot = {
            **self.snapshot,
            "blobs": {p: "b" * 40 for p in self.snapshot["files"]},
        }
        raw = (
            "// service is a comment\n"
            + "\n" * 180
            + "service() { binding.service(); }\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            spec = {
                "repo": self.repo,
                "source_prefixes": ["src/"],
                "question": "Inspect lifecycle",
            }
            scout.write_json(
                config,
                {
                    "objective": "Read observed evidence",
                    "queue_target": 4,
                    "repos": [spec],
                },
            )
            reader = PublicContext(root)
            producer = ResearchProducer(root, config, context=reader)
            sources = [
                {**s, "text": "1: // already supplied source fragment"}
                for s in self.packet["sources"]
            ]
            producer.emit("old", spec, sources, "source_audit")
            with scout.connect(root) as db:
                db.execute(
                    "UPDATE jobs SET state='NEEDS_CONTEXT',finished=1,result=?",
                    (
                        json.dumps(
                            {
                                "analysis": {
                                    "title": "Inspect worker service",
                                    "hypothesis": "Unverified lifecycle",
                                    "decision": "needs_context",
                                    "next_check": "references(service) in src/worker.ts",
                                    "evidence": [],
                                }
                            }
                        ),
                    ),
                )
            with (
                patch.object(reader, "snapshot", return_value=snapshot),
                patch.object(reader, "cached_source_text", return_value=raw) as cached,
                patch.object(reader, "_read", return_value=raw) as fetch,
                patch.object(reader, "duplicate_sources", return_value=[]),
                patch.object(reader, "source", wraps=reader.source) as reads,
            ):
                self.assertTrue(producer.followup(spec, {}))
                cached.assert_called_once_with(self.repo, self.sha, self.secondary)
                self.assertEqual(reads.call_count, 1)
                self.assertEqual(fetch.call_count, 1)
            with scout.connect(root) as db:
                emitted = json.loads(
                    db.execute(
                        "SELECT packet FROM jobs ORDER BY created DESC LIMIT 1"
                    ).fetchone()[0]
                )
            fragments = [
                s for s in emitted["sources"] if s["url"].endswith(self.secondary)
            ]
            self.assertEqual(len(fragments), 1)
            self.assertIn("binding.service()", fragments[0]["text"])
            self.assertEqual(fragments[0]["start_line"], 174)
            self.assertLessEqual(len(fragments[0]["text"].splitlines()), 80)

    def test_cached_accessor_never_fetches_and_checks_exact_identity_and_budget(self):
        from kimi_scout_context import PublicContext

        with tempfile.TemporaryDirectory() as directory:
            reader = PublicContext(Path(directory))
            url = self.packet["sources"][1]["url"]
            for data, expected in (
                ({"url": url, "text": "service();"}, "service();"),
                ({"url": url.replace(self.sha, "b" * 40), "text": "service();"}, None),
                ({"url": url, "text": "x" * 131073}, None),
                ({"url": url, "text": "\u754c" * 50000}, None),
                (None, None),
            ):
                with (
                    self.subTest(expected=expected),
                    patch.object(reader, "_load", return_value=data),
                    patch.object(
                        reader, "_read", side_effect=AssertionError("must not fetch")
                    ),
                ):
                    self.assertEqual(
                        reader.cached_source_text(self.repo, self.sha, self.secondary),
                        expected,
                    )

    def test_cached_accessor_rejects_model_created_revision_or_unsafe_path(self):
        from kimi_scout_context import PublicContext

        with tempfile.TemporaryDirectory() as directory:
            reader = PublicContext(Path(directory))
            for revision, path in (
                ("main", self.secondary),
                (self.sha, "../private.ts"),
                (self.sha, "src\\worker.ts"),
            ):
                with (
                    self.subTest(revision=revision, path=path),
                    patch.object(reader, "_load") as load,
                ):
                    with self.assertRaises(ValueError):
                        reader.cached_source_text(self.repo, revision, path)
                    load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
