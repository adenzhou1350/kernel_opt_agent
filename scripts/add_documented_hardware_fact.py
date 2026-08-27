#!/usr/bin/env python3
"""Add a hardware fact only when an exact vendor-official document supports it."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import archived_text, normalized_text, read_object, resolve_evidence_path, validate_hardware_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--fact-id", required=True)
    parser.add_argument("--scope", choices=("ARCHITECTURE", "DEVICE_MODEL", "TARGET_DEVICE"), required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--value-json", required=True)
    parser.add_argument("--unit")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--locator-kind", choices=("SECTION", "TABLE", "HTML_ANCHOR", "TEXT"), required=True)
    parser.add_argument("--locator", required=True)
    parser.add_argument("--support-text", required=True, help="Exact source text that supports this fact")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    path = args.manifest.resolve()
    data = read_object(path)
    source = next((item for item in data.get("sources", []) if item.get("source_id") == args.source_id), None)
    if source is None or source.get("authority") != "VENDOR_OFFICIAL_DOCUMENT":
        raise ValueError("documented hardware facts require a bound VENDOR_OFFICIAL_DOCUMENT")
    if any(item.get("fact_id") == args.fact_id for item in data.get("facts", [])):
        raise ValueError(f"duplicate fact_id: {args.fact_id}")
    artifact = resolve_evidence_path(path.parent, str(source.get("retrieval", {}).get("artifact_path", "")))
    if normalized_text(args.support_text) not in archived_text(artifact):
        raise ValueError("--support-text is not present in the bound official document")
    fact = {
        "fact_id": args.fact_id,
        "scope": args.scope,
        "field": args.field,
        "value": json.loads(args.value_json),
        "unit": args.unit,
        "evidence_class": "DOCUMENTED_FACT",
        "source_id": args.source_id,
        "locator": {
            "kind": args.locator_kind,
            "value": args.locator,
            "support_text": args.support_text,
            "support_text_sha256": hashlib.sha256(args.support_text.encode("utf-8")).hexdigest(),
        },
        "semantic_review": {
            "status": "APPROVED",
            "reviewer": args.reviewer,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "claim": f"{args.field}={args.value_json}",
        },
    }
    data.setdefault("facts", []).append(fact)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    errors = validate_hardware_evidence(path)
    if errors:
        raise ValueError("updated manifest failed validation: " + "; ".join(errors))
    print(json.dumps({"status": "PASS", "fact": fact}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
