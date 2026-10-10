"""Offline explicit-request selection and actual emitted-packet regressions."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research
from scout_requested_definition import requested_function_window
from tests.test_kimi_scout_research import Context

COMMIT = "a" * 40
REPO = "a/b"
PATH = "src/kernel.py"
URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{PATH}"


class RequestedDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        optional_advice = patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}, create=True)
        optional_advice.start()
        self.addCleanup(optional_advice.stop)
        self.ctx = context.PublicContext(self.root)
        self.snapshot = patch.object(self.ctx, "snapshot", return_value={"files": [PATH]})
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)
        self.raw = ("class Executor:\n    def _sync(self):\n        return True\n" +
                    "\n" * 100 + "    def _check_gate(self):\n        if self.ready:\n            self.fill = False\n        return self.fill\n")
        self.reader = patch.object(self.ctx, "_read", side_effect=lambda *a, **kw: self.raw)
        self.read_mock = self.reader.start()
        self.addCleanup(self.reader.stop)

    def evidence(self, **kwargs):
        return self.ctx.source(REPO, COMMIT, PATH,
                               hints="Inspect _check_gate. Background: Executor._sync", **kwargs)

    def test_requested_function_overrides_qualified_background_and_is_complete(self):
        evidence = self.evidence(request_hints="Inspect _check_gate clearing logic")
        self.assertEqual(evidence["start_line"], 104)
        self.assertIn("self.fill = False", evidence["text"])
        self.assertNotIn("def _sync", evidence["text"])
        self.assertTrue(evidence["requested_definition_complete"])
        self.assertEqual(evidence["end_line"], 107)
        self.assertEqual(self.read_mock.call_count, 1)

    def test_ambiguous_names_or_owners_do_not_assert_a_selected_definition(self):
        for request in ("Inspect _sync and _check_gate", "Inspect Missing._check_gate"):
            self.assertIsNone(requested_function_window(self.raw.splitlines(), request))
        duplicate = "class A:\n    def same(self): pass\nclass B:\n    def same(self): pass"
        self.assertIsNone(requested_function_window(duplicate.splitlines(), "Inspect same"))
        self.assertEqual(requested_function_window(duplicate.splitlines(), "Inspect B.same")["start_line"], 4)
        result = self.evidence(request_hints="Inspect absent_method")
        self.assertNotIn("requested_definition", result)

    def test_explicit_definition_overrides_other_function_mentions(self):
        request = "definition(_check_gate); compare Executor._sync and _check_gate"
        result = self.evidence(request_hints=request)
        self.assertEqual(result["requested_definition"]["name"], "_check_gate")
        self.assertTrue(result["requested_definition_complete"])
        self.assertIn("return self.fill", result["text"])
        self.assertNotIn("def _sync", result["text"])

    def test_explicit_qualified_definition_disambiguates_duplicate_methods(self):
        raw = "class A:\n    def same(self): pass\nclass B:\n    def same(self): pass"
        result = requested_function_window(raw.splitlines(),
                                           "definition(B.same); compare A.same")
        self.assertEqual(result["start_line"], 4)

    def test_invalid_or_multiple_explicit_targets_do_not_fall_back_to_prose(self):
        for request in (
            "definition(missing); inspect _check_gate",
            "definition(_sync) definition(_check_gate)",
            "definition(_sync, _check_gate)",
            "definition(_sync; repo:other/private) inspect _check_gate",
            "definition(\n_sync) inspect _check_gate",
            "definition(_sync inspect _check_gate",
        ):
            with self.subTest(request=request):
                self.assertIsNone(requested_function_window(self.raw.splitlines(), request))
        result = requested_function_window(self.raw.splitlines(),
                                           "definition(_sync) definition(_sync)")
        self.assertEqual(result["name"], "_sync")

    def test_explicit_target_keeps_line_precedence(self):
        result = self.evidence(request_hints="definition(_check_gate)", start=1,
                               max_lines=3)
        self.assertNotIn("requested_definition", result)
        self.assertIn("def _sync", result["text"])

    def test_explicit_target_keeps_completeness_caps(self):
        self.raw = "def target():\n" + "    # " + "x" * 10000 + "\n    return False\n"
        result = self.evidence(request_hints="definition(target)")
        self.assertFalse(result["requested_definition_complete"])
        self.assertLessEqual(len(result["text"]), 9000)

    def test_explicit_line_or_literal_remains_authoritative(self):
        for kwargs in ({"start": 1, "max_lines": 3}, {"exact_hint": "def _sync"}):
            result = self.evidence(request_hints="Inspect _check_gate", **kwargs)
            self.assertIn("def _sync", result["text"])
            self.assertNotIn("requested_definition", result)

    def test_non_python_and_malformed_request_are_not_new_fetch_targets(self):
        self.assertIsNone(requested_function_window(["const target = true;"], "Inspect target"))
        for value in (None, 42, "x" * 2001):
            with self.assertRaisesRegex(ValueError, "bounded text"):
                self.evidence(request_hints=value)
        self.assertEqual(self.read_mock.call_count, 0)

    def test_line_and_character_caps_never_claim_complete_long_function(self):
        self.raw = "def target():\n" + "    # " + "x" * 10000 + "\n    return False\n"
        result = self.evidence(request_hints="Inspect target")
        self.assertFalse(result["requested_definition_complete"])
        self.assertLessEqual(len(result["text"]), 9000)
        self.assertTrue(result["truncated"])

    def producer(self, root, ctx=None):
        scout.initialize(root)
        config = root / "config.json"
        config.write_text(json.dumps({"objective": "Offline evidence selection", "queue_target": 4,
                          "repos": [{"repo": REPO, "source_prefixes": ["src/"], "question": "Check boundaries"}]}), encoding="utf-8")
        producer = research.ResearchProducer(root, config, context=ctx or Context())
        producer.lessons = []  # Isolate source trimming from adaptive lesson fitting.
        return producer

    def test_emitted_packet_protects_complete_function_before_unrelated_raw(self):
        self.raw = "def target():\n    # " + "x" * 6000 + "\n    return False\n"
        primary = self.evidence(request_hints="Inspect target")
        unrelated = {"url": URL.replace("kernel.py", "other.py"), "text": "z" * 1200}
        first = self.producer(self.root / "first")
        self.assertTrue(first.emit("first", first.config["repos"][0], [primary, unrelated], "source_followup"))
        with scout.connect(first.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(packet["sources"][0]["text"], primary["text"])
        budget = len((scout.SYSTEM + scout.dumps(packet)).encode("utf-8")) - 400
        second = self.producer(self.root / "second")
        with patch.object(scout, "MAX_INPUT_BYTES", budget):
            self.assertTrue(second.emit("second", second.config["repos"][0], [primary, unrelated], "source_followup"))
        with scout.connect(second.root) as db:
            result = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(result["sources"][0]["text"], primary["text"])
        self.assertTrue(result["sources"][0]["requested_definition_complete"])
        self.assertLess(len(result["sources"][1]["text"]), 1200)
        self.assertLessEqual(len((scout.SYSTEM + scout.dumps(result)).encode("utf-8")), budget)

    def test_forced_trimming_clears_completeness_and_updates_visible_range(self):
        self.raw = "def target():\n" + "\n".join("    # " + "x" * 80 for _ in range(50)) + "\n    return False\n"
        primary = self.evidence(request_hints="Inspect target")
        first = self.producer(self.root / "first")
        self.assertTrue(first.emit("first", first.config["repos"][0], [primary], "source_followup"))
        with scout.connect(first.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        budget = len((scout.SYSTEM + scout.dumps(packet)).encode("utf-8")) - 1000
        second = self.producer(self.root / "second")
        with patch.object(scout, "MAX_INPUT_BYTES", budget):
            self.assertTrue(second.emit("second", second.config["repos"][0], [primary], "source_followup"))
        with scout.connect(second.root) as db:
            actual = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])["sources"][0]
        self.assertFalse(actual["requested_definition_complete"])
        self.assertEqual(actual["end_line"], actual["start_line"] + len(actual["text"].splitlines()) - 1)

    def test_followup_forwards_next_check_without_background_context(self):
        class RecordingContext(Context):
            def source(self, repo, commit, path, hints="", start=None, max_lines=120, request_hints=""):
                self.requests = getattr(self, "requests", []) + [(path, request_hints)]
                return super().source(repo, commit, path, hints, start, max_lines)
        ctx = RecordingContext()
        producer = self.producer(self.root / "queue", ctx)
        spec = producer.config["repos"][0]
        producer.emit("old", spec, [{"url": URL, "text": "old"}], "source_audit")
        with scout.connect(producer.root) as db:
            db.execute("UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?",
                       (time.time(), scout.dumps({"analysis": {"title": "kernel.py", "hypothesis": "Executor._sync",
                        "decision": "needs_context", "next_check": "Inspect _check_gate", "evidence": []}})))
        self.assertTrue(producer.followup(spec, {}))
        self.assertIn((PATH, "Inspect _check_gate"), ctx.requests)


if __name__ == "__main__":
    unittest.main()
