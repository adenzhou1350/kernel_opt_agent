#!/usr/bin/env python3
"""Audit source tile schedule, final cubin SASS and ptxas resources."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from experiment_common import CANDIDATES, SCREENING_SEQUENCES, identity, write_json


FUNCTION = re.compile(r"^\s*Function\s*:\s*(.+)$")
INSTRUCTION = re.compile(r"/\*[0-9a-fA-F]+\*/\s+(?:@[!P0-9]+\s+)?([A-Z][A-Z0-9_.]*)")
RESOURCE_FUNCTION = re.compile(r"^\s*Function\s+(.+):$")
REGISTERS = re.compile(r"REG:(\d+)")
STACK = re.compile(r"STACK:(\d+)")
SHARED = re.compile(r"SHARED:(\d+)")
LOCAL = re.compile(r"LOCAL:(\d+)")


def sections(text: str) -> dict[str, list[str]]:
    result, current = {}, None
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


def resources(text: str) -> dict[str, dict]:
    result, current = {}, None
    for line in text.splitlines():
        match = RESOURCE_FUNCTION.match(line)
        if match:
            current = match.group(1)
            result[current] = {"raw": []}
        elif current is not None:
            result[current]["raw"].append(line)
    for value in result.values():
        raw = " ".join(value.pop("raw"))
        for name, pattern in (
            ("registers", REGISTERS),
            ("stack", STACK),
            ("shared", SHARED),
            ("local", LOCAL),
        ):
            match = pattern.search(raw)
            value[name] = None if match is None else int(match.group(1))
    return result


def select(mapping: dict, token: str) -> tuple[str, object]:
    matches = [(name, value) for name, value in mapping.items() if token in name]
    if len(matches) != 1:
        raise RuntimeError(f"expected one function containing {token}, got {[x[0] for x in matches]}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = run / "experiments/req-s3-tile-causal-production-ab"
    build = json.loads((experiment / "build/manifest.json").read_text())
    if build.get("status") != "PASS":
        raise RuntimeError("build gate did not pass")

    source_dir = run / "microbench_candidates/req-s3-tile-causal-production-ab/candidate_pkg"
    source_text = "\n".join(
        (source_dir / name).read_text()
        for name in ("qwen35_fla_s3_short_raw_sm120.py", "qwen35_fla_s3_long_raw_sm120.py")
    )
    required_source = (
        "assert output.layout == output_tiles_layout",
        "for row_tile in cutlass.range_constexpr(BT // 16)",
        "if cutlass.const_expr(col_tile <= row_tile)",
        "and cutlass.Int32(col_tile) <= warp_idx",
        "candidate_id=candidate_id",
    )
    missing = [token for token in required_source if token not in source_text and token not in (source_dir / "qwen35_fla_pipeline_sm120.py").read_text()]
    if missing:
        raise RuntimeError(f"source schedule audit failed: {missing}")

    config_audits = {}
    for config in build["configurations"]:
        key = f"{config['candidate_id'].lower()}_s{config['sequence']}"
        cubin = Path(config["binary"]["cubin"]["path"])
        sass_path = experiment / "static" / f"{key}.sass"
        resource_path = experiment / "static" / f"{key}.resources.txt"
        sass_path.parent.mkdir(parents=True, exist_ok=True)
        sass_text = subprocess.run(
            ["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(cubin)],
            check=True, text=True, stdout=subprocess.PIPE,
        ).stdout
        resource_text = subprocess.run(
            ["/usr/local/cuda/bin/cuobjdump", "--dump-resource-usage", str(cubin)],
            check=True, text=True, stdout=subprocess.PIPE,
        ).stdout
        sass_path.write_text(sass_text)
        resource_path.write_text(resource_text)
        funcs, usage = sections(sass_text), resources(resource_text)
        s3_token = "qwen35_fla_s3_short_raw_sm120" if config["sequence"] <= 640 else "qwen35_fla_s3_long_raw_sm120"
        s3_name, s3_ops = select(funcs, s3_token)
        _, s3_usage = select(usage, s3_token)
        hmmas = sum(op.startswith("HMMA") for op in s3_ops)
        barriers = sum(op.startswith("BAR") for op in s3_ops)
        stack = s3_usage.get("stack")
        registers = s3_usage.get("registers")
        shared = s3_usage.get("shared")
        cap_registers = 126 if config["sequence"] <= 640 else 128
        cap_shared = 73984 if config["sequence"] <= 640 else 49408
        local = s3_usage.get("local")
        if (
            stack not in (0, None)
            or local not in (0, None)
            or registers is None
            or registers > cap_registers
            or shared is None
            or shared > cap_shared
        ):
            raise RuntimeError(f"resource cap failed for {key}: {s3_usage}")
        config_audits[key] = {
            "cubin": identity(cubin),
            "sass": identity(sass_path),
            "resource_text": identity(resource_path),
            "s3_function": s3_name,
            "s3_hmma_static_sites": hmmas,
            "s3_barrier_static_sites": barriers,
            "s3_resources": s3_usage,
            "functions": {name: ops for name, ops in funcs.items()},
        }

    for sequence in SCREENING_SEQUENCES:
        c0 = config_audits[f"c0_s{sequence}"]
        c1 = config_audits[f"c1_s{sequence}"]
        static_hmma_delta = c0["s3_hmma_static_sites"] - c1["s3_hmma_static_sites"]
        if static_hmma_delta != 12:
            raise RuntimeError(
                f"S={sequence}: expected exactly 12 fewer S3 HMMA sites, got {static_hmma_delta}"
            )
        if c1["s3_barrier_static_sites"] != c0["s3_barrier_static_sites"]:
            raise RuntimeError(f"S={sequence}: barrier topology changed")
        for token in ("qwen35_fla_s01_sm120", "qwen35_fla_s2_sm120", "qwen35_fla_post_sm120"):
            c0_match = select(c0["functions"], token)[1]
            c1_match = select(c1["functions"], token)[1]
            if c0_match != c1_match:
                raise RuntimeError(f"S={sequence}: unchanged stage differs: {token}")

    expected_dynamic = {
        "static_per_warp_program": {
            "qk_c0_hmma_sites": 64,
            "qk_c1_hmma_sites": 64,
            "score_v_c0_hmma_sites": 32,
            "score_v_c1_hmma_sites": 20,
            "expected_total_s3_hmma_site_delta_c0_minus_c1": 12,
            "explanation": "QK skips tiles by runtime row-warp predicates, so its static sites remain; score-V has ten constexpr tile pairs and removes 12 static sites.",
        },
        "full_chunk": {
            "c0_tile_pairs": 16,
            "c1_tile_pairs": 10,
            "c0_qk_warp_hmma": 256,
            "c1_qk_warp_hmma": 160,
            "c0_score_v_warp_hmma": 256,
            "c1_score_v_warp_hmma": 160,
        },
        "s404_tail": {
            "valid_tokens": 20,
            "pairs": [[0, 0], [1, 0], [1, 1]],
            "c1_tile_pairs": 3,
        },
        "s404_per_head": {"c0_tile_pairs": 112, "c1_tile_pairs": 63},
        "s768_per_head": {"c0_tile_pairs": 192, "c1_tile_pairs": 120},
        "launch_geometry": {
            "s404": {"grid_s3": [112, 1, 1], "block_s3": [512, 1, 1], "dynamic_shared_bytes": 73984},
            "s768": {"grid_s3": [192, 1, 1], "block_s3": [256, 1, 1], "dynamic_shared_bytes": 49408},
        },
        "derivation": "m16n8k16: QK tile m16n16k128 = 2*8 HMMA; scoreV per D-warp tile m16n16k16 = 2 HMMA, 8 D warps",
    }
    summary = {
        "schema_version": "qwen35-s3-tile-ab-static-audit-v1",
        "status": "PASS",
        "source_contract": identity(source_dir / "CANDIDATE_CONTRACT.md"),
        "expected_dynamic_tile_audit": expected_dynamic,
        "configurations": config_audits,
    }
    write_json(experiment / "static/instruction_audit.json", summary)


if __name__ == "__main__":
    main()
