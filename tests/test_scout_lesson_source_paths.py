"""Source affinity is optional advice, not a current-version correctness verdict."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
import scout_lesson_context as lessons

REV = "a" * 40
OLD = "b" * 40
RAW = f"https://raw.githubusercontent.com/owner/project/{REV}/src/operator.py"


def card(name, url, body="Check all guards; this source is not a native test."):
    return dict(
        id=name, title=name, applies_when="Read the current implementation.",
        lesson=body, avoid_when="Other versions may differ; never auto-reject.",
        status="counterexample", evidence=[dict(url=url, note="Source only.")],
    )


class SourceLessonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "lessons"
        self.library.mkdir()
        self.generic = card("generic-regression", "https://example.org/context",
                            "regression correctness production " * 4)
        self.focused = card("specific-guard", f"https://github.com/owner/project/blob/{OLD}/src/operator.py#L10-L20")
        self.save(self.generic)
        self.save(self.focused)

    def save(self, value):
        (self.library / (value["id"] + ".json")).write_text(
            json.dumps(value), encoding="utf-8"
        )

    def lookup(self, urls, **kwargs):
        return lessons.lesson_suggestions(
            "production correctness regression", source_urls=urls,
            directory=self.library, **kwargs
        )

    def test_same_repo_full_path_cross_revision_beats_generic_prose(self):
        baseline = lessons.lesson_suggestions(
            "production correctness regression", directory=self.library
        )
        self.assertEqual(baseline["matches"], [self.generic])
        actual = self.lookup([RAW])
        self.assertEqual(actual["matches"], [self.focused])
        self.assertTrue(actual["source_path_match"])
        self.assertEqual(actual["status"], "ADVISORY_MATCH")
        self.assertNotIn("qualified", actual)
        self.assertNotIn(str(self.root), json.dumps(actual))

    def test_exact_revision_ranks_before_other_same_file_cards(self):
        exact = card("z-exact", RAW, "Exact revision source; still check applicability.")
        self.save(exact)
        self.assertEqual(self.lookup([RAW] * 10)["matches"], [exact])

    def test_other_repo_directory_case_and_mutable_refs_are_not_matches(self):
        for url in (
            RAW.replace("owner/project", "another/project"),
            RAW.replace("/src/", "/tests/"),
            RAW.replace("operator.py", "Operator.py"),
            RAW.replace(REV, "main"),
            RAW.replace("https:", "http:"),
            RAW.replace("raw.githubusercontent.com", "raw.githubusercontent.com.evil.org"),
            RAW.replace("https://", "https://user:secret@"),
            RAW.replace("/src/", "/src/../src/"),
            "https://github.com/owner/project/issues/1",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.lookup([url])["matches"], [self.generic])

    def test_equal_source_affinity_uses_query_relevance_not_alphabetic_id(self):
        relevant = card("z-pickle-policy", self.focused["evidence"][0]["url"],
                        "Preserve pickle cache_options maxblocks trim reopen policy.")
        self.save(relevant)
        result = lessons.lesson_suggestions(
            "pickle cache_options maxblocks trim", source_urls=[RAW],
            directory=self.library,
        )
        self.assertEqual(result["matches"], [relevant])
        self.assertTrue(result["source_path_match"])
        exact = dict(self.focused, evidence=[dict(url=RAW, note="Exact revision.")])
        self.save(exact)
        self.assertEqual(lessons.lesson_suggestions(
            "pickle cache_options maxblocks trim", source_urls=[RAW],
            directory=self.library,
        )["matches"], [exact])

    def test_imported_api_anchors_preserve_existing_source_text_interface(self):
        expected = {
            "import torch as pt\npt.bool": "bool pt",
            "from torch import nn as layers\nlayers.Linear": "layers linear",
            '17: import (\n18: h "net/http"\n19: )\n20: h.DefaultClient.Do(req)':
                "defaultclient do http",
            'const hf = await import("@huggingface/transformers");\nhf.AutoTokenizer.from_pretrained(n)':
                "autotokenizer from_pretrained hf transformers",
            "hf = eval('import(\"@huggingface/transformers\")');\nhf.AutoTokenizer.from_pretrained(n)":
                "autotokenizer from_pretrained hf transformers",
            "row.name; db.prepare; torch.bool": "",
            'const hf = await import(moduleName);\nhf.AutoTokenizer.from_pretrained(n)': "",
            "hf = eval(expression);\nhf.AutoTokenizer.from_pretrained(n)": "",
        }
        for source, terms in expected.items():
            with self.subTest(source=source):
                self.assertEqual(lessons.source_api_query(source), terms)
        self.assertEqual(lessons.source_api_query("x" * lessons.MAX_SOURCE_CHARS
                         + "\nimport torch\ntorch.bool"), "")
        self.assertLessEqual(len(lessons.source_api_query(
            "import public\n" + " ".join(f"public.api{i}" for i in range(3000))
        )), lessons.MAX_QUERY_CHARS)

    def test_imported_api_advice_does_not_displace_source_identity_or_budget(self):
        imported = card("torch-bool-cache-policy", "https://example.org/evidence",
                        "Observe torch bool before assigning a dtype bug.")
        self.save(imported)
        source = "import torch\ntorch.ones(n, dtype=torch.bool)"
        result = lessons.lesson_suggestions(
            "production correctness regression", source_text=source,
            directory=self.library,
        )
        self.assertEqual(result["matches"], [imported])
        self.assertTrue(result["source_query_used"])
        same_file = self.lookup([RAW], source_text=source)
        self.assertEqual(same_file["matches"], [self.focused])
        self.assertFalse(same_file["source_query_used"])
        excluded = lessons.lesson_suggestions(
            "production correctness regression", source_text=source,
            directory=self.library, exclude=[imported["id"]],
        )
        self.assertEqual(excluded["matches"], [self.generic])
        self.assertNotIn("qualified", result)

    def test_exclusion_size_and_url_budget_preserve_generic_fallback(self):
        self.assertEqual(self.lookup([RAW], exclude=[self.focused["id"]])["matches"], [self.generic])
        self.save(dict(self.focused, lesson="x" * (lessons.MAX_CARD_BYTES + 1)))
        actual = self.lookup([RAW])
        self.assertEqual(actual["matches"], [self.generic])
        self.assertGreaterEqual(actual["oversized_matches_omitted"], 1)
        self.save(self.focused)
        self.assertEqual(self.lookup(["https://example.org/none"] * 16 + [RAW])["matches"], [self.generic])

    def test_fitting_still_drops_whole_card_not_primary_source(self):
        packet = dict(sources=[dict(url=RAW, text="primary evidence")],
                      lesson_suggestions=self.lookup([RAW]))
        original = copy.deepcopy(packet)
        lessons.fit_lesson_context(packet, 1)
        self.assertNotIn("lesson_suggestions", packet)
        self.assertEqual(packet["sources"], original["sources"])

    def test_partial_gated_deltanet_window_finds_guard_without_imports(self):
        url = (
            "https://raw.githubusercontent.com/fla-org/flash-linear-attention/"
            "78a39922d56562336e22e5a429b039f34ef2bf7f/fla/layers/gated_deltanet.py"
        )
        result = lessons.lesson_suggestions(
            "Find bounded, production-reachable model-layer or wrapper correctness "
            "gaps with a focused regression. Check existing tests, supported backend "
            "and exact caller before proposing a kernel change. gated_deltanet.py",
            source_urls=[url],
        )
        self.assertEqual(result["matches"][0]["id"], "training-and-grad-mode-dispatch")
        self.assertIn("not self.training", result["matches"][0]["lesson"])
        self.assertNotIn("qualified", result)

    def test_workspace_fallback_card_keeps_false_and_exception_distinct(self):
        url = (
            "https://raw.githubusercontent.com/sgl-project/sglang/"
            "44be30d2165318011fa1e9002cf58d6061907ed4/"
            "python/sglang/srt/layers/flashinfer_comm_fusion.py"
        )
        result = lessons.lesson_suggestions(
            "dtype change silently reuses a workspace after size rejection",
            source_urls=[url],
        )
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "exception-fallback-versus-validator-rejection")
        self.assertTrue(result["source_path_match"])
        self.assertLessEqual(len(json.dumps(matched, ensure_ascii=False).encode()), lessons.MAX_CARD_BYTES)
        self.assertIn("False", matched["lesson"])
        self.assertIn("arbitrary raising fake", matched["lesson"])
        self.assertIn("static version-bound evidence", matched["avoid_when"])
        self.assertEqual(matched["status"], "counterexample")

    def test_callable_hash_card_keeps_fallback_and_compiler_scope_distinct(self):
        url = (
            "https://raw.githubusercontent.com/Dao-AILab/flash-attention/"
            "e9d8944c855489e03c66262d07ba4c81d9d8dd31/flash_attn/cute/utils.py"
        )
        result = lessons.lesson_suggestions(
            "hash_callable missing co_consts causes a wrong compiled cache hit",
            source_urls=[url],
        )
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "callable-hash-fallback-reachability")
        self.assertTrue(result["source_path_match"])
        self.assertLessEqual(len(json.dumps(matched, ensure_ascii=False).encode()), lessons.MAX_CARD_BYTES)
        self.assertIn("inspect.getsource", matched["lesson"])
        self.assertIn("wrapper construction is not kernel compilation", matched["lesson"])
        self.assertIn("not the whole FlashAttention package", matched["avoid_when"])
        self.assertEqual(matched["status"], "counterexample")

    def test_helper_contract_card_fits_and_retains_callee_counterexample(self):
        url = (
            "https://raw.githubusercontent.com/pelletier/go-toml/"
            "686c980c47581bf19b6119b60e9a59f2aed04170/decode.go"
        )
        result = lessons.lesson_suggestions(
            "Check asymmetric validation in the caller and callee", source_urls=[url]
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertTrue(result["source_path_match"])
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "helper-contract-and-owner-lifetime")
        self.assertLessEqual(
            len(json.dumps(matched, ensure_ascii=False).encode()),
            lessons.MAX_CARD_BYTES,
        )
        self.assertTrue(any("parseLocalDate" in item["note"] for item in matched["evidence"]))
        self.assertIn("public helper", matched["avoid_when"].casefold())

    def test_shared_registration_card_fits_and_keeps_contract_limit(self):
        url = (
            "https://raw.githubusercontent.com/spf13/pflag/"
            "c966cfef47379dcb01e7929504d66d94b540945b/golangflag.go"
        )
        result = lessons.lesson_suggestions(
            "CopyToGoFlagSet string values and shared default initialization",
            source_urls=[url],
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertTrue(result["source_path_match"])
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "shared-variable-registration-side-effects")
        self.assertLessEqual(
            len(json.dumps(matched, ensure_ascii=False).encode()),
            lessons.MAX_CARD_BYTES,
        )
        self.assertIn("newStringValue", matched["lesson"])
        self.assertIn("explicit empty value", matched["lesson"])
        self.assertIn("pre-parse-only", matched["avoid_when"])
        self.assertNotIn("qualified", result)

    def test_research_emitter_supplies_source_urls_without_extra_source_reads(self):
        root = self.root / "run"
        scout.initialize(root)
        spec = dict(repo="owner/project", question="production correctness regression",
                    source_prefixes=["src/"])
        config = self.root / "config.json"
        config.write_text(json.dumps(dict(objective="test", queue_target=8, repos=[spec])), encoding="utf-8")
        producer = research.ResearchProducer(root, config, context=object())
        source = dict(url=RAW, text="121: partial source without imports")
        real = lessons.lesson_suggestions

        def lookup(*args, **kwargs):
            self.assertEqual(kwargs["source_text"], source["text"])
            return real(*args, **kwargs, directory=self.library)

        with patch.object(research, "lesson_suggestions", side_effect=lookup):
            self.assertTrue(producer.emit("key", spec, [source], "discovery"))
        with scout.connect(root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(packet["lesson_suggestions"]["matches"], [self.focused])
        self.assertEqual(packet["sources"], [source])

    def test_real_library_ambiguous_query_retains_source_bound_advice_in_packet(self):
        root = self.root / "real-library-run"
        scout.initialize(root)
        spec = dict(repo="sgl-project/sglang", source_prefixes=["python/"],
                    question="uninitialized Python local walrus enclosing guards")
        config = self.root / "real-library-config.json"
        config.write_text(json.dumps(dict(objective="test", queue_target=8, repos=[spec])), encoding="utf-8")
        producer = research.ResearchProducer(root, config, context=object())
        source = dict(
            url="https://raw.githubusercontent.com/sgl-project/sglang/"
                "11bfd868ac36c0d5c7089c3f1a65ed575feb5540/"
                "python/sglang/srt/layers/attention/attention_registry.py",
            text="388: if cfg := mambaish_config(model_config):",
        )
        self.assertTrue(producer.emit("source-bound-contract", spec, [source], "discovery"))
        with scout.connect(root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        advice = packet["lesson_suggestions"]
        self.assertTrue(advice["source_path_match"])
        self.assertEqual(advice["matches"][0]["id"], "consumer-contract-before-regression")
        self.assertIn("clipped branch cannot establish absence", advice["matches"][0]["lesson"])
        self.assertEqual(packet["sources"], [source])

    def test_callee_mutex_advice_retains_pair_atomicity_limit(self):
        url = (
            "https://raw.githubusercontent.com/spf13/afero/"
            "eb6a92826ea568e3f40ab91fcbda8d2b38b61d3e/mem/file.go"
        )
        result = lessons.lesson_suggestions(
            "Check setter synchronization before claiming a data race",
            source_urls=[url],
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertTrue(result["source_path_match"])
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "helper-contract-and-owner-lifetime")
        self.assertLessEqual(
            len(json.dumps(matched, ensure_ascii=False).encode()),
            lessons.MAX_CARD_BYTES,
        )
        evidence = next(item for item in matched["evidence"] if "/mem/file.go" in item["url"])
        self.assertIn("atomic pair", evidence["note"])
        self.assertIn("not all-race proof", evidence["note"])

    def test_pickle_policy_card_preserves_runtime_cache_exclusion_and_replacement(self):
        url = (
            "https://raw.githubusercontent.com/fsspec/filesystem_spec/"
            "76ba99e652820d997dbaab9eebda1e2215f6c4ff/fsspec/spec.py"
        )
        result = lessons.lesson_suggestions(
            "pickle cache_options maxblocks trim reopen policy", source_urls=[url]
        )
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "serialization-policy-without-runtime-cache")
        self.assertTrue(result["source_path_match"])
        self.assertIn("populated cache bytes", matched["lesson"])
        self.assertIn("AllBytes replacement", matched["lesson"])
        self.assertIn("unpicklable", matched["avoid_when"])
        self.assertIn("proposed unmerged", json.dumps(matched).lower())
        self.assertLessEqual(len(json.dumps(matched).encode()), lessons.MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)

    def test_pickle_card_is_relevant_across_revision_ties(self):
        url = (
            "https://raw.githubusercontent.com/fsspec/filesystem_spec/"
            + "b" * 40 + "/fsspec/spec.py"
        )
        result = lessons.lesson_suggestions(
            "pickle cache_options maxblocks trim reopen policy", source_urls=[url]
        )
        self.assertTrue(result["source_path_match"])
        self.assertEqual(result["matches"][0]["id"],
                         "serialization-policy-without-runtime-cache")

    def test_serialized_exception_advice_keeps_transport_and_strategy_limits(self):
        url = (
            "https://raw.githubusercontent.com/nhairs/python-json-logger/"
            "366c14f23ba3f8fb6c02804f4b2c9192cd948ac3/src/pythonjsonlogger/core.py"
        )
        result = lessons.lesson_suggestions(
            "cached exception exc_text SocketHandler formatter options", source_urls=[url]
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertTrue(result["source_path_match"])
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "serialized-fallback-option-parity")
        self.assertEqual(matched["status"], "hypothesis")
        self.assertIn("without opening a socket", matched["lesson"])
        self.assertIn("untrusted pickle", matched["avoid_when"])
        self.assertIn("broader evidence-choice strategy remains a hypothesis",
                      matched["avoid_when"])
        self.assertLessEqual(len(json.dumps(matched).encode()), lessons.MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)

    def test_known_stream_timeout_scope_is_not_renamed_as_new_regression(self):
        result = lessons.lesson_suggestions(
            "InferenceTimeoutError ReadTimeout streaming after first token",
            source_urls=["https://raw.githubusercontent.com/huggingface/huggingface_hub/"
                         "bb2ef7579c3d2dc2eb49b16ccf15a070fe5b7023/"
                         "src/huggingface_hub/inference/_client.py"],
        )
        self.assertTrue(result["source_path_match"])
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "closed-issue-subcase-coverage")
        reference = next(e for e in matched["evidence"] if e["url"].endswith("/pull/5150"))
        self.assertIn("known streaming limitation", reference["note"])
        self.assertIn("not proof it is desirable or permanently rejected", reference["note"])
        self.assertIn("before setup", matched["lesson"])
        self.assertLessEqual(len(json.dumps(matched).encode()), lessons.MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_existing_seek_fix_does_not_hide_a_return_contract_subcase(self):
        url = (
            "https://raw.githubusercontent.com/fsspec/filesystem_spec/"
            "16fad6169ad2c61e9e7afc6791ab9f560ed21ee0/fsspec/implementations/http.py"
        )
        result = lessons.lesson_suggestions(
            "No-op seek returns None despite an existing merged fix", source_urls=[url]
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertTrue(result["source_path_match"])
        matched = result["matches"][0]
        self.assertEqual(matched["id"], "closed-issue-subcase-coverage")
        self.assertIn("does not require", matched["lesson"])
        self.assertIn("does not prove async", matched["avoid_when"])
        self.assertLessEqual(len(json.dumps(matched).encode()), lessons.MAX_CARD_BYTES)


if __name__ == "__main__":
    unittest.main()
