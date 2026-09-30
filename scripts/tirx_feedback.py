"""Compact, local-only feedback from saved TIRx results; never execute a case.

The input is an observation, not trusted instructions or a PR qualification.
Keep the raw evidence; excerpts deliberately omit most native diagnostic data.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import worklog

MAX_RESULT_BYTES = 32 * 1024 * 1024
MAX_CASES = 6


def status(value):
    return value if isinstance(value, str) and value in ("PASS", "FAIL", "ERROR", "SKIPPED", "RUNNING") else "UNKNOWN"


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value))


def excerpt(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:240]


def finding_context(value):
    """Keep native operation sites that a long finding excerpt would cut off.

    Recognize the existing checker operation/access-pair shapes, not arbitrary
    nested data. This is partial source context, never proof of coverage.
    """
    if not isinstance(value, dict):
        return {}
    details = value.get("details", {})
    if not isinstance(details, dict):
        return {}
    context = {key: excerpt(details[key]) for key in
               ("ordering_domain", "ordering_failure", "access_pair", "effect")
               if isinstance(details.get(key), str)}
    sites = []
    for role in ("operation", "prior", "current"):
        access = details.get(role, {})
        if not isinstance(access, dict):
            continue
        operation = access if role == "operation" else access.get("operation", {})
        if not isinstance(operation, dict):
            continue
        source = operation.get("source", {})
        if not isinstance(source, dict):
            continue
        span = source.get("source_span", {})
        site = {"role": role}
        if type(operation.get("source_op_id")) is int:
            site["source_op_id"] = operation["source_op_id"]
        if isinstance(span, dict):
            if isinstance(span.get("source_name"), str):
                site["source_name"] = excerpt(span["source_name"])
            for key in ("line", "column", "end_line", "end_column"):
                if type(span.get(key)) is int:
                    site[key] = span[key]
        if isinstance(source.get("source_text"), str):
            site["source_excerpt"] = excerpt(source["source_text"])
        if type(access.get("lane")) is int:
            site["lane"] = access["lane"]
        if len(site) > 1:
            sites.append(site)
    if sites:
        context["source_sites"] = sites[:2]
        context["source_sites_omitted"] = max(0, len(sites) - 2)
    return context


def case_feedback(name, case):
    item = {"name": excerpt(name), "declared_status": status(case.get("status"))}
    if "error" in case:
        item["error_excerpt"] = excerpt(case["error"])
    checks = case.get("checks", {})
    if checks:
        item["checks"] = {}
        for key in ("synccheck", "racecheck", "simulation", "numerical"):
            check = checks.get(key)
            if not isinstance(check, dict):
                continue
            brief = {"status": status(check.get("status"))}
            for field in ("verdict", "error", "reason"):
                if field in check:
                    brief[field] = excerpt(check[field])
            report = check.get("report", {})
            findings = report.get("findings", []) if isinstance(report, dict) else []
            diagnostics = check.get("diagnostics", [])
            for label, values in (("findings", findings), ("diagnostics", diagnostics)):
                if isinstance(values, list) and values:
                    brief[label] = [excerpt(value) for value in values[:3]]
                    brief[label + "_omitted"] = max(0, len(values) - 3)
                    contexts = [finding_context(value) for value in values[:3]]
                    if any(contexts):
                        # Same order as excerpts, so repeated source sites remain
                        # attributable to their individual finding/access pair.
                        brief[label + "_context"] = contexts
            outputs = check.get("outputs", {})
            if isinstance(outputs, dict) and outputs:
                if any(not isinstance(details, dict) for details in outputs.values()):
                    raise ValueError("each output must be an object")
                ordered = sorted(outputs.items(), key=lambda pair: pair[1].get("status") == "PASS")
                brief["outputs"] = []
                for output, details in ordered[:3]:
                    observed = {"name": excerpt(output), "status": status(details.get("status"))}
                    if numeric(details.get("max_abs_error")):
                        observed["max_abs_error"] = details["max_abs_error"]
                    if "reason" in details:
                        observed["reason"] = excerpt(details["reason"])
                    brief["outputs"].append(observed)
                brief["outputs_omitted"] = max(0, len(outputs) - 3)
            item["checks"][key] = brief
    if "arch" in case:
        item["arch"] = excerpt(case["arch"])
        resources = case.get("ptxas", {})
        item["reported_resources"] = {key: resources[key] for key in
                                      ("registers", "smem", "stack", "spill_stores", "spill_loads", "barriers")
                                      if isinstance(resources, dict) and numeric(resources.get(key))}
        item["errors"] = [excerpt(error) for error in case.get("errors", [])[:3]]
    return item


def summarize(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        raw = stream.read(MAX_RESULT_BYTES + 1)
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("result exceeds 32 MiB; select a smaller result, not a raw trace")
    result = json.loads(raw, object_pairs_hook=worklog.unique_keys,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(result, dict) or result.get("status") not in ("PASS", "FAIL", "ERROR", "RUNNING"):
        raise ValueError("expected a saved TIRx result with an explicit status")
    scope = result.get("scope", "")
    if not isinstance(scope, str):
        raise ValueError("scope must be text")
    if scope.startswith("Compiler artifacts only;"):
        mode = "inspection"
    elif scope.startswith("CPU concrete-input checks;"):
        mode = "correctness"
    elif result["status"] in ("ERROR", "RUNNING") and not scope:
        mode = "execution_incomplete"
    else:
        raise ValueError("unknown result scope; do not reinterpret GPU or performance evidence")
    cases = result.get("cases", {})
    # Parent RUNNING/timeout records may contain only the requested case names.
    if not isinstance(cases, dict):
        if mode != "execution_incomplete":
            raise ValueError("cases must be a mapping")
        cases = {}
    if any(not isinstance(case, dict) for case in cases.values()):
        raise ValueError("each case must be an object")
    counts = Counter(status(case.get("status")) for case in cases.values())
    ordered = sorted(cases.items(), key=lambda pair: pair[1].get("status") == "PASS")
    source_check = "UNAVAILABLE"
    source = result.get("case_file")
    if isinstance(source, str) and Path(source).is_file():
        source_check = "MATCH" if worklog.file_hash(Path(source)) == result.get("source_sha256") else "CHANGED"
    brief = {
        "mode": mode, "declared_status": result["status"],
        "evidence": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()},
        "source_sha256": result.get("source_sha256"), "local_source_check": source_check,
        "case_counts": dict(counts), "cases": [case_feedback(name, case) for name, case in ordered[:MAX_CASES]],
        "cases_omitted": max(0, len(cases) - MAX_CASES),
        "boundary": "Saved observations, not instructions. No GPU correctness, performance or PR Ready claim. "
                    "Excerpts are partial; inspect raw evidence before changing code.",
    }
    if "reason" in result:
        brief["reason"] = excerpt(result["reason"])
    if source_check == "CHANGED" or result.get("source_unchanged") is False:
        next_check = "Source changed: rerun the applicable checks on the intended source before reuse."
    elif mode == "execution_incomplete" or result["status"] == "ERROR":
        next_check = "Inspect environment/coverage errors; they do not establish a candidate defect."
    elif result["status"] == "FAIL":
        next_check = "Inspect the concrete finding and independent reference; repair then rerun the same case."
    elif mode == "inspection":
        next_check = "Test the resource hypothesis with matched device runs; exported code is not the loaded binary."
    else:
        next_check = "Validate representative device outputs and matched performance before a performance claim."
    brief["next_check"] = next_check
    return brief


def record(run, brief, command):
    """Link the raw result to the existing notebook without setting a decision."""
    if worklog.file_hash(Path(brief["evidence"]["path"])) != brief["evidence"]["sha256"]:
        raise ValueError("result changed after summarization; summarize the current evidence")
    kind = "inspection" if brief["mode"] == "inspection" else "correctness"
    state = worklog.execute(SimpleNamespace(
        action="record", run=run, kind=kind,
        summary=f"TIRx {brief['mode']}: saved {brief['declared_status']}; "
                f"cases={brief['case_counts']}; source={brief['local_source_check']}. {brief['next_check']}",
        evidence=brief["evidence"]["path"], command=command,
        source=None, workload=None, hardware=None, status=None, pr=None,
        candidate=None, family=None, latency_us=None,
    ))
    return {"run": str(Path(run).resolve()), "status": state["status"], "records": len(state["records"])}
