#!/usr/bin/env python3
"""Build a hash-bound, fail-closed pull-request evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from schema_utils import validate_instance, validate_json_file

SPEC_SCHEMA = "upstream-candidate-spec-v1"
PACKAGE_SCHEMA = "upstream-candidate-package-v1"
REQUIRED_EVIDENCE_ROLES = {
    "CORRECTNESS",
    "WHOLE_MODEL_PERFORMANCE",
    "REPRODUCTION",
}
REQUIRED_GATES = {
    "correctness",
    "source_review",
    "whole_model_performance",
    "upstream_checks",
    "cross_hardware",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def run_git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def resolve_evidence(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"evidence path must be a safe relative path: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(
            f"evidence path escapes the evidence root: {relative}"
        ) from error
    if not resolved.is_file():
        raise ValueError(f"evidence file is missing: {relative}")
    return resolved


def validate_spec(spec_path: Path, root: Path) -> dict:
    repository_root = Path(__file__).resolve().parents[1]
    schema_path = repository_root / "schemas/upstream_candidate_spec.schema.json"
    receipt_schema = read_object(
        repository_root / "schemas/upstream_evidence_receipt.schema.json"
    )
    errors = validate_json_file(spec_path, schema_path)
    if errors:
        raise ValueError("invalid upstream candidate spec: " + "; ".join(errors))
    spec = read_object(spec_path)
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise ValueError("unsupported upstream candidate spec schema")

    roles = {item["role"] for item in spec["evidence"]}
    missing_roles = sorted(REQUIRED_EVIDENCE_ROLES - roles)
    if missing_roles:
        raise ValueError(f"missing required evidence roles: {missing_roles}")

    evidence_by_path: dict[str, dict] = {}
    for item in spec["evidence"]:
        if item["path"] in evidence_by_path:
            raise ValueError(f"duplicate evidence path: {item['path']}")
        path = resolve_evidence(root, item["path"])
        actual = digest(path)
        if actual != item["sha256"]:
            raise ValueError(
                f"stale evidence hash for {item['path']}: expected {item['sha256']}, got {actual}"
            )
        receipt = read_object(path)
        receipt_errors = validate_instance(receipt, receipt_schema)
        if receipt_errors:
            raise ValueError(
                f"invalid evidence receipt {item['path']}: " + "; ".join(receipt_errors)
            )
        if receipt["role"] != item["role"]:
            raise ValueError(
                f"evidence role mismatch for {item['path']}: "
                f"spec={item['role']} receipt={receipt['role']}"
            )
        if receipt["status"] != "PASS":
            raise ValueError(f"evidence receipt is not PASS: {item['path']}")
        if receipt["candidate_commit"] != spec["repository"]["candidate_commit"]:
            raise ValueError(
                f"evidence receipt targets a stale candidate: {item['path']}"
            )
        for artifact in receipt["artifacts"]:
            artifact_path = resolve_evidence(root, artifact["path"])
            artifact_digest = digest(artifact_path)
            if artifact_digest != artifact["sha256"]:
                raise ValueError(
                    f"stale receipt artifact {artifact['path']}: "
                    f"expected {artifact['sha256']}, got {artifact_digest}"
                )
        evidence_by_path[item["path"]] = item

    gate_names = {item["name"] for item in spec["gates"]}
    if gate_names != REQUIRED_GATES:
        raise ValueError(
            f"gates must contain exactly {sorted(REQUIRED_GATES)}, got {sorted(gate_names)}"
        )
    failed = sorted(item["name"] for item in spec["gates"] if item["status"] == "FAIL")
    if failed:
        raise ValueError(
            f"failed qualification gates cannot produce a PR package: {failed}"
        )
    failed_tests = [
        item["command"] for item in spec["tests"] if item["status"] != "PASS"
    ]
    if failed_tests:
        raise ValueError(f"non-PASS tests cannot produce a PR package: {failed_tests}")
    for test in spec["tests"]:
        evidence = evidence_by_path.get(test["evidence_path"])
        if evidence is None:
            raise ValueError(
                f"test references undeclared evidence: {test['evidence_path']}"
            )
        if evidence["role"] not in {"CORRECTNESS", "UPSTREAM_CHECKS"}:
            raise ValueError(
                f"test evidence must be CORRECTNESS or UPSTREAM_CHECKS: {test['evidence_path']}"
            )
    gate_by_name = {item["name"]: item for item in spec["gates"]}
    if (
        gate_by_name["upstream_checks"]["status"] == "PASS"
        and "UPSTREAM_CHECKS" not in roles
    ):
        raise ValueError(
            "a PASS upstream_checks gate requires UPSTREAM_CHECKS evidence"
        )
    if (
        gate_by_name["cross_hardware"]["status"] == "PASS"
        and "CROSS_HARDWARE" not in roles
    ):
        raise ValueError("a PASS cross_hardware gate requires CROSS_HARDWARE evidence")

    whole_model_claims = 0
    for claim in spec["benchmark_claims"]:
        evidence = evidence_by_path.get(claim["evidence_path"])
        if evidence is None:
            raise ValueError(
                f"benchmark claim references undeclared evidence: {claim['evidence_path']}"
            )
        expected_role = (
            "WHOLE_MODEL_PERFORMANCE"
            if claim["scope"] == "WHOLE_MODEL"
            else "OPERATOR_PERFORMANCE"
        )
        if evidence["role"] != expected_role:
            raise ValueError(
                f"{claim['metric']} requires {expected_role} evidence, got {evidence['role']}"
            )
        computed = (
            claim["candidate"] / claim["baseline"]
            if claim["direction"] == "HIGHER_IS_BETTER"
            else claim["baseline"] / claim["candidate"]
        )
        if not math.isclose(computed, claim["speedup"], rel_tol=1e-6, abs_tol=1e-9):
            raise ValueError(
                f"speedup for {claim['metric']} is not recomputable: "
                f"declared {claim['speedup']}, computed {computed}"
            )
        if claim["scope"] == "WHOLE_MODEL":
            whole_model_claims += 1
            if computed <= 1.0:
                raise ValueError(
                    "whole-model evidence must show a positive improvement"
                )
    if whole_model_claims == 0:
        raise ValueError("at least one whole-model benchmark claim is required")
    return spec


def validate_repository(repository: Path, spec: dict) -> dict:
    if not (repository / ".git").exists() and not run_git(
        repository, "rev-parse", "--git-dir"
    ):
        raise ValueError(f"not a git repository: {repository}")
    base = spec["repository"]["base_commit"]
    candidate = spec["repository"]["candidate_commit"]
    for revision in (base, candidate):
        run_git(repository, "cat-file", "-e", f"{revision}^{{commit}}")
    ancestor = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor", base, candidate],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("base_commit is not an ancestor of candidate_commit")
    head = run_git(repository, "rev-parse", "HEAD")
    if head != candidate:
        raise ValueError(
            f"repository HEAD {head} does not match candidate_commit {candidate}"
        )
    porcelain = run_git(repository, "status", "--porcelain")
    if porcelain:
        raise ValueError("repository must be clean before packaging")
    patch = subprocess.run(
        ["git", "-C", str(repository), "diff", "--binary", base, candidate],
        capture_output=True,
        check=False,
    )
    if patch.returncode:
        raise ValueError(
            f"failed to materialize candidate diff: {patch.stderr.decode(errors='replace')}"
        )
    if not patch.stdout:
        raise ValueError("candidate diff is empty")
    return {
        "head": head,
        "clean": True,
        "patch": patch.stdout,
        "patch_sha256": digest_bytes(patch.stdout),
    }


def render_markdown(spec: dict, status: str, patch_sha256: str) -> str:
    repo = spec["repository"]
    lines = [
        f"# {repo['title']}",
        "",
        f"> Package status: `{status}`. Candidate `{repo['candidate_commit']}`; patch SHA-256 `{patch_sha256}`.",
        "",
        "## Motivation",
        "",
        spec["motivation"],
        "",
        "## Modifications",
        "",
    ]
    lines.extend(f"- {item}" for item in spec["modifications"])
    lines.extend(("", "## Accuracy Tests", ""))
    lines.append(spec["accuracy_summary"])
    lines.append("")
    lines.extend(f"- `{item['command']}` — {item['status']}" for item in spec["tests"])
    lines.extend(("", "## Speed Tests and Profiling", ""))
    lines.append("| Scope | Workload | Metric | Baseline | Candidate | Speedup |")
    lines.append("|---|---|---|---:|---:|---:|")
    for claim in spec["benchmark_claims"]:
        lines.append(
            f"| {claim['scope']} | {claim['workload']} | {claim['metric']} "
            f"| {claim['baseline']:.6g} {claim['unit']} "
            f"| {claim['candidate']:.6g} {claim['unit']} | {claim['speedup']:.4f}x |"
        )
    lines.extend(("", "## Boundaries", ""))
    lines.extend(f"- {item}" for item in spec["boundaries"])
    lines.extend(("", "## Qualification Gates", ""))
    lines.extend(
        f"- `{item['name']}`: **{item['status']}** — {item['rationale']}"
        for item in spec["gates"]
    )
    lines.append("")
    return "\n".join(lines)


def command_build(args: argparse.Namespace) -> dict:
    spec_path = args.spec.resolve()
    evidence_root = args.evidence_root.resolve()
    repository = args.repository.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    spec = validate_spec(spec_path, evidence_root)
    repository_receipt = validate_repository(repository, spec)
    pending = sorted(
        item["name"] for item in spec["gates"] if item["status"] == "PENDING"
    )
    status = "UPSTREAM_READY" if not pending else "DRAFT_PENDING_QUALIFICATION"

    manifest = {
        "schema_version": PACKAGE_SCHEMA,
        "package_id": spec["package_id"],
        "generated_at": now(),
        "status": status,
        "pending_gates": pending,
        "repository": spec["repository"],
        "source": {
            "repository_head": repository_receipt["head"],
            "repository_clean": repository_receipt["clean"],
            "patch": {
                "path": "changes.patch",
                "sha256": repository_receipt["patch_sha256"],
            },
        },
        "evidence": spec["evidence"],
        "tests": spec["tests"],
        "benchmark_claims": spec["benchmark_claims"],
        "boundaries": spec["boundaries"],
        "gates": spec["gates"],
        "claims_allowed": (
            ["open a non-draft upstream pull request with the bounded claims in PR.md"]
            if status == "UPSTREAM_READY"
            else [
                "open a draft pull request",
                "request review of correctness and benchmark design",
            ]
        ),
        "claims_forbidden": (
            []
            if status == "UPSTREAM_READY"
            else [
                "upstream-ready",
                "portable performance improvement",
                "cross-hardware speedup",
            ]
        ),
    }
    root = Path(__file__).resolve().parents[1]
    manifest_errors = validate_instance(
        manifest,
        read_object(root / "schemas/upstream_candidate_package.schema.json"),
    )
    if manifest_errors:
        raise ValueError("invalid generated package: " + "; ".join(manifest_errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        (temporary / "changes.patch").write_bytes(repository_receipt["patch"])
        (temporary / "PR.md").write_text(
            render_markdown(spec, status, repository_receipt["patch_sha256"]),
            encoding="utf-8",
        )
        (temporary / "manifest.json").write_bytes(canonical_json(manifest))
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "package_id": spec["package_id"],
        "status": status,
        "pending_gates": pending,
        "output": str(output),
        "manifest_sha256": digest(output / "manifest.json"),
        "pr_body_sha256": digest(output / "PR.md"),
        "patch_sha256": repository_receipt["patch_sha256"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    build = subparsers.add_parser("build", help="build an immutable upstream package")
    build.add_argument("--spec", type=Path, required=True)
    build.add_argument("--evidence-root", type=Path, required=True)
    build.add_argument("--repository", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = command_build(args)
    except (OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
