#!/usr/bin/env python3
"""Focused tests for qualification environment reuse routing."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment import (  # noqa: E402
    closure_template,
    evaluate,
    request_template,
)


def identities() -> tuple[str, str, str, str]:
    return "1" * 64, "2" * 64, "3" * 64, "4" * 64


def matched() -> tuple[dict, dict]:
    workflow, test_contract, dependency, toolchain = identities()
    tree = "a" * 40
    module = "b" * 64
    closure = closure_template()
    closure.update({"closure_id": "cached-cpu", "materialized": True})
    closure["platform"]["available_cpu_features"] = ["avx2", "avx512f"]
    closure["execution"].update(
        {
            "workflow_sha256": workflow,
            "test_contract_sha256": test_contract,
            "image_digest": "sha256:" + "c" * 64,
            "dependency_lock_sha256": dependency,
            "toolchain_lock_sha256": toolchain,
        }
    )
    closure["source_binding"] = {"tree_sha": tree, "module_sha256": module}

    request = request_template()
    request["candidate_id"] = "candidate"
    request["platform"]["required_cpu_features"] = ["avx2"]
    request["execution"].update(
        {
            "workflow_sha256": workflow,
            "test_contract_sha256": test_contract,
            "image_digest": "sha256:" + "c" * 64,
            "dependency_lock_sha256": dependency,
            "toolchain_lock_sha256": toolchain,
        }
    )
    request["candidate_source"] = {"tree_sha": tree, "module_sha256": module}
    return closure, request


def test_full_pure_python_closure_is_reused() -> None:
    closure, request = matched()
    result = evaluate(closure, request)
    assert result["decision"] == "REUSE_FULL_CLOSURE"
    assert result["dependency_closure_reusable"] is True
    assert result["native_extension_reusable"] is True
    assert result["import_binding_reusable"] is True


def test_matching_dependencies_can_rebind_python_source() -> None:
    closure, request = matched()
    request["candidate_source"]["tree_sha"] = "d" * 40
    request["candidate_source"]["module_sha256"] = "e" * 64
    result = evaluate(closure, request)
    assert result["decision"] == "REUSE_DEPENDENCIES_REBIND_SOURCE"
    assert result["dependency_closure_reusable"] is True
    assert result["import_binding_reusable"] is False


def test_source_bound_extension_reuse_and_rebuild_are_distinct() -> None:
    closure, request = matched()
    tree = request["candidate_source"]["tree_sha"]
    closure["execution"]["native_extension"] = {
        "required": True,
        "artifact_sha256": "f" * 64,
        "source_tree_sha": tree,
    }
    request["execution"]["native_extension_required"] = True
    assert evaluate(closure, request)["decision"] == "REUSE_FULL_CLOSURE"

    request["candidate_source"]["tree_sha"] = "9" * 40
    request["candidate_source"]["module_sha256"] = "8" * 64
    request["allow_native_rebuild"] = True
    result = evaluate(closure, request)
    assert result["decision"] == "REUSE_DEPENDENCIES_REBUILD_EXTENSION"
    assert result["native_extension_reusable"] is False

    request["allow_native_rebuild"] = False
    result = evaluate(closure, request)
    assert result["decision"] == "MATERIALIZE_NEW_CLOSURE"
    assert result["next_action"] == "USE_SOURCE_MATCHED_PREBUILT_CLOSURE"


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        ("image", "execution.image_digest"),
        ("dependency", "execution.dependency_lock_sha256"),
        ("workflow", "execution.workflow_sha256"),
        ("isa", "platform.required_cpu_features"),
        ("gpu", "platform.gpu_visible"),
        ("unmaterialized", "materialized"),
    ],
)
def test_hard_environment_drift_requires_new_closure(mutation: str, field: str) -> None:
    closure, request = matched()
    if mutation == "image":
        request["execution"]["image_digest"] = "sha256:" + "7" * 64
    elif mutation == "dependency":
        request["execution"]["dependency_lock_sha256"] = "7" * 64
    elif mutation == "workflow":
        request["execution"]["workflow_sha256"] = "7" * 64
    elif mutation == "isa":
        request["platform"]["required_cpu_features"] = ["amx_bf16"]
    elif mutation == "gpu":
        request["platform"]["gpu_visible"] = True
    else:
        closure["materialized"] = False
    result = evaluate(closure, request)
    assert result["decision"] == "MATERIALIZE_NEW_CLOSURE"
    assert result["dependency_closure_reusable"] is False
    assert any(item["field"] == field for item in result["hard_mismatches"])


def test_native_extension_identity_is_fail_closed() -> None:
    closure, request = matched()
    closure["execution"]["native_extension"]["required"] = True
    with pytest.raises(ValueError, match="needs artifact and source identities"):
        evaluate(closure, request)

    closure, request = matched()
    closure["execution"]["native_extension"]["artifact_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="cannot claim extension identities"):
        evaluate(closure, request)


def test_unknown_fields_and_malformed_hashes_fail_closed() -> None:
    closure, request = matched()
    request["hidden"] = True
    with pytest.raises(ValueError, match="additional property"):
        evaluate(closure, request)

    closure, request = matched()
    request["execution"]["workflow_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="does not match"):
        evaluate(closure, request)

    closure, request = matched()
    duplicate = copy.deepcopy(closure)
    duplicate["platform"]["available_cpu_features"] = ["avx2", "avx2"]
    with pytest.raises(ValueError, match="unique"):
        evaluate(duplicate, request)
