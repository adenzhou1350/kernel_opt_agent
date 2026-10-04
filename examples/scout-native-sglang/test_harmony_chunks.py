"""Opt-in full-module Harmony streaming audit; no installed-package claim."""

import hashlib
import os
import re
import subprocess
import sys
import types

import pytest

repository = os.environ.get("HARMONY_AUDIT_GIT_ROOT")
revision = os.environ.get("HARMONY_AUDIT_REVISION")
if not repository or not revision:
    pytest.skip(
        "Set the reviewed Git root and revision explicitly", allow_module_level=True
    )

digests = {
    "35f3c96ff4794a4de15daf12caad371084a037ee": "630786e1acd69b98e6cd819a00711749a391a6059cb4fa5219093f8e9e47f821",
    "bb00fda98c3de8878ab80eed9198a361827fc64e": "5ccf9a157a2d9913e07716b1ebd6c0681ed1f0906819e4f5f4094c6da6e9c88b",
}
if not re.fullmatch(r"[0-9a-f]{40}", revision) or revision not in digests:
    raise ValueError("Review and bind the exact source before running a new revision")
path = "python/sglang/srt/parser/harmony_parser.py"
raw = subprocess.check_output(
    ["git", "-C", repository, "show", f"{revision}:{path}"], timeout=30
)
assert hashlib.sha256(raw).hexdigest() == digests[revision]
# Execute the complete actual module, not extracted methods or package stubs.
# This module has only stdlib imports; registration supports real dataclasses.
module = types.ModuleType(f"reviewed_harmony_{revision}")
sys.modules[module.__name__] = module
exec(compile(raw, f"{revision}:{path}", "exec"), module.__dict__)


def event_values(events):
    return [(e.event_type, e.content, e.raw_text) for e in events]


@pytest.mark.parametrize(
    "header",
    [
        "<|channel|>analysis to=browser.search",
        "<|start|>assistant to=python<|channel|>analysis",
        "<|start|>assistant<|channel|>analysis to=python",
    ],
)
def test_tool_call_split_and_coalesced_parity(header):
    body = ' {"query": "SGLang", "nested": {"items": [1,2]}} '
    text = header + "<|message|>" + body + "<|call|>"
    expected = [("tool_call", body.strip(), text)]
    plans = [
        [text],
        [header, "<|message|>", body[:14], body[14:], "<|call|>"],
        list(text),  # Defensive marker fragmentation, not a serving claim.
        *[[text[:i], text[i:]] for i in range(1, len(text))],
    ]
    mismatches = []
    for index, chunks in enumerate(plans):
        parser = module.HarmonyParser()
        actual = event_values([e for chunk in chunks for e in parser.parse(chunk)])
        if actual != expected:
            mismatches.append((index, actual))
    assert not mismatches, (
        f"{len(mismatches)}/{len(plans)} failures; first={mismatches[:1]}"
    )


def test_plain_reasoning_remains_incremental():
    parser = module.HarmonyParser()
    first = parser.parse("<|channel|>analysis<|message|>first ")
    second = parser.parse("second")
    assert event_values(first) == [("reasoning", "first ", None)]
    assert event_values(second) == [("reasoning", "second", None)]
