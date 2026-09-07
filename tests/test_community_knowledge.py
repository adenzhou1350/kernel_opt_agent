#!/usr/bin/env python3
"""Exercise immutable community evidence capture and event provenance."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import (
    ARTIFACT_SPECS,
    atomic_json,
    attach_graph,
    build_graph,
    build_match_receipt,
    build_review_queue,
    capture_pr,
    discovery_classifications,
    read_object,
    refresh_tracked_events,
    sha256_file,
    sync_repository,
    validate_corpus,
    validate_event,
    validate_graph,
    validate_match_receipt,
    validate_review_queue,
)
from schema_utils import validate_instance


SHA_A = "a" * 40
SHA_B = "b" * 40


class FakeGitHubClient:
    authenticated = False

    def __init__(self) -> None:
        self.review_body = "The benchmark needs an end-to-end control."
        self.pull_state = "closed"
        self.pull_merged = True
        self.pull_updated_at = "2026-01-03T00:00:00Z"
        self.repo_stars = 10
        self.review_submitted_at = "2026-01-02T00:00:00Z"

    def pull(self) -> dict:
        return {
            "title": "Fuse dequantization with logits GEMM",
            "body": "Removes a materialized dense weight and reports 2x.",
            "state": self.pull_state,
            "draft": False,
            "merged": self.pull_merged,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": self.pull_updated_at,
            "closed_at": "2026-01-03T00:00:00Z",
            "merged_at": "2026-01-03T00:00:00Z",
            "base": {"sha": SHA_A, "repo": {"stargazers_count": self.repo_stars}},
            "head": {"sha": SHA_B},
            "user": {"login": "contributor"},
            "labels": [{"name": "performance"}],
        }

    def json_pages(self, path: str, accept: str) -> tuple[list[object], list[str]]:
        del accept
        url = f"https://api.github.test{path}"
        if path.endswith("/pulls/7"):
            return [self.pull()], [url]
        if "/files?" in path:
            return [[{"filename": "kernel.py", "status": "modified"}][0]], [url]
        if "/commits?" in path:
            return [{"sha": SHA_B}], [url]
        if "/issues/7/comments" in path:
            return [{"body": "Reproduced on the stated GPU."}], [url]
        if path.endswith("/pulls/7/reviews?per_page=100"):
            return [
                {
                    "state": "APPROVED",
                    "body": self.review_body,
                    "submitted_at": self.review_submitted_at,
                }
            ], [url]
        if path.endswith("/pulls/7/comments?per_page=100"):
            return [{"path": "kernel.py", "body": "Preserve the fallback."}], [url]
        if "/timeline?" in path:
            return [
                {
                    "event": "merged",
                    "commit_id": SHA_B,
                    "repo": {
                        "full_name": "example/project",
                        "html_url": "https://github.test/example/project",
                        "forks_url": "https://api.github.test/example/project/forks",
                        "forks_count": self.repo_stars,
                    },
                }
            ], [url]
        raise AssertionError(path)

    def bytes(self, url: str, accept: str) -> tuple[bytes, list[str]]:
        del accept
        return b"diff --git a/kernel.py b/kernel.py\n", [url]

    def search_pull_requests(
        self, repository: str, since: str, until: str, maximum: int = 1000
    ) -> tuple[list[dict], list[str], int, bool]:
        del repository, since, until, maximum
        return (
            [
                {
                    "number": 7,
                    "title": "Fix kernel performance regression",
                    "body": "Restore the faster fused path.",
                    "created_at": "2025-12-31T00:00:00Z",
                    "updated_at": "2026-01-03T00:00:00Z",
                    "labels": [{"name": "performance"}],
                },
                {
                    "number": 8,
                    "title": "Update documentation",
                    "body": "Template: check performance and regression; no measurements.",
                    "created_at": "2026-01-02T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "labels": [],
                },
            ],
            ["https://api.github.test/search/issues?page=1"],
            2,
            False,
        )


def evidence_ref(manifest: dict, kind: str, locator: str) -> dict:
    artifact = next(item for item in manifest["artifacts"] if item["kind"] == kind)
    return {"artifact_kind": kind, "sha256": artifact["sha256"], "locator": locator}


def event_for(manifest_path: Path) -> dict:
    manifest = read_object(manifest_path)
    pull_ref = evidence_ref(manifest, "PULL_REQUEST", "body")
    diff_ref = evidence_ref(manifest, "DIFF", "kernel.py")
    return {
        "schema_version": "community-optimization-event-v1",
        "event_id": "example.fused-dequant-logits",
        "review_status": "REVIEWED",
        "claim_boundary": "DISCOVERY_PRIOR_ONLY",
        "source_snapshot": {
            "repository": manifest["source"]["repository"],
            "pr_number": manifest["source"]["number"],
            "snapshot_id": manifest["snapshot_id"],
            "manifest_sha256": sha256_file(manifest_path),
        },
        "lifecycle": {
            "outcome": "MERGED",
            "merged_at": "2026-01-03T00:00:00Z",
            "followup_required": False,
        },
        "summary": "Fuse weight dequantization into the logits matrix multiplication.",
        "problem": {
            "symptoms": ["Every decode step materializes the full dense weight."],
            "baseline_path": ["dequantize full table", "run dense linear"],
            "bottleneck_classes": ["memory-bandwidth", "materialization"],
            "mandatory_work": ["read compressed weight", "produce logits"],
        },
        "mechanism": {
            "rewrite_families": ["materialization-removal", "operator-fusion"],
            "transformations": ["Fuse dequantization with the consuming GEMM."],
            "removed_work": ["dense intermediate write and reread"],
            "added_work": ["inline scale application"],
            "expected_bottleneck_shifts": [
                "The fused path approaches the compressed-weight bandwidth floor."
            ],
        },
        "applicability": {
            "operators": ["lm_head", "logits projection"],
            "subsystems": ["quantized inference"],
            "dtypes": ["int8", "float16"],
            "hardware": ["NVIDIA GPU"],
            "workload_conditions": ["single-token decode"],
            "required_capabilities": ["supported fused WNA16 kernel"],
            "hard_requirements": {
                "compute_capabilities": [],
                "minimum_parallel_width": 1,
                "required_context_terms": [],
            },
        },
        "implementation": {
            "files": ["kernel.py"],
            "symbols": ["apply"],
            "recipe": ["Route tied logits through the existing fused linear kernel."],
        },
        "validation": {
            "correctness": ["Compare fused logits with the dequantized reference."],
            "measurements": [
                {
                    "metric": "latency",
                    "baseline": 2.0,
                    "candidate": 1.0,
                    "unit": "ms",
                    "direction": "LOWER_IS_BETTER",
                    "reported_speedup": 2.0,
                    "workload": "M=1 logits projection",
                    "hardware": "source-reported NVIDIA GPU",
                    "evidence_ref": pull_ref,
                }
            ],
            "limitations": ["Source-reported benchmark is not target-hardware proof."],
        },
        "relations": [],
        "claims": [
            {
                "claim_id": "removes-materialization",
                "statement": "The patch removes the dense intermediate from the primary path.",
                "grade": "REVIEW_INFERRED",
                "evidence_refs": [diff_ref],
            }
        ],
    }


def main() -> None:
    assert len(ARTIFACT_SPECS) == 8
    assert not discovery_classifications(
        {"title": "Add autoregressive model", "body": "", "labels": []}
    )
    with tempfile.TemporaryDirectory() as temporary:
        corpus = Path(temporary) / "corpus"
        client = FakeGitHubClient()
        first = capture_pr("example/project", 7, corpus, client, ROOT)
        client.repo_stars += 1
        second = capture_pr("example/project", 7, corpus, client, ROOT)
        assert first["snapshot_id"] == second["snapshot_id"]
        assert second["corpus_snapshot_count"] == 1
        assert validate_corpus(corpus, ROOT) == {"status": "PASS", "snapshot_count": 1}

        client.review_body = "A later review records a regression risk."
        third = capture_pr("example/project", 7, corpus, client, ROOT)
        assert third["snapshot_id"] != first["snapshot_id"]
        assert third["corpus_snapshot_count"] == 2
        assert validate_corpus(corpus, ROOT)["snapshot_count"] == 2

        sync_receipt = sync_repository(
            "example/project",
            "2026-01-01T00:00:00Z",
            "2026-01-04T00:00:00Z",
            corpus,
            Path(temporary) / "sync.json",
            client,
            max_captures=1,
            root=ROOT,
        )
        assert sync_receipt["candidate_count"] == 1
        assert sync_receipt["candidates"][0]["decision"] == "CAPTURED"
        assert sync_receipt["window_basis"] == "UPDATED_AT"
        assert sync_receipt["heldout_eligibility_basis"] == "EARLIEST_PUBLIC_AT"
        assert sync_receipt["candidates"][0]["earliest_public_at"] == (
            "2025-12-31T00:00:00Z"
        )
        assert (
            sync_receipt["candidates"][0]["earliest_public_at"]
            < sync_receipt["window"]["since"]
        )
        sync_schema = read_object(ROOT / "schemas" / "community_sync_receipt.schema.json")
        missing_first_public = json.loads(json.dumps(sync_receipt))
        missing_first_public["candidates"][0].pop("earliest_public_at")
        assert any(
            "earliest_public_at" in error
            for error in validate_instance(missing_first_public, sync_schema)
        )
        legacy_sync = json.loads(json.dumps(sync_receipt))
        legacy_sync["schema_version"] = "community-sync-receipt-v1"
        legacy_sync.pop("window_basis")
        legacy_sync.pop("heldout_eligibility_basis")
        for candidate_row in legacy_sync["candidates"]:
            candidate_row.pop("created_at")
            candidate_row.pop("earliest_public_at")
        assert validate_instance(legacy_sync, sync_schema) == []
        assert "REGRESSION" in sync_receipt["candidates"][0]["classifications"]
        assert sync_receipt["next_since"] == "2026-01-04T00:00:00Z"
        assert validate_corpus(corpus, ROOT)["snapshot_count"] == 2

        manifest_path = Path(third["manifest"])
        unreviewed_queue_path = Path(temporary) / "unreviewed-queue.json"
        unreviewed_queue = build_review_queue(corpus, max_items=1, root=ROOT)
        atomic_json(unreviewed_queue_path, unreviewed_queue)
        assert (
            validate_review_queue(unreviewed_queue_path, corpus, ROOT)[
                "unreviewed_count"
            ]
            == 1
        )
        assert unreviewed_queue["items"][0]["state"] == "UNREVIEWED"
        assert unreviewed_queue["items"][0]["selection"] == "SELECTED"
        tampered_queue = json.loads(json.dumps(unreviewed_queue))
        tampered_queue["items"][0]["priority_score"] += 1
        tampered_queue_path = Path(temporary) / "tampered-review-queue.json"
        atomic_json(tampered_queue_path, tampered_queue)
        try:
            validate_review_queue(tampered_queue_path, corpus, ROOT)
        except ValueError as error:
            assert "stale or was edited" in str(error)
        else:
            raise AssertionError("edited community review queue was accepted")

        event_path = corpus / "events" / "event.json"
        event_path.parent.mkdir(parents=True)
        first_event = event_for(manifest_path)
        first_event["relations"] = [
            {
                "type": "COMPLEMENTS",
                "target": "example.layout-aware-logits",
                "rationale": "Compressed reads and a layout-aware schedule remove different costs.",
            },
            {
                "type": "REQUIRES",
                "target": "community-incremental-prefix-state-machine",
                "rationale": "Exercise method resolution across the primitive library.",
            },
        ]
        event_path.write_text(
            json.dumps(first_event, indent=2) + "\n", encoding="utf-8"
        )
        second_event = event_for(manifest_path)
        second_event["event_id"] = "example.layout-aware-logits"
        second_event["summary"] = (
            "Schedule the fused projection around its packed layout."
        )
        second_event["mechanism"]["rewrite_families"].append("data-layout")
        second_event["mechanism"]["expected_bottleneck_shifts"] = [
            "The packed layout trades address work for fewer memory transactions."
        ]
        second_event_path = corpus / "events" / "layout-event.json"
        second_event_path.write_text(
            json.dumps(second_event, indent=2) + "\n", encoding="utf-8"
        )
        result = validate_event(event_path, corpus, ROOT)
        assert result["status"] == "PASS" and result["evidence_reference_count"] == 2
        current_queue = build_review_queue(corpus, max_items=1, root=ROOT)
        assert current_queue["inventory"] == {
            "pull_request_count": 1,
            "current_count": 1,
            "unreviewed_count": 0,
            "review_required_count": 0,
            "selected_count": 0,
            "backlog_count": 0,
        }
        assert current_queue["items"] == []

        graph_path = Path(temporary) / "community_graph.json"
        graph = build_graph(
            corpus,
            ["example/project", "other/engine"],
            ROOT,
        )
        atomic_json(graph_path, graph)
        graph_result = validate_graph(graph_path, corpus, ROOT)
        assert graph_result["node_count"] == 2
        assert graph_result["composition_count"] == 1
        assert graph_result["lifecycle_review_count"] == 0
        assert graph["lifecycle_review_queue"] == []
        assert all(
            node["lifecycle_observation"]["status"] == "CURRENT"
            for node in graph["nodes"]
        )
        primitive_edge = next(
            edge
            for edge in graph["edges"]
            if edge["target"] == "community-incremental-prefix-state-machine"
        )
        assert primitive_edge["target_kind"] == "METHOD"
        assert primitive_edge["resolution"] == "PRESENT"
        assert graph_result["coverage_gap_count"] >= 1
        assert all(
            gap["claim_boundary"] == "CORPUS_COVERAGE_GAP_ONLY"
            for gap in graph["coverage_gaps"]
        )

        run = Path(temporary) / "run"
        (run / "models").mkdir(parents=True)
        for name in ("operator.json", "workload.json", "hardware.json"):
            shutil.copyfile(ROOT / "tests" / "fixtures" / name, run / name)
        atomic_json(
            run / "models" / "opportunity_map.json",
            {
                "schema_version": "opportunity-map-v1",
                "status": "READY",
                "opportunities": [
                    {
                        "opportunity_id": "remove-logits-materialization",
                        "priority_rank": 1,
                        "rewrite_families": ["materialization-removal"],
                        "hypothesis": "Remove a dense intermediate from logits projection.",
                    }
                ],
            },
        )
        attach_graph(run, graph_path, corpus, ROOT)
        receipt = build_match_receipt(run, root=ROOT)
        validate_match_receipt(receipt, run, ROOT)
        matches = receipt["recommendations"][0]["matches"]
        assert matches[0]["event_id"] == "example.fused-dequant-logits"
        assert matches[0]["transfer_status"] == "ADAPTATION_REQUIRED"
        assert matches[0]["opportunity_hits"]
        compositions = receipt["recommendations"][0]["composition_matches"]
        assert len(compositions) == 1
        assert compositions[0]["events"] == [
            "example.fused-dequant-logits",
            "example.layout-aware-logits",
        ]
        assert compositions[0]["claim_boundary"] == "UNVALIDATED_COMPOSITION_HYPOTHESIS"

        # A later review alone must make the older event review-required even
        # before the PR lifecycle changes.
        client.review_body = "The merged change was reverted after a regression."
        client.review_submitted_at = "2026-01-04T00:00:00Z"
        review_refresh = refresh_tracked_events(
            corpus,
            Path(temporary) / "review-refresh.json",
            client,
            max_captures=1,
            root=ROOT,
        )
        review_row = review_refresh["tracked_pull_requests"][0]
        assert review_refresh["captured_count"] == 1
        assert review_refresh["semantic_change_count"] == 1
        assert len(review_refresh["review_required_event_ids"]) == 2
        assert review_row["semantic_changed"]
        assert review_row["after"]["snapshot_id"] != third["snapshot_id"]
        changed_queue = build_review_queue(corpus, max_items=1, root=ROOT)
        assert changed_queue["inventory"]["review_required_count"] == 1
        assert changed_queue["items"][0]["state"] == "REVIEW_REQUIRED"
        assert changed_queue["items"][0]["event_ids"] == [
            "example.fused-dequant-logits",
            "example.layout-aware-logits",
        ]
        review_graph = build_graph(corpus, ["example/project", "other/engine"], ROOT)
        assert len(review_graph["lifecycle_review_queue"]) == 2
        assert all(
            row["event_outcome"] == "MERGED" and row["latest_outcome"] == "MERGED"
            for row in review_graph["lifecycle_review_queue"]
        )

        # A later source transition must not silently rewrite or remain usable
        # through an event extracted from the earlier immutable snapshot.
        client.pull_state = "closed"
        client.pull_merged = False
        client.pull_updated_at = "2026-01-05T00:00:00Z"
        lifecycle_refresh = refresh_tracked_events(
            corpus,
            Path(temporary) / "lifecycle-refresh.json",
            client,
            max_captures=1,
            root=ROOT,
        )
        lifecycle_row = lifecycle_refresh["tracked_pull_requests"][0]
        assert lifecycle_row["before"]["lifecycle"] == "MERGED"
        assert lifecycle_row["after"]["lifecycle"] == "CLOSED_UNMERGED"
        assert lifecycle_row["semantic_changed"]
        stale_graph = build_graph(corpus, ["example/project", "other/engine"], ROOT)
        assert len(stale_graph["lifecycle_review_queue"]) == 2
        assert all(
            row["event_outcome"] == "MERGED"
            and row["latest_outcome"] == "CLOSED_UNMERGED"
            for row in stale_graph["lifecycle_review_queue"]
        )
        atomic_json(graph_path, stale_graph)
        attach_graph(run, graph_path, corpus, ROOT)
        stale_receipt = build_match_receipt(run, root=ROOT)
        stale_recommendation = stale_receipt["recommendations"][0]
        assert stale_recommendation["matches"] == []
        assert len(stale_recommendation["screened_out"]) == 2
        assert all(
            "re-review is required" in row["blockers"][0]
            for row in stale_recommendation["screened_out"]
        )

        # Historical graphs remain cutoff-safe: the later review and lifecycle
        # transition are invisible before 2026-01-04.
        historical_graph = build_graph(
            corpus,
            ["example/project", "other/engine"],
            ROOT,
            cutoff_at="2026-01-03T23:59:59Z",
        )
        assert historical_graph["lifecycle_review_queue"] == []
        assert all(
            node["lifecycle_observation"]["status"] == "CURRENT"
            for node in historical_graph["nodes"]
        )

        blocked_event = json.loads(second_event_path.read_text(encoding="utf-8"))
        blocked_event["applicability"]["hard_requirements"][
            "minimum_parallel_width"
        ] = 2
        second_event_path.write_text(
            json.dumps(blocked_event, indent=2) + "\n", encoding="utf-8"
        )
        atomic_json(
            graph_path,
            build_graph(
                corpus,
                ["example/project", "other/engine"],
                ROOT,
                cutoff_at="2026-01-03T23:59:59Z",
            ),
        )
        attach_graph(run, graph_path, corpus, ROOT)
        gated_receipt = build_match_receipt(run, root=ROOT)
        recommendation = gated_receipt["recommendations"][0]
        assert not recommendation["composition_matches"]
        assert recommendation["screened_out"] == [
            {
                "event_id": "example.layout-aware-logits",
                "blockers": ["parallel width >= 2 is required but not explicit"],
                "claim_boundary": "APPLICABILITY_GATE",
            }
        ]

        event = json.loads(event_path.read_text(encoding="utf-8"))
        event["claims"][0]["evidence_refs"][0]["sha256"] = "0" * 64
        event_path.write_text(json.dumps(event, indent=2) + "\n", encoding="utf-8")
        try:
            validate_event(event_path, corpus, ROOT)
        except ValueError as error:
            assert "not bound" in str(error)
        else:
            raise AssertionError("tampered evidence reference was accepted")

        artifact = manifest_path.parent / "pull.diff"
        artifact.write_text("tampered\n", encoding="utf-8")
        try:
            validate_corpus(corpus, ROOT)
        except ValueError as error:
            assert "artifact" in str(error)
        else:
            raise AssertionError("tampered corpus artifact was accepted")

    print("community knowledge test: PASS")


if __name__ == "__main__":
    main()
