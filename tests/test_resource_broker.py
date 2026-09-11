#!/usr/bin/env python3
"""Tests for the non-launching shared qualification resource broker."""

from __future__ import annotations

import copy
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment import (  # noqa: E402
    closure_template,
    request_template,
)
from resource_broker import ResourceBroker, validate_inventory  # noqa: E402


NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)


def environment_request(candidate: str = "candidate-a") -> dict:
    value = request_template()
    value["candidate_id"] = candidate
    value["platform"]["gpu_visible"] = True
    value["platform"]["required_cpu_features"] = ["AVX2"]
    value["candidate_source"] = {
        "tree_sha": ("a" if candidate == "candidate-a" else "b") * 40,
        "module_sha256": ("c" if candidate == "candidate-a" else "d") * 64,
    }
    return value


def environment_closure() -> dict:
    request = environment_request()
    value = closure_template()
    value["closure_id"] = "sm120-cpu-base"
    value["materialized"] = True
    value["platform"] = {
        "os": "linux",
        "architecture": "x86_64",
        "available_cpu_features": ["AVX2", "AVX512F"],
        "gpu_visible": True,
    }
    for field in (
        "workflow_sha256",
        "test_contract_sha256",
        "image_digest",
        "dependency_lock_sha256",
        "toolchain_lock_sha256",
    ):
        value["execution"][field] = request["execution"][field]
    value["source_binding"] = request["candidate_source"]
    return value


def inventory(count: int = 4) -> dict:
    return {
        "schema_version": "resource-broker-inventory-v1",
        "inventory_id": "test-pool",
        "observed_at": "2026-09-11T07:00:00Z",
        "hosts": [
            {
                "host_id": "sm120-a",
                "worker_id": "worker-sm120-a",
                "state": "AVAILABLE",
                "architecture": "sm120",
                "capabilities": ["CUDA", "P2P"],
                "gpus": [
                    {
                        "uuid": f"GPU-{index}",
                        "memory_gib": 32,
                        "state": "FREE",
                    }
                    for index in range(count)
                ],
                "environment_closures": [environment_closure()],
            }
        ],
    }


def job(
    job_id: str,
    *,
    priority: int = 100,
    gpu_count: int = 1,
    ready: bool = True,
    exclusive: bool = False,
    candidate: str = "candidate-a",
) -> dict:
    return {
        "schema_version": "resource-broker-job-v1",
        "job_id": job_id,
        "origin": {
            "thread_id": f"thread-{job_id}",
            "lane_id": "vllm",
            "repository": "vllm-project/vllm",
            "candidate_id": candidate,
        },
        "priority_score": priority,
        "dispatch_gate": {
            "state": "READY" if ready else "BLOCKED",
            "identity_sha256": "e" * 64 if ready else None,
        },
        "resource": {
            "gpu_count": gpu_count,
            "min_memory_gib": 24,
            "architectures": ["sm120"],
            "required_capabilities": ["CUDA"],
            "exclusive_host": exclusive,
        },
        "environment_request": environment_request(candidate),
        "budget": {"max_wall_seconds": 600, "max_gpu_seconds": 2400},
        "callback": {"thread_id": f"thread-{job_id}"},
    }


@pytest.fixture
def broker():
    with tempfile.TemporaryDirectory() as temporary:
        value = ResourceBroker(Path(temporary) / "broker.sqlite")
        try:
            yield value
        finally:
            value.close()


def test_gang_allocations_are_atomic_and_disjoint(broker: ResourceBroker) -> None:
    broker.submit(job("first", gpu_count=2), now=NOW)
    broker.submit(job("second", gpu_count=2), now=NOW + timedelta(seconds=1))
    first = broker.acquire(inventory(), now=NOW)
    second = broker.acquire(inventory(), now=NOW)
    assert first and second
    assert first["gpu_uuids"] == ["GPU-0", "GPU-1"]
    assert second["gpu_uuids"] == ["GPU-2", "GPU-3"]
    assert not set(first["gpu_uuids"]) & set(second["gpu_uuids"])
    assert broker.acquire(inventory(), now=NOW) is None


def test_small_job_backfills_when_high_priority_gang_cannot_fit(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("occupy", priority=1000, gpu_count=2), now=NOW)
    assert broker.acquire(inventory(), now=NOW)["job_id"] == "occupy"
    broker.submit(job("large", priority=900, gpu_count=4), now=NOW)
    broker.submit(job("small", priority=100, gpu_count=1), now=NOW)
    lease = broker.acquire(inventory(), now=NOW)
    assert lease and lease["job_id"] == "small"
    assert broker.job("large")["state"] == "QUEUED"


def test_stale_lease_stays_reserved_until_terminal_reconciliation(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("old", gpu_count=4), now=NOW)
    old = broker.acquire(inventory(), ttl_seconds=10, now=NOW)
    broker.submit(job("new", gpu_count=4), now=NOW + timedelta(seconds=1))
    snapshot = broker.snapshot(now=NOW + timedelta(seconds=11))
    assert snapshot["leases"][0]["state"] == "STALE"
    assert broker.job("old")["state"] == "STALE_REQUIRES_RECONCILIATION"
    assert broker.acquire(inventory(), now=NOW + timedelta(seconds=11)) is None
    terminal = broker.complete(
        old["lease_id"],
        "ABANDONED",
        {"path": "worker/reconcile.json", "sha256": "f" * 64},
        now=NOW + timedelta(seconds=12),
    )
    assert terminal["callback"] == {"thread_id": "thread-old"}
    assert (
        broker.acquire(inventory(), now=NOW + timedelta(seconds=12))["job_id"] == "new"
    )


def test_blocked_authorization_never_receives_a_resource(
    broker: ResourceBroker,
) -> None:
    submitted = broker.submit(job("blocked", ready=False), now=NOW)
    assert submitted["state"] == "BLOCKED_AUTHORIZATION"
    assert broker.acquire(inventory(), now=NOW) is None


def test_environment_mismatch_does_not_hold_gpus(
    broker: ResourceBroker,
) -> None:
    request = job("wrong-environment")
    request["environment_request"]["execution"]["toolchain_lock_sha256"] = "9" * 64
    broker.submit(request, now=NOW)
    assert broker.acquire(inventory(), now=NOW) is None
    assert broker.snapshot(now=NOW)["allocations"] == []


def test_source_rebind_reuses_dependency_closure(broker: ResourceBroker) -> None:
    broker.submit(job("rebind", candidate="candidate-b"), now=NOW)
    lease = broker.acquire(inventory(), now=NOW)
    assert lease["environment"]["decision"] == ("REUSE_DEPENDENCIES_REBIND_SOURCE")


def test_full_closure_is_preferred_over_source_rebind_across_hosts(
    broker: ResourceBroker,
) -> None:
    pool = inventory(1)
    full_host = copy.deepcopy(pool["hosts"][0])
    full_host["host_id"] = "sm120-b"
    full_host["worker_id"] = "worker-sm120-b"
    full_host["gpus"][0]["uuid"] = "GPU-full"
    full_host["environment_closures"][0]["closure_id"] = "candidate-b-full"
    full_host["environment_closures"][0]["source_binding"] = environment_request(
        "candidate-b"
    )["candidate_source"]
    pool["hosts"].append(full_host)
    broker.submit(job("prefer-full", candidate="candidate-b"), now=NOW)
    lease = broker.acquire(pool, now=NOW)
    assert lease["host_id"] == "sm120-b"
    assert lease["environment"]["decision"] == "REUSE_FULL_CLOSURE"


def test_plan_explains_resource_and_environment_blockers(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("ready"), now=NOW)
    mismatch = job("prepare", candidate="candidate-b")
    mismatch["environment_request"]["execution"]["toolchain_lock_sha256"] = "9" * 64
    broker.submit(mismatch, now=NOW)
    impossible = job("impossible", gpu_count=4)
    impossible["resource"]["architectures"] = ["sm80"]
    broker.submit(impossible, now=NOW)
    broker.submit(job("blocked", ready=False), now=NOW)

    planned = {item["job_id"]: item for item in broker.plan(inventory(2))["jobs"]}
    assert planned["ready"]["plan_state"] == "READY_FOR_RESOURCE_RESERVATION"
    assert planned["prepare"]["plan_state"] == "ENVIRONMENT_PREPARATION_REQUIRED"
    assert planned["impossible"]["plan_state"] == "NO_COMPATIBLE_RESOURCE"
    assert planned["blocked"]["plan_state"] == "BLOCKED_AUTHORIZATION"

    broker.acquire(inventory(2), now=NOW)
    planned = {item["job_id"]: item for item in broker.plan(inventory(2))["jobs"]}
    assert planned["ready"]["broker_state"] == "LEASED"


def test_plan_reports_waiting_when_compatible_gpus_are_occupied(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("occupy", gpu_count=2), now=NOW)
    broker.acquire(inventory(2), now=NOW)
    broker.submit(job("waiting", gpu_count=1), now=NOW)
    planned = {item["job_id"]: item for item in broker.plan(inventory(2))["jobs"]}
    assert planned["waiting"]["plan_state"] == "WAITING_FOR_GPU"


def test_exclusive_host_blocks_other_jobs(broker: ResourceBroker) -> None:
    broker.submit(job("exclusive", gpu_count=1, exclusive=True), now=NOW)
    broker.submit(job("other", gpu_count=1), now=NOW + timedelta(seconds=1))
    assert broker.acquire(inventory(), now=NOW)["job_id"] == "exclusive"
    assert broker.acquire(inventory(), now=NOW) is None


def test_completion_releases_gpu_and_preserves_callback(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("done"), now=NOW)
    lease = broker.acquire(inventory(), now=NOW)
    terminal = broker.complete(
        lease["lease_id"],
        "SUCCEEDED",
        {"path": "results/done.json", "sha256": "1" * 64},
        now=NOW + timedelta(seconds=5),
    )
    assert terminal["callback"]["thread_id"] == "thread-done"
    assert broker.job("done")["state"] == "SUCCEEDED"
    assert broker.snapshot(now=NOW)["allocations"] == []


def test_completion_rejects_non_digest_result_identity(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("bad-result"), now=NOW)
    lease = broker.acquire(inventory(), now=NOW)
    with pytest.raises(ValueError, match="full digest"):
        broker.complete(
            lease["lease_id"],
            "FAILED",
            {"path": "results/failure.json", "sha256": "z" * 64},
            now=NOW + timedelta(seconds=1),
        )


def test_duplicate_gpu_or_callback_drift_is_rejected(
    broker: ResourceBroker,
) -> None:
    bad_inventory = inventory()
    bad_inventory["hosts"].append(copy.deepcopy(bad_inventory["hosts"][0]))
    bad_inventory["hosts"][1]["host_id"] = "sm120-b"
    with pytest.raises(ValueError, match="GPU UUID"):
        validate_inventory(bad_inventory)
    bad_job = job("callback")
    bad_job["callback"]["thread_id"] = "some-other-thread"
    with pytest.raises(ValueError, match="originating task"):
        broker.submit(bad_job, now=NOW)

    bad_inventory = inventory()
    extension = bad_inventory["hosts"][0]["environment_closures"][0]["execution"][
        "native_extension"
    ]
    extension["required"] = False
    extension["artifact_sha256"] = "a" * 64
    extension["source_tree_sha"] = "b" * 40
    with pytest.raises(ValueError, match="unused extension identity"):
        validate_inventory(bad_inventory)


def test_two_brokers_cannot_double_allocate_one_gpu() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "broker.sqlite"
        first = ResourceBroker(database)
        first.submit(job("race"), now=NOW)
        first.close()
        barrier = threading.Barrier(2)
        results: list[dict | None] = []

        def acquire() -> None:
            local = ResourceBroker(database)
            try:
                barrier.wait()
                results.append(local.acquire(inventory(1), now=NOW))
            finally:
                local.close()

        threads = [threading.Thread(target=acquire) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(result is not None for result in results) == 1


def test_heartbeat_cannot_revive_an_expired_lease(
    broker: ResourceBroker,
) -> None:
    broker.submit(job("expired"), now=NOW)
    lease = broker.acquire(inventory(), ttl_seconds=5, now=NOW)
    with pytest.raises(ValueError, match="active lease"):
        broker.heartbeat(
            lease["lease_id"], ttl_seconds=10, now=NOW + timedelta(seconds=6)
        )
