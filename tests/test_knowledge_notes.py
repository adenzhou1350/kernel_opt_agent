"""Check the small public library's editing and retrieval boundaries."""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import knowledge_notes as notes  # noqa: E402


class KnowledgeNotesTests(unittest.TestCase):
    def test_diagnostic_requirement_advice_keeps_source_only_scope(self):
        from scout_lesson_context import lesson_suggestions

        advice = lesson_suggestions("reversed error message diagnostic requirement comparison")
        card = advice["matches"][0]
        self.assertEqual(card["id"], "diagnostic-requirement-versus-observation")
        self.assertIn("count >= N", card["lesson"])
        self.assertIn("exact boundary equality", card["lesson"])
        self.assertIn("received too few", card["avoid_when"])
        self.assertIn("neither runtime reachability", card["avoid_when"])
        self.assertEqual(advice["oversized_matches_omitted"], 0)

    def test_readinto_advice_keeps_byte_and_native_scope_boundaries(self):
        from scout_lesson_context import lesson_suggestions

        advice = lesson_suggestions("readinto typed memoryview buffer bytes position")
        self.assertEqual(advice["status"], "ADVISORY_MATCH")
        card = advice["matches"][0]
        self.assertEqual(card["id"], "readinto-buffer-validation-before-consumption")
        self.assertIn("before consuming input", card["lesson"])
        self.assertIn("not byte capacity", card["lesson"])
        self.assertIn("failure leaves the position", card["lesson"])
        self.assertIn("nbytes alone does not establish contiguity", card["avoid_when"])
        self.assertIn("not zero-copy I/O", card["avoid_when"])
        self.assertIn("prospective evidence-selection utility", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_native_registration_advice_keeps_cleanup_and_protocol_limits(self):
        from scout_lesson_context import lesson_suggestions

        advice = lesson_suggestions("newListener listener registration cancellation")
        self.assertEqual(advice["status"], "ADVISORY_MATCH")
        card = advice["matches"][0]
        self.assertEqual(card["id"], "cancellation-before-listener-registration")
        self.assertIn("before inserting the listener", card["lesson"])
        self.assertIn("after addListener returns", card["lesson"])
        self.assertIn("caller-owned listeners", card["lesson"])
        self.assertIn("correctly rejected promise alone", card["avoid_when"])
        self.assertIn("not the Node22/26 CI matrix", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_cold_thenable_advice_reaches_scout_without_native_promise_overclaim(self):
        from scout_lesson_context import lesson_suggestions

        advice = lesson_suggestions("cold thenable async iterator subscription getter")
        self.assertEqual(advice["status"], "ADVISORY_MATCH")
        card = advice["matches"][0]
        self.assertEqual(card["id"], "normalize-cold-thenables-once")
        self.assertIn("consumption happens inside then", card["lesson"])
        self.assertIn("synchronous iterator fast path", card["lesson"])
        self.assertIn("not itself double execution", card["avoid_when"])
        self.assertIn("not an upstream PR or merge", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_vector_layout_advice_reaches_scout_without_forward_only_claim(self):
        from scout_lesson_context import lesson_suggestions

        advice = lesson_suggestions("rank-one strided vector upstream gradient")
        self.assertEqual(advice["status"], "ADVISORY_MATCH")
        card = advice["matches"][0]
        self.assertEqual(card["id"], "vector-input-and-gradient-strides")
        self.assertIn("every supported input gradient", card["lesson"])
        self.assertIn("forward-only validation cannot", card["lesson"])
        self.assertIn("do not add redundant copies", card["avoid_when"])
        self.assertIn("prospective evidence-selection utility", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_resource_recovery_advice_reaches_scout_with_cache_caveat(self):
        from scout_lesson_context import lesson_suggestions

        advice = lesson_suggestions("ZeRO-3 nonpersistent recovery release")
        self.assertEqual(advice["status"], "ADVISORY_MATCH")
        card = advice["matches"][0]
        self.assertEqual(card["id"], "regression-discrimination-by-contract-cell")
        self.assertIn("finite loss", card["lesson"])
        self.assertIn("before backward/step", card["lesson"])
        self.assertIn("legitimately retains", card["avoid_when"])
        self.assertIn("not an accepted upstream PR", card["avoid_when"])
        self.assertTrue(any("12fbd66fc83042121ecba0c8b66810d3656b8e71" in e["url"]
                            for e in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_dma_teardown_advice_retains_dependency_and_evidence_limits(self):
        result = notes.search("RDMA DMA teardown deregistration failure buffers")
        card = result["matches"][0]["card"]
        self.assertEqual(card["id"], "dma-teardown-failure-retention")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("independent resource may be safe", card["avoid_when"])
        self.assertIn("source evidence", card["avoid_when"])
        self.assertIn("native RDMA failure-injection", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_packed_prefill_advice_keeps_version_and_execution_scope(self):
        result = notes.search("KDA packed token sequence count FlashInfer ordinary prefill")
        card = result["matches"][0]["card"]
        self.assertEqual(card["id"], "packed-prefill-capability-boundary")
        self.assertIn("total_tokens > num_sequences", card["lesson"])
        self.assertIn("specific to the cited FlashInfer version", card["avoid_when"])
        self.assertIn("not official registered-test", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_uninitialized_local_advice_retains_enclosing_assignment_and_scope(self):
        result = notes.search("uninitialized Python local walrus enclosing guards")
        cards = {entry["card"]["id"]: entry["card"] for entry in result["matches"]}
        self.assertIn("consumer-contract-before-regression", cards)
        card = cards["consumer-contract-before-regression"]
        self.assertIn("clipped branch cannot establish absence", card["lesson"])
        evidence = [e for e in card["evidence"] if "attention_registry.py" in e["url"]]
        self.assertEqual(len(evidence), 1)
        self.assertIn("cfg := mambaish_config", evidence[0]["note"])
        self.assertIn("not GPU execution", evidence[0]["note"])
        from scout_lesson_context import lesson_suggestions

        actual = lesson_suggestions("consumer contract uninitialized Python local cfg walrus")
        self.assertEqual(actual["matches"][0]["id"], card["id"])
        self.assertEqual(actual["oversized_matches_omitted"], 0)
        self.assertLessEqual(len(json.dumps(actual["matches"][0]).encode()), 8192)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "lessons"
        self.card = {
            "id": "graph-overhead",
            "title": "Graph launch overhead",
            "applies_when": "Measuring graph replay.",
            "lesson": "Measure the production execution mode.",
            "avoid_when": "Only eager execution is used.",
            "evidence": [
                {"url": "https://docs.python.org/3/", "note": "Context only."}
            ],
            "status": "hypothesis",
        }

    def write_card(self, card):
        self.directory.mkdir(exist_ok=True)
        path = self.directory / (card["id"] + ".json")
        path.write_text(json.dumps(card), encoding="utf-8")
        return path

    def test_add_exact_repeat_and_explicit_update(self):
        result = notes.add_note(self.card, self.directory)
        path = Path(result["source"])
        original = path.read_bytes()
        original_time = path.stat().st_mtime_ns
        self.assertEqual(
            "unchanged", notes.add_note(self.card, self.directory)["action"]
        )
        self.assertEqual(original_time, path.stat().st_mtime_ns)
        changed = dict(self.card, status="validated")
        with self.assertRaisesRegex(ValueError, "--replace"):
            notes.add_note(changed, self.directory)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(
            "replaced", notes.add_note(changed, self.directory, replace=True)["action"]
        )
        self.assertEqual("validated", notes.read_card(path)["status"])

    def test_cross_id_title_or_content_duplicates_do_not_write(self):
        notes.add_note(self.card, self.directory)
        variants = [
            dict(
                self.card,
                id="other-title",
                title=" GRAPH: launch overhead! ",
                lesson="Changed lesson.",
            ),
            dict(
                self.card,
                id="other-content",
                title="Another title",
                lesson="MEASURE the production execution mode!",
            ),
        ]
        for variant in variants:
            with self.subTest(id=variant["id"]):
                result = notes.add_note(variant, self.directory)
                self.assertEqual(
                    ("duplicate", self.card["id"]), (result["action"], result["id"])
                )
                self.assertFalse((self.directory / (variant["id"] + ".json")).exists())

    def test_replacement_cannot_duplicate_another_lesson(self):
        notes.add_note(self.card, self.directory)
        other = dict(
            self.card, id="other", title="Different title", lesson="Different lesson"
        )
        notes.add_note(other, self.directory)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            notes.add_note(
                dict(other, lesson=self.card["lesson"]), self.directory, replace=True
            )
        with self.assertRaisesRegex(ValueError, "existing lesson"):
            notes.add_note(
                dict(other, id="missing", title="Missing", lesson="Missing content"),
                self.directory,
                replace=True,
            )
        with self.assertRaisesRegex(ValueError, "existing lesson"):
            notes.add_note(dict(other, id="missing"), self.directory, replace=True)

    def test_bad_ids_and_private_evidence_rejected_before_writing(self):
        for bad_id in (
            "../escape",
            "a/b",
            "a\\b",
            "UPPER",
            "..",
            "C:drive",
            "a" * 81,
            "con",
            "lpt1",
        ):
            with self.subTest(id=bad_id), self.assertRaises(ValueError):
                notes.add_note(dict(self.card, id=bad_id), self.directory)
        for url in (
            "file:///tmp/run",
            "http://127.0.0.1/x",
            "http://10.0.0.2",
            "https://host.internal/run",
            "https://localhost/",
            "https://user:secret@example.com/x",
            "https://example.com:invalid",
        ):
            card = copy.deepcopy(self.card)
            card["evidence"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                notes.add_note(card, self.directory)
        self.assertFalse(self.directory.exists())

    def test_check_catches_hand_edited_duplicates_and_filename_mismatch(self):
        self.write_card(self.card)
        duplicate = dict(self.card, id="duplicate", title="graph LAUNCH overhead!")
        path = self.write_card(duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate title"):
            notes.read_cards(self.directory)
        path.unlink()
        (self.directory / "graph-overhead.json").rename(self.directory / "wrong.json")
        with self.assertRaisesRegex(ValueError, "Filename"):
            notes.read_cards(self.directory)

    def test_cli_invalid_json_and_missing_file_return_json_error(self):
        bad_file = Path(self.temp.name) / "bad.json"
        bad_file.write_text("{broken", encoding="utf-8")
        for source in (bad_file, Path(self.temp.name) / "missing.json"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = notes.main(
                    ["--directory", str(self.directory), "add", "--file", str(source)]
                )
            self.assertEqual(1, status)
            self.assertIn("error", json.loads(output.getvalue()))
        self.assertFalse(self.directory.exists())

    def test_search_is_deterministic_bounded_and_advisory(self):
        for card_id in ("zeta", "alpha", "delta", "beta"):
            notes.add_note(
                dict(
                    self.card,
                    id=card_id,
                    title=f"Graph {card_id}",
                    lesson=f"Recommendation for {card_id}",
                ),
                self.directory,
            )
        result = notes.search("GRAPH", self.directory)
        self.assertEqual(
            ["alpha", "beta", "delta"], [m["card"]["id"] for m in result["matches"]]
        )
        self.assertEqual(result, notes.search("GRAPH", self.directory))
        self.assertEqual(
            1, len(notes.search("graph", self.directory, limit=1)["matches"])
        )
        self.assertEqual([], notes.search("unmatched", self.directory)["matches"])
        self.assertIn("Advisory", result["caution"])
        self.assertTrue(Path(result["matches"][0]["source"]).is_file())
        for query, limit in (("", 3), ("!!!", 3), ("graph", 0)):
            with self.assertRaises(ValueError):
                notes.search(query, self.directory, limit)

    def test_invalid_structure_is_reported_not_silently_skipped(self):
        for card in (
            [],
            dict(self.card, status="ready"),
            dict(self.card, evidence=[]),
            dict(self.card, extra="private receipt"),
        ):
            with self.subTest(card=card), self.assertRaises(ValueError):
                notes.validate(card)
        self.directory.mkdir()
        (self.directory / "broken.json").write_text("[1]", encoding="utf-8")
        with self.assertRaises(ValueError):
            notes.search("graph", self.directory)

    def test_symlink_card_cannot_escape_library(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text(json.dumps(self.card), encoding="utf-8")
        self.directory.mkdir()
        try:
            (self.directory / "graph-overhead.json").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation unavailable on this host")
        with self.assertRaisesRegex(ValueError, "inside the library"):
            notes.add_note(self.card, self.directory, replace=True)
        self.assertEqual(self.card, json.loads(outside.read_text(encoding="utf-8")))

    def test_curated_library_validates_and_excludes_archives(self):
        cards = notes.read_cards(notes.DEFAULT_DIRECTORY)
        self.assertGreaterEqual(len(cards), 4)
        result = notes.search("precision graph production", limit=20)
        self.assertTrue(result["matches"])
        self.assertTrue(
            all(
                Path(m["source"]).parent == notes.DEFAULT_DIRECTORY
                for m in result["matches"]
            )
        )

    def test_consumer_impact_advice_is_retrievable_with_its_limits(self):
        result = notes.search("intermediate CSV consumer normalization config", limit=3)
        advice = next(
            match["card"]
            for match in result["matches"]
            if match["card"]["id"] == "production-path-and-impact"
        )
        self.assertIn("selected configs and errors", advice["lesson"])
        self.assertIn("own documented contract", advice["avoid_when"])
        self.assertIn("does not prove all consumers safe", advice["avoid_when"])
        self.assertTrue(
            any(
                item["url"] == "https://github.com/ROCm/aiter/pull/6303"
                for item in advice["evidence"]
            )
        )

    def test_native_offset_state_validation_is_retrievable(self):
        result = notes.search("ctypes seek native offset buffered position", limit=3)
        advice = next(match["card"] for match in result["matches"]
                      if match["card"]["id"] == "native-offset-validation-before-state-mutation")
        self.assertIn("seek(2**64)", advice["lesson"])
        self.assertIn("then commit the state", advice["lesson"])
        self.assertIn("not the Redis/MySQL/TiKV CI matrix", advice["avoid_when"])
        self.assertTrue(any(item["url"].endswith("issues/7657") for item in advice["evidence"]))

    def test_kernel_geometry_units_are_retrievable_without_a_cuda_claim(self):
        result = notes.search("swizzle int4 shared memory allocation", limit=3)
        advice = next(
            match["card"]
            for match in result["matches"]
            if match["card"]["id"] == "consumer-contract-before-regression"
        )
        self.assertIn("instantiate actual template constants", advice["lesson"])
        evidence = [item for item in advice["evidence"] if "TransformerEngine" in item["url"]]
        self.assertEqual(len(evidence), 2)
        self.assertTrue(any("not CUDA execution" in item["note"] for item in evidence))

    def test_inherited_test_fixture_counterexample_is_retrievable(self):
        result = notes.search("unittest inherited fixture exclusive file", limit=3)
        advice = next(match["card"] for match in result["matches"]
                      if match["card"]["id"] == "unittest-inherited-fixture-coverage")
        self.assertIn("SummaryTests", advice["lesson"])
        self.assertIn("deliberately shared contract tests", advice["avoid_when"])
        self.assertIn("not the full Redis/MySQL/TiKV CI matrix", advice["avoid_when"])
        self.assertTrue(any("70e513d6" in item["url"] for item in advice["evidence"]))


if __name__ == "__main__":
    unittest.main()
