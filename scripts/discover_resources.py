#!/usr/bin/env python3
"""Derive a conservative material-resource set from final SASS and official evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_utils import (
    read_object,
    sha256,
    target_fields_match,
    validate_hardware_evidence,
    validate_identity,
)
from count_sass import validate_disassembly_receipt


# These are detection boundaries, not target-hardware performance facts.  A
# node is admitted only when the target manifest supplies the required official
# document role and the final binary supplies the triggering instruction class.
CLASS_RULES = {
    "branch_control": (["instruction_front_end", "warp_issue"], ["programming_model", "instruction_set"]),
    "control_noop": (["instruction_front_end", "warp_issue"], ["instruction_set"]),
    "integer_address": (["integer_address_pipe", "register_storage", "warp_issue"], ["instruction_set"]),
    "conversion": (["conversion_pipe", "register_storage", "warp_issue"], ["instruction_set"]),
    "tensor": (["tensor_compute", "tensor_issue", "register_storage"], ["instruction_set", "architecture_tuning"]),
    "simt_fp": (["simt_compute", "warp_issue", "register_storage"], ["instruction_set"]),
    "predicate_compare": (["predicate_compute", "predicate_storage", "warp_issue", "register_storage"], ["instruction_set"]),
    "move_select": (["register_storage", "warp_issue"], ["instruction_set"]),
    "special_function": (["special_function", "warp_issue", "register_storage"], ["instruction_set"]),
    "global_load": (["load_store_request", "l1_shared_boundary", "l2_boundary", "device_memory_boundary", "register_storage"], ["programming_model", "instruction_set"]),
    "global_store": (["load_store_request", "l1_shared_boundary", "l2_boundary", "device_memory_boundary"], ["programming_model", "instruction_set"]),
    "constant_load": (["constant_memory_path", "load_store_request", "register_storage"], ["programming_model", "instruction_set"]),
    "local_load": (["local_spill_path", "load_store_request", "l1_shared_boundary", "l2_boundary", "device_memory_boundary"], ["programming_model", "instruction_set"]),
    "local_store": (["local_spill_path", "load_store_request", "l1_shared_boundary", "l2_boundary", "device_memory_boundary"], ["programming_model", "instruction_set"]),
    "shared_load": (["shared_memory", "shared_bank_service", "load_store_request", "register_storage"], ["programming_model", "instruction_set"]),
    "shared_store": (["shared_memory", "shared_bank_service", "load_store_request"], ["programming_model", "instruction_set"]),
    "surface_texture": (["surface_texture_path", "l2_boundary", "device_memory_boundary", "register_storage"], ["programming_model", "instruction_set"]),
    "atomic_reduction": (["atomic_reduction_service", "load_store_request", "l2_boundary", "device_memory_boundary", "register_storage"], ["programming_model", "instruction_set"]),
    "barrier": (["synchronization", "warp_issue"], ["programming_model", "instruction_set"]),
    "memory_wait": (["scoreboard_wait", "synchronization", "warp_issue"], ["programming_model", "instruction_set"]),
    "async_copy": (["async_copy_engine", "load_store_request", "shared_memory", "l2_boundary", "device_memory_boundary"], ["instruction_set", "architecture_tuning"]),
    "system_register": (["system_register_path", "register_storage", "warp_issue"], ["instruction_set"]),
    "warp_collective": (["warp_collective", "register_storage", "warp_issue"], ["programming_model", "instruction_set"]),
}


def observed_classes(sass: dict) -> dict[str, int]:
    totals: dict[str, int] = {}
    for function in sass.get("functions", {}).values():
        for name, count in function.get("classes", {}).items():
            totals[name] = totals.get(name, 0) + int(count)
    return {name: count for name, count in sorted(totals.items()) if count > 0}


def sources_by_role(manifest: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for source in manifest.get("sources", []):
        result.setdefault(str(source.get("role")), []).append(source)
    return result


def locator_value(record: dict) -> str:
    locator = record.get("locator", {})
    return str(locator.get("value", "")) if isinstance(locator, dict) else str(locator)


def reviewed_mapping_fact(manifest: dict, instruction_class: str) -> dict | None:
    field = f"instruction_class.{instruction_class}.resource_ids"
    return next((fact for fact in manifest.get("facts", []) if fact.get("field") == field), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sass-summary", type=Path, required=True)
    parser.add_argument("--hardware-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest_errors = validate_hardware_evidence(args.hardware_evidence)
    manifest = read_object(args.hardware_evidence)
    sass = read_object(args.sass_summary)
    classes = observed_classes(sass)
    role_sources = sources_by_role(manifest)
    nodes: dict[str, dict] = {}
    unresolved: list[dict] = []
    if sass.get("schema_version") != "sass-instruction-count-v2" or sass.get("status") != "PASS":
        unresolved.append({"kind": "SASS_COVERAGE", "reason": "SASS summary must be a PASS sass-instruction-count-v2 artifact"})
    coverage = sass.get("coverage", {})
    if coverage.get("status") != "PASS" or coverage.get("site_coverage_fraction") != 1.0:
        unresolved.append({"kind": "SASS_COVERAGE", "reason": "every final-binary static instruction site must have exactly one lexical class"})
    if sass.get("unclassified_mnemonics") or sass.get("ambiguous_mnemonics"):
        unresolved.append({
            "kind": "SASS_COVERAGE",
            "unclassified_mnemonics": sass.get("unclassified_mnemonics", {}),
            "ambiguous_mnemonics": sass.get("ambiguous_mnemonics", {}),
        })
    validate_identity(args.sass_summary.parent, sass.get("input_sass_identity", {}), "SASS input", unresolved_errors := [])
    validate_identity(args.sass_summary.parent, sass.get("final_binary_identity", {}), "final binary", unresolved_errors)
    validate_identity(args.sass_summary.parent, sass.get("disassembly_receipt_identity", {}), "disassembly receipt", unresolved_errors)
    try:
        binary_path = Path(sass.get("final_binary_identity", {}).get("path", ""))
        sass_input_path = Path(sass.get("input_sass_identity", {}).get("path", ""))
        receipt_path = Path(sass.get("disassembly_receipt_identity", {}).get("path", ""))
        if not binary_path.is_absolute(): binary_path = args.sass_summary.parent / binary_path
        if not sass_input_path.is_absolute(): sass_input_path = args.sass_summary.parent / sass_input_path
        if not receipt_path.is_absolute(): receipt_path = args.sass_summary.parent / receipt_path
        _, receipt_errors = validate_disassembly_receipt(receipt_path, binary_path, sass_input_path)
        unresolved_errors.extend(receipt_errors)
    except Exception as error:
        unresolved_errors.append(f"cannot validate disassembly receipt: {error}")
    unresolved.extend({"kind": "BINARY_IDENTITY", "reason": error} for error in unresolved_errors)
    unresolved.extend(
        {"kind": "TARGET_IDENTITY", "reason": error}
        for error in target_fields_match(manifest.get("target_identity", {}), sass.get("disassembly_target", {}))
    )
    test_policy = manifest.get("official_source_policy", {}).get("policy", {}).get("test_fixture_only") is True

    for instruction_class, count in classes.items():
        rule = CLASS_RULES.get(instruction_class)
        if rule is None:
            unresolved.append({
                "instruction_class": instruction_class,
                "reason": "no conservative resource detection rule",
                "developer_action": "provide an official instruction/resource document locator and add a reviewed detection rule",
            })
            continue
        resource_ids, roles = rule
        mapping_fact = reviewed_mapping_fact(manifest, instruction_class)
        if not test_policy:
            if mapping_fact is None:
                unresolved.append({
                    "instruction_class": instruction_class,
                    "reason": "no reviewed official instruction-class to resource mapping fact",
                    "developer_action": f"add DOCUMENTED_FACT field=instruction_class.{instruction_class}.resource_ids with exact support text",
                })
                continue
            documented_resources = set(map(str, mapping_fact.get("value", [])))
            if documented_resources != set(resource_ids):
                unresolved.append({
                    "instruction_class": instruction_class,
                    "reason": "reviewed official mapping does not exactly match the versioned detector rule",
                    "rule_resources": sorted(resource_ids),
                    "documented_resources": sorted(documented_resources),
                })
                continue
        missing = [role for role in roles if role not in role_sources]
        if missing:
            unresolved.append({
                "instruction_class": instruction_class,
                "required_document_roles": roles,
                "missing_document_roles": missing,
                "reason": "final-binary observation cannot be mapped without exact official documentation",
            })
            continue
        evidence = [
            {
                "source_id": source["source_id"],
                "role": role,
                "locator": locator_value(source),
                "url": source.get("url"),
            }
            for role in roles
            for source in role_sources[role]
        ]
        if mapping_fact is not None:
            evidence.append({
                "source_id": mapping_fact.get("source_id"),
                "role": "instruction_resource_mapping",
                "locator": locator_value(mapping_fact),
                "url": next((item.get("url") for item in manifest.get("sources", []) if item.get("source_id") == mapping_fact.get("source_id")), None),
            })
        for resource_id in resource_ids:
            node = nodes.setdefault(resource_id, {
                "resource_id": resource_id,
                "status": "DETECTED",
                "triggers": [],
                "official_evidence": [],
                "documented_performance_parameters": [],
                "empirical_service_parameters": [],
            })
            node["triggers"].append({"instruction_class": instruction_class, "static_sites": count})
            known = {(item["source_id"], item["locator"]) for item in node["official_evidence"]}
            node["official_evidence"].extend(
                item for item in evidence if (item["source_id"], item["locator"]) not in known
            )

    # A launched binary always consumes dispatch/CTA-allocation state.  These
    # boundaries are admitted only when the programming model is documented.
    if classes:
        role = "programming_model"
        if role in role_sources:
            evidence = [{
                "source_id": source["source_id"], "role": role,
                "locator": locator_value(source), "url": source.get("url"),
            } for source in role_sources[role]]
            for resource_id in ("kernel_dispatch", "cta_allocation"):
                nodes.setdefault(resource_id, {
                    "resource_id": resource_id,
                    "status": "DETECTED",
                    "triggers": [{"instruction_class": "launched_binary", "static_sites": 1}],
                    "official_evidence": evidence,
                    "documented_performance_parameters": [],
                    "empirical_service_parameters": [],
                })
        else:
            unresolved.append({"instruction_class": "launched_binary", "missing_document_roles": [role]})

    current_required = set(nodes)
    official_available = set()
    for fact in manifest.get("facts", []):
        field = str(fact.get("field", ""))
        parts = field.split(".")
        if len(parts) >= 3 and parts[0] == "resource":
            resource_id = parts[1]
            parameter = ".".join(parts[2:])
            if parameter == "available" and fact.get("value") is True:
                official_available.add(resource_id)
            if parameter == "available" and fact.get("value") is not True:
                continue
            if resource_id not in official_available and resource_id not in nodes and parameter != "available":
                unresolved.append({
                    "kind": "OFFICIAL_RESOURCE_FACT",
                    "resource_id": resource_id,
                    "reason": "resource parameter is present without resource.<id>.available=true",
                })
                continue
            node = nodes.setdefault(resource_id, {
                "resource_id": resource_id,
                "status": "OFFICIALLY_AVAILABLE",
                "triggers": [],
                "official_evidence": [],
                "documented_performance_parameters": [],
                "empirical_service_parameters": [],
            })
            source = next((item for item in manifest.get("sources", []) if item.get("source_id") == fact.get("source_id")), {})
            node["official_evidence"].append({
                "source_id": fact.get("source_id"), "role": source.get("role"),
                "locator": locator_value(fact), "url": source.get("url"),
            })
            if parameter != "available":
                node["documented_performance_parameters"].append({
                    "field": parameter, "value": fact.get("value"), "unit": fact.get("unit"),
                    "source_id": fact.get("source_id"), "locator": locator_value(fact),
                })

    status = "READY" if not manifest_errors and not unresolved and manifest.get("status") == "READY" else "BLOCKED"
    result = {
        "schema_version": "resource-discovery-v2",
        "status": status,
        "detector_identity": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve())},
        "binary_identity": sass.get("final_binary_identity", {}),
        "sass_input_identity": sass.get("input_sass_identity", {}),
        "sass_summary_identity": {"path": str(args.sass_summary.resolve()), "sha256": sha256(args.sass_summary)},
        "disassembly_receipt_identity": sass.get("disassembly_receipt_identity", {}),
        "hardware_evidence_identity": {"path": str(args.hardware_evidence.resolve()), "sha256": sha256(args.hardware_evidence)},
        "observed_instruction_classes": [
            {"instruction_class": name, "static_sites": count}
            for name, count in classes.items()
        ],
        "required_resource_ids": sorted(current_required),
        "official_available_resource_ids": sorted(official_available),
        "candidate_resource_ids": sorted(set(nodes) | official_available),
        "resource_nodes": [nodes[name] for name in sorted(nodes)],
        "unresolved_mappings": [
            *({"kind": "HARDWARE_EVIDENCE_ERROR", "detail": error} for error in manifest_errors),
            *unresolved,
        ],
        "exclusions": [],
        "completeness_contract": {
            "scope": "all final-binary mnemonic sites, uniquely classified instruction/resource mappings, launch allocation and exact official document roles",
            "static_mnemonic_coverage_required": 1.0,
            "does_not_claim": [
                "undocumented proprietary internal pipelines",
                "a numeric throughput or latency without an official fact or target measurement",
                "dynamic instruction counts from static sites",
            ],
            "manual_resource_omission_forbidden": True,
            "unresolved_mapping_blocks_modeling": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": status, "resources": len(nodes), "unresolved": len(result["unresolved_mappings"]), "output": str(args.output)}, sort_keys=True))
    return 0 if status == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
