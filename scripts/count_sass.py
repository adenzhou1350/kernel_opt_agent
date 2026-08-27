#!/usr/bin/env python3
"""Classify every final-binary SASS mnemonic; unknown or ambiguous sites fail closed."""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from evidence_utils import read_object, sha256


FUNCTION = re.compile(r"^\s*Function\s*:\s*(.+?)\s*$")
INSTRUCTION = re.compile(r"/\*[0-9a-fA-F]+\*/\s+(?:@[!A-Z0-9]+\s+)?([A-Z][A-Z0-9_.]*)\b")

# Lexical detection rules are not throughput facts.  They deliberately remain
# disjoint; a new mnemonic must be reviewed instead of disappearing into a
# broad catch-all.  Resource semantics are admitted later from official facts.
CLASS_PATTERNS = {
    "barrier": (
        r"^BAR(?:\.|$)",
        r"^MBARRIER(?:\.|$)",
        r"^SYNCS\.(?:ARRIVE|EXCH)(?:\.|$)",
    ),
    "branch_control": (r"^(?:BRA|BRX|BSSY|BSYNC|EXIT|RET|CALL|YIELD)(?:\.|$)",),
    "control_noop": (r"^NOP(?:\.|$)",),
    "async_copy": (r"^(?:LDGSTS|CPASYNC|UTMA|TMA)",),
    "global_load": (r"^LDG(?!STS)(?:\.|$)",),
    "global_store": (r"^STG(?:\.|$)",),
    "local_load": (r"^LDL(?:\.|$)",),
    "local_store": (r"^STL(?:\.|$)",),
    "constant_load": (r"^(?:LDC|LDCU)(?:\.|$)",),
    "shared_load": (r"^(?:LDS|LDSM)(?:\.|$)",),
    "shared_store": (r"^(?:STS|STSM)(?:\.|$)",),
    "surface_texture": (r"^(?:TEX|TLD|SULD|SUST)(?:\.|$)",),
    "atomic_reduction": (r"^(?:ATOM|RED)(?:\.|$)",),
    "tensor": (r"^(?:HMMA|IMMA|MMA|WGMMA|QGMMA|UTCMMA|TCGEN)(?:\.|$)",),
    "simt_fp": (r"^(?:FFMA|FADD|FMUL|FSET|FSEL|FHADD|FHFMA|HFMA2?|HADD2?|HMUL2?|DADD|DMUL|DFMA)(?:\.|$)",),
    "integer_address": (r"^(?:IABS|IADD3?|IMAD|IMNMX|LEA|SHF|LOP3?|UIMAD|UIADD3?|ULEA|USHF|ULOP3?|VIMNMX|UVIMNMX)(?:\.|$)",),
    "predicate_compare": (r"^(?:ISETP|UISETP|FSETP|DSETP|HSETP2?|FCHK|PLOP3)(?:\.|$)",),
    "move_select": (r"^(?:MOV|UMOV|SEL|USEL|PRMT|P2R|R2UR)(?:\.|$)",),
    "conversion": (r"^(?:F2F|F2FP|F2I|I2F|I2I)(?:\.|$)",),
    "special_function": (r"^MUFU(?:\.|$)",),
    "system_register": (r"^(?:S2R|S2UR|CS2R)(?:\.|$)",),
    "warp_collective": (r"^(?:SHFL|VOTE|MATCH|REDUX|ELECT|ENDCOLLECTIVE)(?:\.|$)",),
    "memory_wait": (
        r"^(?:DEPBAR|WARPSYNC|MEMBAR|NANOSLEEP)(?:\.|$)",
        r"^FENCE\.(?:VIEW|PROXY)(?:\.|$)",
        r"^SYNCS\.PHASECHK(?:\.|$)",
    ),
}
COMPILED_PATTERNS = {
    name: tuple(re.compile(pattern) for pattern in patterns)
    for name, patterns in CLASS_PATTERNS.items()
}


def classify_mnemonic(mnemonic: str) -> list[str]:
    return [
        name for name, patterns in COMPILED_PATTERNS.items()
        if any(pattern.match(mnemonic) for pattern in patterns)
    ]


def validate_disassembly_receipt(receipt_path: Path, binary: Path, sass: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    receipt = read_object(receipt_path)
    if receipt.get("schema_version") != "final-binary-disassembly-receipt-v1":
        errors.append("invalid final-binary disassembly receipt schema")
    if receipt.get("status") != "PASS" or receipt.get("exit_code") != 0:
        errors.append("disassembly receipt must record a successful tool execution")
    if receipt.get("binary_identity", {}).get("sha256") != sha256(binary):
        errors.append("disassembly receipt binary hash does not match --binary")
    if receipt.get("sass_identity", {}).get("sha256") != sha256(sass):
        errors.append("disassembly receipt SASS hash does not match --input")
    for field in ("command", "tool", "target"):
        if not receipt.get(field):
            errors.append(f"disassembly receipt {field} is required")
    target = receipt.get("target", {})
    if str(target.get("vendor", "")).upper() != "TEST":
        probe = receipt.get("architecture_probe", {})
        expected_architecture = str(target.get("architecture_code", "")).lower()
        discovered = {str(item).lower() for item in probe.get("discovered_architecture_codes", [])}
        if probe.get("exit_code") != 0 or not expected_architecture or expected_architecture not in discovered:
            errors.append("disassembly receipt: target architecture is not proven by the binary architecture probe")
        tool_path = Path(str(receipt.get("tool", {}).get("path", "")))
        if not tool_path.is_file() or receipt.get("tool", {}).get("sha256") != sha256(tool_path):
            errors.append("disassembly receipt: disassembler tool identity mismatch")
    return receipt, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="cuobjdump/nvdisasm SASS text")
    parser.add_argument("--binary", type=Path, required=True, help="exact launched cubin/so/executable")
    parser.add_argument("--disassembly-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.input, args.binary, args.disassembly_receipt):
        if not path.is_file():
            raise FileNotFoundError(path)
    receipt, receipt_errors = validate_disassembly_receipt(args.disassembly_receipt, args.binary, args.input)

    functions: dict[str, collections.Counter] = {}
    current = None
    for line in args.input.read_text(errors="replace").splitlines():
        match = FUNCTION.match(line)
        if match:
            current = match.group(1)
            functions.setdefault(current, collections.Counter())
            continue
        instruction = INSTRUCTION.search(line)
        if current and instruction:
            functions[current][instruction.group(1)] += 1

    unclassified: dict[str, int] = {}
    ambiguous: dict[str, dict] = {}
    output_functions = {}
    total_sites = classified_sites = 0
    all_mnemonics: dict[str, int] = {}
    for name, counts in sorted(functions.items()):
        classes: collections.Counter = collections.Counter()
        function_unknown = {}
        function_ambiguous = {}
        for mnemonic, count in counts.items():
            all_mnemonics[mnemonic] = all_mnemonics.get(mnemonic, 0) + count
            total_sites += count
            matches = classify_mnemonic(mnemonic)
            if len(matches) == 1:
                classes[matches[0]] += count
                classified_sites += count
            elif not matches:
                function_unknown[mnemonic] = count
                unclassified[mnemonic] = unclassified.get(mnemonic, 0) + count
            else:
                function_ambiguous[mnemonic] = {"count": count, "classes": matches}
                ambiguous[mnemonic] = {"count": ambiguous.get(mnemonic, {}).get("count", 0) + count, "classes": matches}
        output_functions[name] = {
            "instruction_count": sum(counts.values()),
            "mnemonics": dict(sorted(counts.items())),
            "classes": dict(sorted(classes.items())),
            "unclassified_mnemonics": function_unknown,
            "ambiguous_mnemonics": function_ambiguous,
        }
    status = "PASS" if total_sites > 0 and classified_sites == total_sites and not receipt_errors else "BLOCKED"
    result = {
        "schema_version": "sass-instruction-count-v2",
        "status": status,
        "input_sass_identity": {"path": str(args.input.resolve()), "sha256": sha256(args.input)},
        "final_binary_identity": {"path": str(args.binary.resolve()), "sha256": sha256(args.binary)},
        "disassembly_receipt_identity": {"path": str(args.disassembly_receipt.resolve()), "sha256": sha256(args.disassembly_receipt)},
        "disassembly_target": receipt.get("target", {}),
        "functions": output_functions,
        "all_mnemonics": dict(sorted(all_mnemonics.items())),
        "unclassified_mnemonics": dict(sorted(unclassified.items())),
        "ambiguous_mnemonics": dict(sorted(ambiguous.items())),
        "coverage": {
            "status": status,
            "total_static_sites": total_sites,
            "classified_static_sites": classified_sites,
            "site_coverage_fraction": classified_sites / total_sites if total_sites else 0.0,
            "unique_mnemonics": len(all_mnemonics),
            "classified_unique_mnemonics": len(all_mnemonics) - len(unclassified) - len(ambiguous),
        },
        "validation_errors": receipt_errors,
        "caveat": "Static coverage is complete for final-binary mnemonic sites; dynamic counts, replay and proprietary pipelines remain separate evidence questions.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": status, "functions": len(functions), "instructions": total_sites, "unclassified": len(unclassified), "ambiguous": len(ambiguous)}, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
