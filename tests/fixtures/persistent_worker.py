#!/usr/bin/env python3
"""Deterministic NDJSON worker for persistent-session runner tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time


def emit(value: dict) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-identity", required=True)
    parser.add_argument("--switching", action="store_true")
    args = parser.parse_args()
    emit(
        {
            "event": "ready",
            "protocol": "persistent-session-v1",
            "session_identity": args.session_identity,
            "switching_supported": args.switching,
            "engine_init_count": 1,
        }
    )
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("event") == "shutdown":
            return 0
        payload = request["payload"]
        if payload.get("sleep_seconds"):
            time.sleep(float(payload["sleep_seconds"]))
        treatment_identity = payload.get(
            "returned_treatment_identity", request["treatment_identity"]
        )
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        emit(
            {
                "event": "result",
                "request_id": request["request_id"],
                "treatment_identity": treatment_identity,
                "output_digest": digest,
                "measurement": {"value": payload.get("value")},
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
