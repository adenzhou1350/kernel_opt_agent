"""The growing knowledge library must remain bounded, scoped and advisory."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout  # noqa: E402
import kimi_scout_research as research  # noqa: E402
import kimi_scout_delivery as delivery  # noqa: E402
from scout_lesson_context import (  # noqa: E402
    MAX_CARD_BYTES,
    fit_lesson_context,
    lesson_suggestions,
)


def card(name, lesson="Native stream pause observation"):
    return {
        "id": name,
        "title": name,
        "applies_when": "Native stream pause",
        "lesson": lesson,
        "avoid_when": "Do not infer GPU performance",
        "status": "hypothesis",
        "evidence": [
            {
                "url": "https://example.com/native",
                "note": "A mechanism, not a measured gain",
            }
        ],
    }


class LessonContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def save(self, value):
        path = self.root / (value["id"] + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_one_complete_card_preserves_scope_and_status(self):
        first = card("stream-pause")
        self.save(first)
        self.save(card("second-stream", "Another native stream pause condition"))
        result = lesson_suggestions("native stream pause", directory=self.root)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0], first)
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertIn("does not establish", result["caution"])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_existing_cards_are_not_duplicated(self):
        self.save(card("stream-pause"))
        result = lesson_suggestions(
            "stream pause", exclude=("stream-pause",), directory=self.root
        )
        self.assertEqual(result["matches"], [])

    def test_configuration_counterexample_remains_retrievable_and_scoped(self):
        result = lesson_suggestions("configuration CLI parser plugin consumer backend")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        lesson = result["matches"][0]
        self.assertEqual(lesson["id"], "consumer-contract-before-regression")
        self.assertLessEqual(len(json.dumps(lesson, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertEqual(lesson["status"], "counterexample")
        evidence = next(item for item in lesson["evidence"] if "/arg_groups/fields/exec_.py" in item["url"])
        self.assertIn("plugin registration", evidence["note"])
        self.assertIn("not a server or GPU qualification", evidence["note"])
        self.assertIn("Programmatic consumers", evidence["note"])

    def test_owner_lifetime_lesson_is_retrievable_with_its_native_scope(self):
        result = lesson_suggestions(
            "helper contract owner lifetime HTTP response body cancellation"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        lesson = result["matches"][0]
        self.assertEqual(lesson["id"], "helper-contract-and-owner-lifetime")
        self.assertEqual(lesson["status"], "validated")
        self.assertLessEqual(
            len(json.dumps(lesson, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        body = next(item for item in lesson["evidence"] if "download_body_test.go" in item["url"])
        self.assertIn("200/206", body["note"])
        self.assertIn("not cloud", body["note"])
        retry = next(item for item in lesson["evidence"] if "listall_context_cancellation_test.go" in item["url"])
        self.assertIn("draining", retry["note"])
        self.assertIn("503", retry["note"])
        self.assertIn("blocked", retry["note"])
        self.assertNotIn("qualified", result)

    def test_generated_variant_advice_retains_registration_and_native_limits(self):
        result = lesson_suggestions(
            "Check generated variant registration and callers before reproducing a local anomaly"
        )
        value = result["matches"][0]
        self.assertEqual(value["id"], "generated-variant-reachability")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertIn("autotuner", value["lesson"])
        self.assertIn("synchronized producer/consumer", value["lesson"])
        self.assertIn("native numerical correctness", value["avoid_when"])
        geometry = next(item for item in value["evidence"] if "#L941-L965" in item["url"])
        self.assertIn("512 CTAs", geometry["note"])
        self.assertIn("not a native GPU correctness claim", geometry["note"])
        self.assertNotIn("qualified", result)

    def test_default_library_cards_fit_the_existing_advisory_budget(self):
        root = Path(__file__).resolve().parents[1] / "knowledge" / "lessons"
        for path in root.glob("*.json"):
            with self.subTest(card=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertLessEqual(
                    len(json.dumps(value, ensure_ascii=False).encode()), MAX_CARD_BYTES
                )

    def test_large_card_is_omitted_not_silently_truncated(self):
        self.save(card("stream-pause", "native stream pause " * MAX_CARD_BYTES))
        result = lesson_suggestions("stream pause", directory=self.root)
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["oversized_matches_omitted"], 1)

    def test_query_and_failures_are_bounded_and_non_authorizing(self):
        self.save(card("stream-pause"))
        result = lesson_suggestions("stream pause " * 1000, directory=self.root)
        self.assertTrue(result["query_truncated"])
        self.assertLess(len(json.dumps(result)), MAX_CARD_BYTES)
        (self.root / "malformed.json").write_text("{}", encoding="utf-8")
        result = lesson_suggestions("stream pause", directory=self.root)
        self.assertEqual(result["status"], "LIBRARY_UNAVAILABLE")
        self.assertEqual(result["matches"], [])
        self.assertNotIn("qualified", result)

    def test_library_updates_are_visible_without_growing_a_cache(self):
        self.assertEqual(
            lesson_suggestions("stream pause", directory=self.root)["matches"], []
        )
        self.save(card("stream-pause"))
        self.assertEqual(
            len(lesson_suggestions("stream pause", directory=self.root)["matches"]), 1
        )

    def test_optional_advice_cannot_displace_primary_evidence(self):
        packet = {
            "sources": [{"text": "original source"}],
            "lesson_suggestions": {"matches": [card("stream-pause")]},
        }
        expected = packet["sources"].copy()
        fit_lesson_context(packet, 100)
        self.assertNotIn("lesson_suggestions", packet)
        self.assertEqual(packet["sources"], expected)

    def test_advice_changes_do_not_make_unchanged_sources_new_jobs(self):
        scout.initialize(self.root)
        packet = {
            "name": "fixed",
            "repo": "a/b",
            "question": "same source",
            "sources": [
                {"url": "https://github.com/a/b/issues/1", "text": "same report"}
            ],
            "lesson_suggestions": {"matches": [card("stream-pause")]},
        }
        first = scout.enqueue(self.root, packet)
        packet["lesson_suggestions"]["matches"][0]["lesson"] = "Revised advisory"
        self.assertEqual(scout.enqueue(self.root, packet), first)
        with scout.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_collect_source_attaches_a_real_related_lesson_without_fetching_it(self):
        def fetch(url, **unused):
            if "/commits/" in url:
                return json.dumps({"sha": "a" * 40})
            if "/search/issues?" in url:
                return '{"items":[]}'
            if "/issues?" in url:
                return "[]"
            return '{"private":false}'

        with patch.object(scout, "fetch", side_effect=fetch):
            packet = scout.collect_source(
                {
                    "repo": "a/b",
                    "name": "pause",
                    "question": "native stream pause resume consumer progress",
                }
            )
        extra = packet["lesson_suggestions"]["matches"]
        self.assertEqual(extra[0]["id"], "native-events-versus-consumer-progress")
        self.assertEqual(len(packet["reviewed_lessons"]), 3)

    def test_research_queue_retains_related_lesson_and_deduplicates_source(self):
        scout.initialize(self.root)
        config = self.root / "config.json"
        spec = {
            "repo": "a/b",
            "source_prefixes": ["src/"],
            "question": "native stream pause resume consumer progress",
        }
        config.write_text(
            json.dumps(
                {"objective": "Public source", "queue_target": 4, "repos": [spec]}
            ),
            encoding="utf-8",
        )
        producer = research.ResearchProducer(self.root, config, context=object())
        source = {
            "url": "https://raw.githubusercontent.com/a/b/" + "a" * 40 + "/src/pipe.ts",
            "text": "Native public source",
        }
        self.assertTrue(producer.emit("first", spec, [source], "source_audit"))
        self.assertFalse(producer.emit("second", spec, [source], "source_audit"))
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(
            packet["lesson_suggestions"]["matches"][0]["id"],
            "native-events-versus-consumer-progress",
        )

    def test_delivery_prompt_includes_advice_but_does_not_execute_a_context_request(
        self,
    ):
        worker = delivery.Delivery(
            SimpleNamespace(root=self.root, execution_concurrency=1, github_auth=False)
        )
        delivery.initialize(worker.root)
        lead = {
            "id": "native",
            "repo": "a/b",
            "canonical_key": "native-pause",
            "analysis": {"title": "Native stream pause resume consumer progress"},
        }
        delivery.stage(worker.root, [lead])
        job = delivery.claim(worker.root)
        source = {
            "source": "def value():\n    return 1\n",
            "path": "stream.py",
            "url": "https://raw.githubusercontent.com/a/b/" + "a" * 40 + "/stream.py",
        }
        response = {
            "decision": "needs_context",
            "reason": "Need actual consumer",
            "test_code": "",
            "edits": [],
        }
        with (
            patch.object(delivery, "load_source", return_value=source),
            patch.object(worker, "model", return_value=response) as model,
            patch.object(worker, "sandbox") as sandbox,
        ):
            self.assertEqual(worker.execute(job), "INCONCLUSIVE")
        prompt = model.call_args.args[2]
        self.assertIn('"id": "native-events-versus-consumer-progress"', prompt)
        self.assertIn('"avoid_when":', prompt)
        sandbox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
