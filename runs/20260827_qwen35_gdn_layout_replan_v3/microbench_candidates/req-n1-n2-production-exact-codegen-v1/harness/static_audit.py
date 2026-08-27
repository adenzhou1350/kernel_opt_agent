#!/usr/bin/env python3
"""Audit exact cubin SASS, unchanged stages and hard resource caps."""

from __future__ import annotations

import argparse
import re
import subprocess
import traceback
from pathlib import Path

from common import (
    CANDIDATES,
    EXPERIMENT_ROOT,
    PATHS,
    dump,
    gate,
    identity,
    require_run,
    verify_bound_sources,
    verify_experiment_source_seal,
)


FUNCTION = re.compile(r"^\s*Function\s*:\s*(.+)$")
INSTRUCTION = re.compile(
    r"/\*[0-9a-fA-F]+\*/\s+(?:@[!P0-9]+\s+)?([A-Z][A-Z0-9_.]*)"
)
INSTRUCTION_RECORD = re.compile(
    r"/\*[0-9a-fA-F]+\*/\s+(?:@[!P0-9]+\s+)?"
    r"([A-Z][A-Z0-9_.]*)\s*([^;]*);"
)
RESOURCE_FUNCTION = re.compile(r"^\s*Function\s+(.+):$")
RESOURCE_PATTERNS = {
    "registers": re.compile(r"REG:(\d+)"),
    "stack": re.compile(r"STACK:(\d+)"),
    "shared": re.compile(r"SHARED:(\d+)"),
    "local": re.compile(r"LOCAL:(\d+)"),
}


def sass_sections(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        match = FUNCTION.match(line)
        if match:
            current = match.group(1)
            result[current] = []
        elif current is not None:
            opcode = INSTRUCTION.search(line)
            if opcode:
                result[current].append(opcode.group(1))
    return result


def sass_instruction_sections(text: str) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    current = None
    for line in text.splitlines():
        match = FUNCTION.match(line)
        if match:
            current = match.group(1)
            result[current] = []
        elif current is not None:
            instruction = INSTRUCTION_RECORD.search(line)
            if instruction:
                result[current].append({
                    "opcode": instruction.group(1),
                    "operands": instruction.group(2).strip(),
                    "text": line.strip(),
                })
    return result


def immediate_values(operands: str) -> list[int]:
    result = []
    for token in re.findall(r"(?<![A-Za-z0-9_])(?:0x[0-9a-fA-F]+|\d+)", operands):
        result.append(int(token, 0))
    return result


def resource_sections(text: str) -> dict[str, dict]:
    raw: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        match = RESOURCE_FUNCTION.match(line)
        if match:
            current = match.group(1)
            raw[current] = []
        elif current is not None:
            raw[current].append(line)
    result = {}
    for name, lines in raw.items():
        joined = " ".join(lines)
        result[name] = {
            field: (None if (match := pattern.search(joined)) is None else int(match.group(1)))
            for field, pattern in RESOURCE_PATTERNS.items()
        }
    return result


def select(mapping: dict, token: str):
    matches = [(name, value) for name, value in mapping.items() if token in name]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one function containing {token!r}, got {[x[0] for x in matches]}"
        )
    return matches[0]


def disassemble(entry: dict, output: Path, config: dict) -> dict:
    cubin = Path(entry["cubin"]["path"])
    stem = f"{entry['candidate_id'].lower()}_{entry['production_path']}"
    sass_path = output / f"{stem}.sass"
    resources_path = output / f"{stem}.resources.txt"
    sass_text = subprocess.run(
        ["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(cubin)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    resources_text = subprocess.run(
        ["/usr/local/cuda/bin/cuobjdump", "--dump-resource-usage", str(cubin)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    sass_path.write_text(sass_text)
    resources_path.write_text(resources_text)
    functions = sass_sections(sass_text)
    instruction_sections = sass_instruction_sections(sass_text)
    resources = resource_sections(resources_text)
    s3_name, s3_ops = select(functions, config["s3_token"])
    instruction_name, s3_instructions = select(
        instruction_sections, config["s3_token"]
    )
    if instruction_name != s3_name:
        raise RuntimeError("SASS function record parsing disagrees on S3 symbol")
    _, s3_resources = select(resources, config["s3_token"])
    ptx_text = Path(entry["ptx"]["path"]).read_text(errors="replace")
    return {
        "status": "PASS_DISASSEMBLY",
        "candidate_id": entry["candidate_id"],
        "model_candidate_id": entry.get("model_candidate_id"),
        "production_path": entry["production_path"],
        "cubin": identity(cubin),
        "ptx": entry["ptx"],
        "sass": identity(sass_path),
        "resource_text": identity(resources_path),
        "s3_function": s3_name,
        "s3_opcodes": s3_ops,
        "s3_instructions": s3_instructions,
        "s3_hmma_static_sites": sum(op.startswith("HMMA") for op in s3_ops),
        "s3_barrier_static_sites": sum(op.startswith("BAR") for op in s3_ops),
        "s3_resources": s3_resources,
        "runtime_assert_tokens": {
            "ptx_assertfail": "__assertfail" in ptx_text,
            "sass_trap": any(
                op.startswith(("TRAP", "BPT", "BRKPT")) for op in s3_ops
            ),
        },
        "functions": functions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = require_run(args.run)
    verify_experiment_source_seal(run)
    bound_sources = verify_bound_sources()
    build = gate(EXPERIMENT_ROOT / "build/manifest.json")["payload"]
    output = EXPERIMENT_ROOT / "static"
    output.mkdir(parents=True, exist_ok=True)

    entries = {
        (item.get("candidate_id"), item.get("production_path")): item
        for item in build["configurations"]
    }
    audits = {}
    try:
        for path_name, config in PATHS.items():
            control = entries[("C0", path_name)]
            if control.get("status") != "PASS_CODEGEN":
                raise RuntimeError(f"C0 build control unavailable: {path_name}")
            audits[("C0", path_name)] = disassemble(
                control, output, config
            )
    except Exception as error:
        dump(output / "invalid_infrastructure.json", {
            "schema_version": "qwen35-n1-n2-static-infra-v1",
            "status": "INVALID",
            "error": str(error),
            "traceback": traceback.format_exc(),
            "candidate_disposition": "NONE",
        })
        raise RuntimeError("INVALID_INFRA: C0 disassembly/resource control failed") from error

    candidate_results = []
    for model_id, candidate_id in CANDIDATES.items():
        for path_name, config in PATHS.items():
            entry = entries[(candidate_id, path_name)]
            if entry.get("status") != "PASS_CODEGEN":
                candidate_results.append({
                    "candidate_id": model_id,
                    "binary_candidate_id": candidate_id,
                    "production_path": path_name,
                    "status": "FAIL",
                    "reason": entry.get("status"),
                    "build_entry": entry,
                })
                continue
            try:
                audit = disassemble(entry, output, config)
                audits[(candidate_id, path_name)] = audit
                control = audits[("C0", path_name)]
                reasons = []
                usage = audit["s3_resources"]
                if usage.get("registers") is None or usage["registers"] > config["register_cap"]:
                    reasons.append("REGISTER_CAP")
                if usage.get("shared") is None or usage["shared"] > config["shared_cap"]:
                    reasons.append("SHARED_CAP")
                if usage.get("stack") not in (0, None):
                    reasons.append("STACK_FRAME")
                if usage.get("local") not in (0, None):
                    reasons.append("LOCAL_MEMORY")
                if any(op.startswith(("LDL", "STL")) for op in audit["s3_opcodes"]):
                    reasons.append("SASS_LOCAL_LOAD_STORE")
                if any(audit["runtime_assert_tokens"].values()):
                    reasons.append("RUNTIME_ASSERT_OR_TRAP")
                expected_barrier_delta = 1 if path_name == "long_s1024" else 0
                observed_barrier_delta = (
                    audit["s3_barrier_static_sites"]
                    - control["s3_barrier_static_sites"]
                )
                if observed_barrier_delta != expected_barrier_delta:
                    reasons.append(
                        "BARRIER_STATIC_DELTA_EXPECTED_"
                        f"{expected_barrier_delta}_GOT_{observed_barrier_delta}"
                    )

                alias_lifetime_sass = None
                if path_name == "long_s1024":
                    instructions = audit["s3_instructions"]
                    named_barriers = [
                        index for index, instruction in enumerate(instructions)
                        if instruction["opcode"].startswith("BAR")
                        and 1 in immediate_values(instruction["operands"])
                        and 128 in immediate_values(instruction["operands"])
                    ]
                    stmatrix = [
                        index for index, instruction in enumerate(instructions)
                        if instruction["opcode"].startswith(("STMATRIX", "STSM"))
                    ]
                    first_score_store = stmatrix[0] if stmatrix else None
                    pre_store_ldsm = [
                        index for index, instruction in enumerate(instructions)
                        if instruction["opcode"].startswith("LDSM")
                        and first_score_store is not None
                        and index < first_score_store
                    ]
                    named_position = (
                        named_barriers[0] if len(named_barriers) == 1 else None
                    )
                    alias_lifetime_sass = {
                        "named_barrier_1_128_positions": named_barriers,
                        "first_stmatrix_position": first_score_store,
                        "pre_store_ldsm_positions": pre_store_ldsm,
                        "all_pre_store_ldsm_before_named_barrier": (
                            named_position is not None
                            and all(index < named_position for index in pre_store_ldsm)
                        ),
                        "named_barrier_precedes_first_stmatrix": (
                            named_position is not None
                            and first_score_store is not None
                            and named_position < first_score_store
                        ),
                    }
                    if (
                        len(named_barriers) != 1
                        or first_score_store is None
                        or not alias_lifetime_sass[
                            "all_pre_store_ldsm_before_named_barrier"
                        ]
                        or not alias_lifetime_sass[
                            "named_barrier_precedes_first_stmatrix"
                        ]
                    ):
                        reasons.append(
                            "LONG_K_READ_BARRIER_1_128_SCORE_STMATRIX_ORDER"
                        )
                if audit["s3_opcodes"] == control["s3_opcodes"]:
                    reasons.append("S3_FINAL_SASS_MECHANISM_ABSENT")
                control_predicate_ops = sum(
                    op.startswith(("ISETP", "PLOP", "BRA"))
                    for op in control["s3_opcodes"]
                )
                candidate_predicate_ops = sum(
                    op.startswith(("ISETP", "PLOP", "BRA"))
                    for op in audit["s3_opcodes"]
                )
                if candidate_predicate_ops <= control_predicate_ops:
                    reasons.append(
                        "QK_CAUSAL_CONTROL_NOT_VISIBLE_IN_FINAL_SASS"
                    )

                expected_delta = 0 if model_id == "N1" else 12
                observed_delta = (
                    control["s3_hmma_static_sites"]
                    - audit["s3_hmma_static_sites"]
                )
                if observed_delta != expected_delta:
                    reasons.append(
                        f"HMMA_STATIC_DELTA_EXPECTED_{expected_delta}_GOT_{observed_delta}"
                    )

                for token in (
                    "qwen35_fla_s01_sm120",
                    "qwen35_fla_s2_sm120",
                    "qwen35_fla_post_sm120",
                ):
                    if select(control["functions"], token)[1] != select(audit["functions"], token)[1]:
                        reasons.append(f"UNCHANGED_STAGE_DIFF:{token}")

                candidate_results.append({
                    "candidate_id": model_id,
                    "binary_candidate_id": candidate_id,
                    "production_path": path_name,
                    "status": "PASS" if not reasons else "FAIL",
                    "reasons": reasons,
                    "expected_hmma_static_delta_vs_c0": expected_delta,
                    "observed_hmma_static_delta_vs_c0": observed_delta,
                    "c0_predicate_control_sites": control_predicate_ops,
                    "candidate_predicate_control_sites": candidate_predicate_ops,
                    "expected_barrier_static_delta_vs_c0": expected_barrier_delta,
                    "observed_barrier_static_delta_vs_c0": observed_barrier_delta,
                    "long_alias_lifetime_sass": alias_lifetime_sass,
                    "audit": {
                        key: value for key, value in audit.items()
                        if key not in {
                            "functions", "s3_opcodes", "s3_instructions"
                        }
                    },
                })
            except Exception as error:
                candidate_results.append({
                    "candidate_id": model_id,
                    "binary_candidate_id": candidate_id,
                    "production_path": path_name,
                    "status": "FAIL",
                    "reason": "CANDIDATE_DISASSEMBLY_OR_AUDIT_FAILURE",
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                })

    summary = {
        "schema_version": "qwen35-n1-n2-codegen-static-audit-v1",
        "status": "PASS",
        "bound_sources": bound_sources,
        "zero_gpu_execution": True,
        "candidate_results": candidate_results,
        "control_results": [
            {
                key: value for key, value in audits[("C0", path_name)].items()
                if key not in {"functions", "s3_opcodes", "s3_instructions"}
            }
            for path_name in PATHS
        ],
        "interpretation": (
            "N1 keeps the static HMMA-site count and changes dynamic QK warp "
            "eligibility; N2 additionally removes exactly 12 scoreV HMMA sites."
        ),
        "claims_forbidden": [
            "numerical correctness",
            "GPU latency or speedup",
            "dynamic executed-instruction count",
            "production acceptance",
        ],
    }
    dump(output / "instruction_audit.json", summary)
    print("PASS: final-cubin SASS/resource audit completed; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
