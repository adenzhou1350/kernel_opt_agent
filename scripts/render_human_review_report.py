#!/usr/bin/env python3
"""Render a validated human-review report as one self-contained Chinese HTML file."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "templates/human_review_report/index.template.html",
    )
    args = parser.parse_args()
    validator = Path(__file__).with_name("validate_human_review_report.py")
    validation = subprocess.run(
        [sys.executable, str(validator), str(args.report)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if validation.returncode:
        print(validation.stdout, end="")
        print(validation.stderr, end="", file=sys.stderr)
        return validation.returncode
    report = json.loads(args.report.read_text())
    template = args.template.read_text()
    if "__REPORT_DATA__" not in template or "__REPORT_TITLE__" not in template:
        raise SystemExit("template is missing a required placeholder")
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    rendered = template.replace("__REPORT_TITLE__", html.escape(report["title"])).replace(
        "__REPORT_DATA__", payload
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)
    print(json.dumps({"status": "PASS", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
