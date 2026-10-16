"""Small default lessons must remain available within Scout's existing budget."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class DefaultKnowledgeBudgetTests(unittest.TestCase):
    def test_inherited_imports_do_not_imply_uv_dependency_reuse(self):
        result = lesson_suggestions("uv --system-site-packages inherited base distributions")
        card = next(c for c in result["matches"] if c["id"] == "separate-dependency-transport-from-native-tests")
        self.assertIn("uv list/install ignore them", card["lesson"])
        self.assertIn("where upstream requires uv", card["lesson"])
        self.assertTrue(any("#uv-venv--system-site-packages" in e["url"] for e in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)

    def test_private_target_advice_checks_loaded_dependency_not_only_metadata(self):
        result = lesson_suggestions("pip --target .pth site.addsitedir distribution metadata")
        card = result["matches"][0]
        self.assertEqual(card["id"], "separate-dependency-transport-from-native-tests")
        self.assertIn("does not process its .pth files", card["lesson"])
        self.assertIn("old globally imported module", card["lesson"])
        self.assertIn("__file__ before testing", card["lesson"])
        self.assertTrue(any("import lines" in e["note"] for e in card["evidence"]))
        self.assertTrue(any("--no-deps" in e["note"] for e in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_dependency_probe_advice_does_not_replace_upstream_qualification(self):
        result = lesson_suggestions("dependency transport stdlib-only public-caller test package")
        card = next(c for c in result["matches"] if c["id"] == "separate-dependency-transport-from-native-tests")
        self.assertIn("complete original source and module files", card["lesson"])
        self.assertIn("do not rename it an upstream baseline", card["lesson"])
        self.assertIn("not accepted semantics, novelty or PR readiness", card["avoid_when"])
        self.assertIn("Do not remove production files", card["avoid_when"])
        self.assertTrue(any(e["url"].endswith("/cast/pull/359") for e in card["evidence"]))
        self.assertEqual(result["oversized_matches_omitted"], 0)

    def test_future_completion_advice_keeps_atomicity_and_cancellation_contract(self):
        result = lesson_suggestions("concurrent Future cross-thread completion cancellation commit")
        card = result["matches"][0]
        self.assertEqual(card["id"], "cross-thread-future-completion-commit")
        self.assertIn("only when", card["lesson"])
        self.assertIn("not when it starts", card["lesson"])
        self.assertIn("normally before work starts", card["lesson"])
        self.assertIn("needs maintainer review", card["lesson"])
        self.assertIn("asyncio.Future", card["avoid_when"])
        self.assertIn("full pre-commit", card["avoid_when"])
        self.assertIn("Retrospective", card["evidence"][2]["note"])
        self.assertTrue(any(
            "result-only partial repair" in item["note"]
            and "deliberate mutation" in item["note"]
            and "No model/selector utility" in item["note"]
            for item in card["evidence"]
        ))
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_tma_advice_keeps_descriptor_and_dummy_consumer_semantics(self):
        result = lesson_suggestions(
            "TMA descriptor signed coordinates dummy rows OOB fill"
        )
        card = next(
            match
            for match in result["matches"]
            if match["id"] == "native-binding-semantics-before-field-inference"
        )
        self.assertIn("coordinates are signed", card["lesson"])
        self.assertIn("segment boundaries", card["lesson"])
        self.assertIn("producer/barrier step", card["lesson"])
        self.assertIn("Descriptor acceptance does not prove", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertTrue(any("#L1477-L1479" in item["url"] for item in card["evidence"]))

    def test_native_partial_construction_advice_checks_the_factory_owner(self):
        result = lesson_suggestions(
            "RDMA QP partial construction factory shared_ptr destructor"
        )
        card = next(
            match
            for match in result["matches"]
            if match["id"] == "dma-teardown-failure-retention"
        )
        self.assertIn("local shared_ptr", card["lesson"])
        self.assertIn("before publishing", card["lesson"])
        self.assertIn("directly retrying", card["avoid_when"])
        self.assertIn("bounded retries", card["avoid_when"])
        self.assertIn("no native RDMA failure-injection result", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        urls = [evidence["url"] for evidence in card["evidence"]]
        for suffix in (
            "endpoint_store.cpp#L62-L75",
            "rdma_endpoint.cpp#L110-L126",
            "rdma_endpoint.cpp#L309-L376",
            "rdma_endpoint.cpp#L621-L641",
            "rdma_endpoint.cpp#L219-L268",
        ):
            self.assertTrue(any(url.endswith(suffix) for url in urls))

    def test_cutlass_array_advice_uses_receiver_contract_not_python_list_semantics(
        self,
    ):
        result = lesson_suggestions("CUTLASS Array slice vector start count")
        card = result["matches"][0]
        self.assertEqual(card["id"], "cutlass-array-vector-slice-count")
        self.assertIn("arr[start:count]", card["lesson"])
        self.assertIn("nonzero offset", card["lesson"])
        self.assertIn("receiver's construction", card["lesson"])
        self.assertTrue(
            any(
                "not an installed dependency or GPU-kernel test" in item["note"]
                for item in card["evidence"]
            )
        )
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_backend_state_advice_keeps_reference_and_native_scopes_distinct(self):
        result = lesson_suggestions(
            "backend conv_state cache update missing tuple return assignment mutation"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "backend-state-mutation-contract")
        self.assertIn("dependency version", card["lesson"])
        self.assertIn("state alias", card["lesson"])
        self.assertIn("do not prove native CUDA", card["avoid_when"])
        self.assertIn("Reopen", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_mode_advice_preserves_the_warmup_transition_and_limits(self):
        result = lesson_suggestions(
            "training no-grad inference-mode warmup checkpoint policy memory budget"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "training-and-grad-mode-dispatch")
        self.assertIn("grad-enabled training", card["lesson"])
        self.assertIn("explicit", card["lesson"])
        self.assertIn("measured memory-budget", card["avoid_when"])
        self.assertNotIn("qualified", result)

    def test_failed_warmup_advice_keeps_mode_and_readiness_separate(self):
        result = lesson_suggestions("DeepGEMM warmup compile mode initialization retry")
        card = result["matches"][0]
        self.assertEqual(card["id"], "training-and-grad-mode-dispatch")
        self.assertIn("restoring one does not repair the other", card["lesson"])
        self.assertIn("clear only the failed group's marker", card["lesson"])
        self.assertIn("same-key retry", card["lesson"])
        self.assertIn("reentrancy", card["lesson"])
        self.assertIn("mocked GPU/executor", card["avoid_when"])
        self.assertIn("corrupted CUDA context", card["avoid_when"])
        self.assertIn("prospective evidence-selector utility", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertTrue(any("43712" in entry["url"] for entry in card["evidence"]))
        self.assertNotIn("qualified", result)

    def test_training_guard_counterexample_is_visible_without_native_claims(self):
        result = lesson_suggestions("GatedDeltaNet training no-grad recurrent dispatch chunk")
        card = result["matches"][0]
        self.assertEqual(card["id"], "training-and-grad-mode-dispatch")
        self.assertIn("every visible guard", card["lesson"])
        self.assertIn("not self.training", card["lesson"])
        self.assertIn("visible exclusion is not missing context", card["lesson"])
        evidence = next(item for item in card["evidence"] if "gated_deltanet.py" in item["url"])
        self.assertIn("Source-only counterexample", evidence["note"])
        self.assertIn("Explicit fused_recurrent", evidence["note"])
        self.assertIn("does not execute FLA", evidence["note"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_http_options_advice_distinguishes_wrapper_deadline_and_retry(self):
        result = lesson_suggestions(
            "HTTP listing per-call request options trailing-slash retry"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "request-options-through-retry-adapters")
        self.assertIn("wrapper's wait deadline", card["lesson"])
        self.assertIn("initial-request-only repair", card["lesson"])
        self.assertIn("defaults were not mutated", card["lesson"])
        self.assertIn("Pyodide/XHR", card["avoid_when"])
        self.assertIn("prospective evidence-selector utility", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_default_cards_fit_the_existing_advisory_budget(self):
        for path in knowledge_notes.DEFAULT_DIRECTORY.glob("*.json"):
            with self.subTest(card=path.name):
                card = json.loads(path.read_text(encoding="utf-8"))
                self.assertLessEqual(
                    len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
                )

    def test_scheduler_advice_keeps_transient_and_rounded_ceilings_distinct(self):
        result = lesson_suggestions(
            "scheduler remaining_budget max_num_tokens max_context_length livelock"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "scheduler-budget-feasibility-before-deferral")
        self.assertIn("same argument", card["lesson"])
        self.assertIn("alignment-rounded", card["lesson"])
        self.assertIn("would progress next iteration", card["lesson"])
        self.assertIn("External mutation", card["avoid_when"])
        self.assertIn("not installed-package execution", card["avoid_when"])
        self.assertIn("prospective selector utility", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_configuration_advice_retains_its_contract_and_scope(self):
        result = lesson_suggestions("configuration CLI parser plugin consumer backend")
        card = result["matches"][0]
        self.assertEqual(card["id"], "consumer-contract-before-regression")
        self.assertEqual(card["status"], "counterexample")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertIn("supported caller", card["lesson"])
        self.assertIn("External or dynamic callers", card["avoid_when"])

    def test_native_guard_advice_distinguishes_storage_and_logical_region(self):
        result = lesson_suggestions(
            "torch.as_strided raw capacity out of bounds storage view validation"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "native-operation-inherited-guards")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("logical subregion", card["avoid_when"])
        self.assertIn("meta/symbolic", card["avoid_when"])
        self.assertNotIn("qualified", result)

    def test_sharding_advice_binds_the_registered_operator_not_its_neighbor(self):
        result = lesson_suggestions(
            "custom_sharding output count fused four tensors",
            source_urls=[
                "https://raw.githubusercontent.com/pytorch/ao/"
                "f7c8353e8adeefc008a32169e6f92f8271d15e2d/"
                "torchao/prototype/moe_training/kernels/mxfp8/quant.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "registered-operator-identity-before-arity")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("complete operator name", card["lesson"])
        self.assertIn("source-only counterexample", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_amx_alias_advice_keeps_native_schema_and_caller_limits(self):
        result = lesson_suggestions(
            "VisionAMXAttention softmax_scale forwarding native backend",
            source_urls=[
                "https://raw.githubusercontent.com/sgl-project/sglang/"
                "4e85e8ed3738ac9d7686946fb6db7242bc66a2a9/"
                "python/sglang/srt/layers/attention/vision.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "registered-operator-identity-before-arity")
        self.assertIn("torch.ops.sgl_kernel", card["lesson"])
        self.assertIn("schema has no softmax_scale", card["lesson"])
        self.assertIn("does not prove every model is protected", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_windows_permission_witness_does_not_rewrite_old_runtime_claims(self):
        result = lesson_suggestions(
            "ReadOnlyFs EPERM errors.Is Windows permission classification",
            source_urls=[
                "https://raw.githubusercontent.com/spf13/afero/"
                "eb6a92826ea568e3f40ab91fcbda8d2b38b61d3e/readonlyfs.go"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "go-native-platform-witness")
        self.assertIn("pkg/errors assertions", card["avoid_when"])
        self.assertIn("Afero.WriteFile wrapper reproduction", card["avoid_when"])
        evidence = next(row for row in card["evidence"] if "issuecomment-6213631370" in row["url"])
        self.assertIn("not 18 independent defects", evidence["note"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_native_guard_advice_keeps_safe_kernel_witness_scope(self):
        result = lesson_suggestions(
            "KDA padded key mask NaN gate guard",
            source_urls=[
                "https://raw.githubusercontent.com/vllm-project/vllm/"
                "716c5225aefa7aae0628d88a6d58adddbca7c22c/"
                "vllm/third_party/flash_linear_attention/ops/fused_recurrent.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "native-operation-inherited-guards")
        self.assertIn("accessible task-owned guard cells", card["lesson"])
        self.assertIn("not an out-of-allocation sanitizer", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)


if __name__ == "__main__":
    unittest.main()
