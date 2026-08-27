#!/usr/bin/env python3
"""Restricted, auditable result-to-model transformations."""

from __future__ import annotations

import copy


def pointer_tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {pointer!r}")
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]


def pointer_get(data, pointer: str):
    current = data
    for token in pointer_tokens(pointer):
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def pointer_set(data, pointer: str, value) -> None:
    tokens = pointer_tokens(pointer)
    current = data
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]
    final = tokens[-1]
    if isinstance(current, list):
        current[int(final)] = value
    else:
        if final not in current:
            raise KeyError(f"model update target must already exist: {pointer}")
        current[final] = value


def evaluate_calculation(calculation: dict, result: dict):
    op = calculation.get("op")
    source = pointer_get(result, str(calculation.get("result_pointer", "")))
    if op == "COPY_RESULT":
        return copy.deepcopy(source)
    if op == "AFFINE_RESULT":
        return float(source) * float(calculation["scale"]) + float(calculation.get("offset", 0.0))
    if op == "COMPARE_RESULT":
        comparator = calculation.get("comparator")
        threshold = float(calculation["threshold"])
        value = float(source)
        if comparator == "LE":
            return value <= threshold
        if comparator == "LT":
            return value < threshold
        if comparator == "GE":
            return value >= threshold
        if comparator == "GT":
            return value > threshold
        raise ValueError(f"unsupported comparison {comparator!r}")
    raise ValueError(f"unsupported model calculation {op!r}")
