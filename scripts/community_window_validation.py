#!/usr/bin/env python3
"""Validate one discovery window once and record exact CPU validation time."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from community_discovery_funnel import validate_funnel
from community_evaluation import (
    validate_feasibility_screen,
    validate_heldout_queue,
    validate_preselection_chain_audit,
)
from community_knowledge import atomic_json, now, sha256_file
from community_validation_session import ValidationSession
from schema_utils import validate_instance


SCHEMA_VERSION = "community-window-validation-v1"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def validate_window(
    queue: Path,
    screen: Path,
    audit: Path,
    funnel: Path,
    corpus: Path,
    source_root: Path,
    implementation_root: Path | None = None,
    compare_no_cache: bool = False,
) -> dict:
    implementation_root = (implementation_root or repository_root()).resolve()
    source_root = source_root.resolve()
    corpus = corpus.resolve()
    session = ValidationSession(source_root, identity_roots=(corpus,))
    requested_inputs = {
        "queue": queue.resolve().as_posix(),
        "screen": screen.resolve().as_posix(),
        "audit": audit.resolve().as_posix(),
        "funnel": funnel.resolve().as_posix(),
        "corpus": corpus.as_posix(),
        "source_root": source_root.as_posix(),
    }
    operations = (
        (
            "QUEUE",
            validate_heldout_queue,
            (queue.resolve(), corpus, source_root),
        ),
        (
            "FEASIBILITY_SCREEN",
            validate_feasibility_screen,
            (screen.resolve(), corpus, source_root),
        ),
        (
            "PRESELECTION_CHAIN",
            validate_preselection_chain_audit,
            (audit.resolve(), corpus, source_root),
        ),
        (
            "CUMULATIVE_FUNNEL",
            validate_funnel,
            (funnel.resolve(), corpus, source_root),
        ),
    )

    def run(
        active_session: ValidationSession | None,
    ) -> tuple[list[dict], float, str | None]:
        stages = []
        total_start = time.perf_counter()
        try:
            for name, operation, arguments in operations:
                started = time.perf_counter()
                if active_session is None:
                    result = operation(*arguments)
                else:
                    result = operation(
                        *arguments, validation_session=active_session
                    )
                stages.append(
                    {
                        "name": name,
                        "status": result["status"],
                        "seconds": time.perf_counter() - started,
                    }
                )
        except Exception as error:  # Preserve a machine-readable fail-closed receipt.
            return (
                stages,
                time.perf_counter() - total_start,
                f"{type(error).__name__}: {error}",
            )
        return stages, time.perf_counter() - total_start, None

    stages, total_seconds, failure = run(session)
    script_names = (
        "community_window_validation.py",
        "community_validation_session.py",
        "community_evaluation.py",
        "community_discovery_funnel.py",
        "schema_utils.py",
    )
    implementation = [
        *(implementation_root / "scripts" / path for path in script_names),
        implementation_root / "schemas/community_window_validation.schema.json",
    ]
    try:
        input_identity = {
            "queue": identity(queue),
            "screen": identity(screen),
            "audit": identity(audit),
            "funnel": identity(funnel),
            "corpus_index": identity(corpus / "index.json"),
            "source_root": source_root.as_posix(),
        }
    except Exception as error:
        input_identity = None
        if failure is None:
            failure = f"{type(error).__name__}: {error}"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": (
            "CPU_VALIDATION_TIMING_NOT_GPU_OR_OPTIMIZATION_PERFORMANCE"
        ),
        "status": "FAIL" if failure is not None else "PASS",
        "requested_inputs": requested_inputs,
        "input_identity": input_identity,
        "validator_implementation": [identity(path) for path in implementation],
        "stages": stages,
        "total_seconds": total_seconds,
        "cache": session.statistics(),
        "error": failure,
        "limitations": [
            "Cache entries exist only in this process and are never persisted.",
            "Every cache hit rechecks the artifact and its reachable file-identity closure by SHA-256.",
            "Release evidence still requires an independent no-cache full replay.",
            "These are CPU validation times, not discovery, GPU, or optimization performance measurements.",
        ],
    }
    if compare_no_cache and failure is None:
        no_cache_stages, no_cache_seconds, no_cache_failure = run(None)
        report["no_cache_reference"] = {
            "status": "FAIL" if no_cache_failure is not None else "PASS",
            "stages": no_cache_stages,
            "total_seconds": no_cache_seconds,
            "session_speedup": (
                no_cache_seconds / total_seconds
                if no_cache_failure is None and total_seconds > 0
                else None
            ),
            "error": no_cache_failure,
        }
        if no_cache_failure is not None:
            report["status"] = "FAIL"
            report["error"] = "independent no-cache validation failed: " + no_cache_failure
    schema = json.loads(
        (implementation_root / "schemas/community_window_validation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = validate_instance(report, schema)
    if errors:
        raise ValueError("invalid window validation report: " + "; ".join(errors))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--funnel", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--compare-no-cache",
        action="store_true",
        help="also perform a separate full no-cache validation reference run",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_window(
        args.queue,
        args.screen,
        args.audit,
        args.funnel,
        args.corpus,
        args.source_root,
        compare_no_cache=args.compare_no_cache,
    )
    atomic_json(args.output.resolve(), report)
    print(args.output.resolve())
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
