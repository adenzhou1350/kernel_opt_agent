"""Small default lessons must remain available within Scout's existing budget."""

import doctest
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class DefaultKnowledgeBudgetTests(unittest.TestCase):
    def test_packed_cache_advice_separates_base_and_stride_contracts(self):
        result = lesson_suggestions(
            "MXFP8 packed cache stride alignment",
            source_urls=[
                "https://raw.githubusercontent.com/vllm-project/vllm/"
                "852989f580820849113d67d13fd8053e279d0444/"
                "vllm/models/deepseek_v4/nvidia/ops/dequant_gather_k_cutedsl.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "runtime-address-vector-alignment")
        self.assertTrue(result["source_path_match"])
        self.assertIn("base-pointer alignment", card["lesson"])
        self.assertIn("relaxing only the stride", card["lesson"])
        self.assertIn("do not also weaken the base", card["lesson"])
        self.assertIn("not merged", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_dependency_transport_advice_retains_target_marker_caveat(self):
        result = lesson_suggestions(
            "Requires-Dist target markers pure-Python dependency transport 3.14 3.12"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "separate-dependency-transport-from-native-tests")
        self.assertIn("Re-evaluate target Requires-Dist markers", card["lesson"])
        self.assertIn("3.14 need not be complete on 3.12", card["lesson"])
        self.assertTrue(any(item["url"].endswith("#environment-markers")
                            for item in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_reuse_configuration_advice_keeps_snapshot_and_reuse_controls(self):
        for revision in (
            "09f70d66b58962636c6a0adb8e5487d453ece859",
            "6b542a65405186573fd8439895ecbcee0ec647a5",
        ):
            with self.subTest(revision=revision):
                result = lesson_suggestions(
                    "mutable env dictionary cached worker configuration reuse",
                    source_urls=[
                        "https://raw.githubusercontent.com/joblib/loky/"
                        f"{revision}/loky/reusable_executor.py"
                    ],
                )
                card = result["matches"][0]
                self.assertEqual(card["id"], "snapshot-before-reuse-comparison")
                self.assertTrue(result["source_path_match"])
                self.assertIn("same dictionary", card["lesson"])
                self.assertIn("equal-content", card["lesson"])
                self.assertIn("worker PID", card["lesson"])
                self.assertIn("forced reuse", card["avoid_when"])
                self.assertIn("not a deep-copy recipe", card["avoid_when"])
                self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertNotIn("qualified", result)

    def test_annotation_qualifier_advice_preserves_metadata_and_contract_limits(self):
        result = lesson_suggestions(
            "TypedDict Annotated qualifier nesting required keys metadata",
            source_urls=[
                "https://raw.githubusercontent.com/agronholm/typeguard/"
                "cb8cee7a17af49498ad2465bbbdf8bfa8bf41a53/"
                "src/typeguard/_checkers.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "annotation-qualifier-composition")
        self.assertTrue(result["source_path_match"])
        self.assertIn("inner-before-outer", card["lesson"])
        self.assertIn("missing key", card["lesson"])
        self.assertIn("not permission to strip arbitrary wrappers", card["avoid_when"])
        self.assertIn("CI on another head", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_merged_pyee_source_retrieves_the_scoped_callback_lesson(self):
        result = lesson_suggestions(
            "review public source",
            source_urls=[
                "https://raw.githubusercontent.com/jfhbrook/pyee/"
                "283ce8a76fc5b35636d7dfe2ae0eaacd1eadc20a/pyee/trio.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "coroutine-callback-thread-hints")
        self.assertTrue(result["source_path_match"])
        self.assertIn("not a prospective budget-matched trial", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)

    def test_constructor_lifetime_answer_remains_available_as_advice(self):
        result = lesson_suggestions("caller contract owner lifetime NewVFS constructor")
        card = result["matches"][0]
        self.assertEqual(card["id"], "helper-contract-and-owner-lifetime")
        evidence = next(
            item for item in card["evidence"]
            if item["url"].endswith("/discussions/7690#discussioncomment-18936541")
        )
        self.assertIn("Answer selected by myangitzh", evidence["note"])
        self.assertIn("pkg/fs.NewFileSystem", evidence["note"])
        self.assertIn("behavior is real", evidence["note"])
        self.assertIn("public helper", card["avoid_when"].casefold())
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_comparison_advice_and_example_keep_protocol_and_scope(self):
        result = lesson_suggestions(
            "Python comparison reflected inequality NotImplemented mapping",
            source_urls=[
                "https://raw.githubusercontent.com/grantjenks/python-diskcache/"
                "ebfa37cd99d7ef716ec452ad8af4b4276a8e2233/diskcache/persistent.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "python-comparison-reflected-inequality")
        self.assertTrue(result["source_path_match"])
        self.assertIn("distinct truthy sentinels", card["lesson"])
        self.assertIn("MutableMapping inherits Mapping.__eq__", card["lesson"])
        self.assertIn("custom inequality semantics", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)
        example = Path(__file__).resolve().parents[1] / "docs/references/scout_known_case_calibration.md"
        failures, attempted = doctest.testfile(str(example), module_relative=False)
        self.assertEqual(failures, 0)
        self.assertGreaterEqual(attempted, 10)

    def test_go_windows_observation_advice_fits_without_qualification_claim(self):
        result = lesson_suggestions(
            "Go native Windows newline observation channel",
            source_urls=[
                "https://raw.githubusercontent.com/benhoyt/goawk/"
                "5b11959fbe5fc9a74adf451f33f508c1393abab7/interp/interp_test.go"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "go-native-platform-witness")
        self.assertIn("observation channel", card["lesson"])
        self.assertIn("do not skip Windows", card["lesson"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_barrel_delete_prior_repair_is_available_without_native_head_claim(self):
        result = lesson_suggestions(
            "BarrelList del_slice clipped bounds empty deletion",
            source_urls=[
                "https://raw.githubusercontent.com/mahmoud/boltons/"
                "4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d/boltons/listutils.py"
            ],
        )
        card = result['matches'][0]
        self.assertEqual(card['id'], 'closed-issue-subcase-coverage')
        self.assertTrue(any(
            item['url'].endswith('/boltons/pull/549')
            and 'not independently qualified here' in item['note']
            for item in card['evidence']
        ))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result['oversized_matches_omitted'], 0)

    def test_packed_state_allocation_advice_keeps_maintainer_evidence_attributed(self):
        result = lesson_suggestions(
            "packed recurrent final state allocation sequence grid",
            source_urls=[
                "https://raw.githubusercontent.com/fla-org/flash-linear-attention/"
                "29f4364a918a0a7dd27635d7b8d806b75204d25d/"
                "fla/ops/generalized_delta_rule/iplr/fused_recurrent.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "packed-sequence-state-allocation")
        self.assertIn("N=len(cu_seqlens)-1", card["lesson"])
        self.assertIn("empty middle sequence", card["lesson"])
        self.assertIn("not a universal allocation rule", card["avoid_when"])
        self.assertTrue(any(
            "not our own GB200 run" in item["note"]
            and "one repair lineage" in item["note"]
            for item in card["evidence"]
        ))
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)

    def test_first_group_counter_advice_keeps_shared_consumer_scope(self):
        result = lesson_suggestions(
            "PruneOptimizer num_steps parameter group counter schedule",
            source_urls=[
                "https://raw.githubusercontent.com/pytorch/ao/"
                "b4dcda49cb54ed9bf14de14df61bac684ca7a787/"
                "torchao/prototype/pat/optim/pruneopt.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "first-group-global-counter")
        self.assertIn("shared num_steps", card["lesson"])
        self.assertIn("observable wrong consumer result", card["lesson"])
        self.assertIn("documented per-group", card["avoid_when"])
        self.assertEqual(card["status"], "counterexample")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_checkpoint_stats_advice_covers_lazy_routes_and_cache_identity(self):
        result = lesson_suggestions(
            "checkpoint image_mean image_std normalization disaggregated encoder"
        )
        card = next(
            c for c in result["matches"]
            if c["id"] == "checkpoint-statistics-through-all-entrypoints"
        )
        self.assertIn("audio-first lazy initialization", card["lesson"])
        self.assertIn("checkpoint A/B/A", card["lesson"])
        self.assertIn("three-argument hooks", card["lesson"])
        self.assertIn("not official CI qualification", card["avoid_when"])
        self.assertIn("list-versus-tuple", card["avoid_when"])
        self.assertIn("not an independently reproduced", card["evidence"][0]["note"])
        self.assertTrue(any(
            "Retrospective source-export mutations" in item["note"]
            and "not prospective selector benefit" in item["note"]
            for item in card["evidence"]
        ))
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)

    def test_issue_status_advice_reads_reporter_validation_without_own_pass_claim(self):
        result = lesson_suggestions(
            "open closed issue subcase reporter-confirmed repair latest discussion"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "closed-issue-subcase-coverage")
        self.assertIn("latest discussion", card["lesson"])
        self.assertIn("original tied-weight reproducer", card["lesson"])
        self.assertIn("not our independent native qualification", card["avoid_when"])
        self.assertTrue(any(
            item["url"].endswith("/Megatron-LM/issues/8179")
            and "not our execution or a merge verdict" in item["note"]
            for item in card["evidence"]
        ))
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)

    def test_inherited_imports_do_not_imply_uv_dependency_reuse(self):
        result = lesson_suggestions("uv --system-site-packages inherited base distributions")
        card = next(c for c in result["matches"] if c["id"] == "separate-dependency-transport-from-native-tests")
        self.assertIn("uv list/install ignore them", card["lesson"])
        self.assertIn("where upstream requires uv", card["lesson"])
        self.assertTrue(any("#uv-venv--system-site-packages" in e["url"] for e in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)

    def test_exact_go_workspace_advice_preserves_resolution_boundary(self):
        result = lesson_suggestions("Go proxy release Git go.work exact dependency exports")
        card = next(
            c for c in result["matches"]
            if c["id"] == "separate-dependency-transport-from-native-tests"
        )
        self.assertIn("go.mod/go.sum unchanged", card["lesson"])
        self.assertIn("resolved module directories", card["lesson"])
        self.assertIn("not module-ZIP hashes or original single-module resolution", card["lesson"])
        self.assertIn("permission, policy or authentication denials", card["avoid_when"])
        self.assertTrue(any(e["url"].endswith("#workspaces") for e in card["evidence"]))
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
        self.assertIn("adapter-specific", card["lesson"])
        self.assertIn("maintainer-preferred regression", card["lesson"])
        self.assertIn("without another cancellation thread", card["lesson"])
        self.assertIn("Merged as 633965bad02a857574b3dbad03d1ef9f35e9caa4", card["evidence"][2]["note"])
        self.assertIn("not proof that next-evidence selection", card["avoid_when"])
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

    def test_int8_advice_keeps_ideal_bound_failure_separate_from_diagnostic(self):
        result = lesson_suggestions(
            "online INT8 scale division rounding nearest-grid precision",
            source_urls=[
                "https://raw.githubusercontent.com/vllm-project/vllm/"
                "dde9aca41cd3ccceb1ffa902933b6678a09c83ce/"
                "vllm/model_executor/layers/quantization/online/int8.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "precision-reference-contract")
        self.assertTrue(result["source_path_match"])
        self.assertIn("Preserve a failed ideal-bound check", card["lesson"])
        self.assertIn("agreement is diagnostic", card["lesson"])
        self.assertTrue(any(
            "not an accepted half-grid contract" in item["note"]
            for item in card["evidence"]
        ))
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

    def test_reload_scale_advice_distinguishes_restore_and_derived_tensors(self):
        result = lesson_suggestions(
            "NVFP4 weight reload kernel config block scale storage identity",
            source_urls=[
                "https://raw.githubusercontent.com/vllm-project/vllm/"
                "a608b6e6e05f4b309f77981f010e93c2caa1c677/"
                "vllm/model_executor/layers/quantization/online/nvfp4.py"
            ],
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "backend-state-mutation-contract")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("final owner restore step", card["lesson"])
        self.assertIn("omitted-restore control", card["lesson"])
        self.assertIn("derived reciprocals", card["lesson"])
        self.assertIn("complete loader", card["avoid_when"])
        self.assertIn("not a supported reload failure", card["avoid_when"])
        self.assertTrue(
            any("layerwise.py#L395-L446" in e["url"] for e in card["evidence"])
        )
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

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

    def test_separate_go_binary_advice_keeps_native_execution_boundary(self):
        result = lesson_suggestions("Go cross-built Windows binary test2json framing native execution")
        card = result["matches"][0]
        self.assertEqual(card["id"], "go-native-platform-witness")
        self.assertIn("-test.v=test2json", card["lesson"])
        self.assertIn("Verify both executables", card["lesson"])
        self.assertIn("parent/subtest identities", card["lesson"])
        self.assertIn("application-control denial is unexecuted", card["avoid_when"])
        self.assertTrue(any(e["url"] == "https://pkg.go.dev/cmd/test2json" for e in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)

    def test_pytest_collection_advice_keeps_missing_cases_distinct_from_failures(self):
        result = lesson_suggestions(
            "pytest python_files test_dataclasses directory collection",
            source_urls=[
                "https://raw.githubusercontent.com/alecthomas/voluptuous/"
                "44593ce7c330faf9418252c4b5448f4736144a7f/pyproject.toml"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "pytest-collection-before-suite-claims")
        self.assertIn("actual collected case identities", card["lesson"])
        self.assertIn("missing case is not a failed assertion", card["avoid_when"])
        self.assertIn("Existing PR #555", card["lesson"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
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

    def test_pytest_optional_return_advice_is_source_scoped_and_preserves_reports(self):
        for path in ("tests/test_core.py", "tests/test_fanout.py"):
            with self.subTest(path=path):
                result = lesson_suggestions(
                    "pytest rsync optional capability passed assertions",
                    source_urls=[
                        "https://raw.githubusercontent.com/grantjenks/python-diskcache/"
                        "ebfa37cd99d7ef716ec452ad8af4b4276a8e2233/" + path
                    ],
                )
                card = result["matches"][0]
                self.assertEqual(card["id"], "pytest-collection-before-suite-claims")
                self.assertIn("return normally", card["lesson"])
                self.assertIn("reported passed, not skipped", card["lesson"])
                self.assertIn("retain raw report counters", card["lesson"])
                self.assertIn("conditional source mechanism", card["avoid_when"])
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertNotIn("qualified", result)


    def test_retrieval_control_advice_keeps_pre_cap_and_efficacy_boundaries(self):
        result = lesson_suggestions(
            "RepoMap hash seed tied Counter graph reference cap",
            source_urls=[
                "https://raw.githubusercontent.com/eyuansu62/agent-retrieval-bench/"
                "07014c986f3deadb1548c62b32c0ffbe6a81465d/"
                "src/agent_retrieval_bench/repomap_eval.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "validate-evaluation-metric-invariants")
        self.assertIn("before a graph/reference cap", card["lesson"])
        self.assertIn("per-case outputs", card["lesson"])
        self.assertTrue(any(
            row["url"] == "https://github.com/eyuansu62/agent-retrieval-bench/pull/3"
            and "not improved retrieval accuracy" in row["note"]
            for row in card["evidence"]
        ))
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_budgeted_reader_advice_preserves_hidden_suffix_and_null_controls(self):
        result = lesson_suggestions(
            "budgeted read token prefix hidden suffix scoring",
            source_urls=[
                "https://raw.githubusercontent.com/eyuansu62/agent-retrieval-bench/"
                "07014c986f3deadb1548c62b32c0ffbe6a81465d/"
                "src/agent_retrieval_bench/closed_tool_eval.py"
            ],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "validate-evaluation-metric-invariants")
        self.assertTrue(result["source_path_match"])
        self.assertIn("all permitted observations constant", card["lesson"])
        self.assertIn("visible-suffix positive control", card["lesson"])
        self.assertTrue(any(
            row["url"] == "https://github.com/eyuansu62/agent-retrieval-bench/pull/4"
            and "no measured accuracy" in row["note"]
            for row in card["evidence"]
        ))
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
