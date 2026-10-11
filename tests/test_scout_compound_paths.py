"""Offline filename hints, not symbol resolution or bug classification."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research


class CompoundPathTests(unittest.TestCase):
    def select(self, paths, hints, **kwargs):
        return research.relevant_paths({"files": paths}, hints, **kwargs)

    def test_two_word_report_precedes_incidental_platform_match(self):
        target = "packages/core/src/sessionTitleService.ts"
        paths = ["apps/scripts/platform.mjs", target]
        self.assertEqual(self.select(paths, "Session titles unavailable on this platform"),
                         [target, paths[0]])

    def test_camel_snake_and_kebab_names_share_a_bounded_phrase_hint(self):
        for name in ("requestHeaders.ts", "request_headers.py", "request-headers.js",
                     "request-headers.rs"):
            with self.subTest(name=name):
                # Rust is not a supported source suffix here; the hint must not
                # expand the existing source-language admission rules.
                expected = [] if name.endswith(".rs") else ["src/" + name]
                self.assertEqual(self.select(["src/" + name], "request headers disappear"),
                                 expected)

    def test_singular_report_matches_plural_name(self):
        path = "src/requestHeaders.ts"
        self.assertEqual(self.select([path], "request header disappears"), [path])

    def test_one_word_reordering_and_unrelated_prose_are_not_matches(self):
        path = "src/sessionTitleService.ts"
        for hint in ("session failure", "title unavailable", "title session",
                     "session starts, then a later unrelated title changes", "platform build"):
            with self.subTest(hint=hint):
                self.assertEqual(self.select([path], hint), [])
        self.assertEqual(self.select(["src/statusEvent.ts"], "statu event"), [])

    def test_generic_roles_and_nonproduction_paths_gain_no_phrase_score(self):
        paths = ["src/buildService.ts", "src/dataManager.ts", "src/testHelper.ts",
                 "tests/sessionTitleService.ts", "src/sessionTitleService.test.ts",
                 "vendor/sessionTitleService.ts", "dist/sessionTitleService.ts",
                 "src/generated/sessionTitleService.ts", "fixtures/sessionTitleService.ts"]
        self.assertEqual(self.select(paths, "build service data manager test helper session title"), [])

    def test_explicit_path_and_priority_still_win(self):
        target = "src/sessionTitleService.ts"
        other = "src/platform.mjs"
        self.assertEqual(self.select([target, other], f"session title, inspect {other}"),
                         [other, target])
        self.assertEqual(self.select([target, other], f"session title {target} {other}",
                                    priority_hints=other), [other, target])
        self.assertEqual(self.select([target, other], f"session title {other}",
                                    deprioritize=[other]), [target, other])
        self.assertEqual(self.select([target, other], f"session title {other}",
                                    priority_hints=other, deprioritize=[other]), [other, target])

    def test_excluded_and_unobserved_paths_cannot_become_fetch_targets(self):
        target = "src/sessionTitleService.ts"
        self.assertEqual(self.select([target], "session title", exclude=[target]), [])
        self.assertEqual(self.select([], f"session title {target} https://evil.invalid/title"), [])

    def test_hint_caps_and_snapshot_order_are_preserved(self):
        paths = ["b/sessionTitle.ts", "a/sessionTitle.ts"]
        self.assertEqual(self.select(paths, "session title"), sorted(paths))
        self.assertEqual(self.select(paths, "x" * 16000 + " session title"), [])

    def test_report_subject_precedes_incidental_multitoken_steps(self):
        target = "src/sessionTitleService.ts"
        other = "a/userPrompt.ts"
        self.assertEqual(self.select([other, target], "Session titles fail after a user prompt",
                                    topic_hints="Session titles fail"), [target, other])
        self.assertEqual(self.select([other, target], f"session title, inspect {other}",
                                    topic_hints="session title"), [other, target])

    def test_followup_keeps_two_pinned_source_reads_and_no_search_tier(self):
        target = "src/sessionTitleService.ts"
        commit = "a" * 40
        report = {"url": "https://github.com/owner/project/issues/42",
                  "text": "Session titles unavailable on this platform"}

        class Reader:
            def __init__(self):
                self.reads = []

            def snapshot(self, repo, ref="main"):
                return {"commit": commit, "files": ["src/platform.mjs", target],
                        "blobs": {target: "b" * 40, "src/platform.mjs": "c" * 40}}

            def issue_sources(self, repo, number):
                return [report]

            def duplicate_sources(self, repo, title):
                return []

            def source(self, repo, revision, path, **kwargs):
                self.reads.append((revision, path))
                return {"url": f"https://raw.githubusercontent.com/{repo}/{revision}/{path}",
                        "text": "1: observed source, not a defect verdict"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            spec = {"repo": "owner/project", "source_prefixes": ["src/"],
                    "question": "Check the current contract"}
            config.write_text(json.dumps({"objective": "Acquire relevant evidence",
                                         "queue_target": 4, "repos": [spec]}), encoding="utf-8")
            reader = Reader()
            with patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}):
                producer = research.ResearchProducer(root, config, context=reader)
                prior = {"url": f"https://raw.githubusercontent.com/owner/project/{commit}/src/platform.mjs",
                         "text": "1: prior unrelated platform context"}
                producer.emit("root", spec, [report, prior], "issue_triage", focus_issue=42)
                with scout.connect(root) as db:
                    db.execute("UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?",
                               (time.time(), scout.dumps({"analysis": {
                                   "decision": "needs_context", "title": "Session titles",
                                   "hypothesis": "Prior src/platform.mjs does not settle this contract", "evidence": [],
                                   "next_check": "Locate session title implementation"}})))
                self.assertTrue(producer.followup(spec, {}))
                self.assertEqual(reader.reads, [(commit, target), (commit, "src/platform.mjs")])
                with scout.connect(root) as db:
                    packet = json.loads(db.execute(
                        "SELECT packet FROM jobs ORDER BY created DESC LIMIT 1").fetchone()[0])
                self.assertEqual(len(packet["sources"]), 3)
                self.assertNotIn("code_search_hint", scout.dumps(packet))


if __name__ == "__main__":
    unittest.main()
