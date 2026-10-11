"""Offline provider usage normalization and model-attempt accounting.

Use messages_usage only for documented disjoint cache counters. OpenAI-style
prompt_tokens already includes cache reads: do not apply that sum to it.
Counts are observations, not dollars, comparable compute, or quality scores.
"""

import math
import re

COUNTERS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def messages_usage(usage):
    """Keep absent counters unknown; a returned zero is different from absence.

    MiniMax documents this composition at:
    https://platform.minimax.io/docs/api-reference/anthropic-api-compatible-cache
    Retain the original response alongside this derived view. This helper does
    not authenticate usage or reconstruct usage from a CLI's model text.
    """
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("usage must be an object or null")
    usage = usage or {}
    if any(key in usage for key in ("prompt_tokens", "completion_tokens")):
        raise ValueError("inclusive prompt-token accounting is not Messages accounting")
    counts = {}
    for name in COUNTERS:
        value = usage.get(name)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{name} must be a nonnegative integer or null")
        counts[name] = value
    input_counts = [counts[name] for name in COUNTERS[:3]]
    total_input = None if None in input_counts else sum(input_counts)
    output = counts["output_tokens"]
    return {
        **counts,
        "total_input_tokens": total_input,
        "total_tokens": (
            None if total_input is None or output is None else total_input + output
        ),
        "missing_counters": [name for name in COUNTERS if counts[name] is None],
    }


def summarize_token_attempts(attempts):
    """Offline per-arm accounting of independently identified model attempts.

    The caller supplies a provider-normalized inclusive total and explicitly
    distinguishes final usage from an interrupted stream's last observation.
    Include failed/invalid-answer attempts, not only accepted reviews. Selection
    calls belong to their selected arm; shared acquisition/setup is separate.
    This neither runs calls nor matches budgets, estimates prices or ranks arms.
    """
    if not isinstance(attempts, list) or len(attempts) > 4096:
        raise ValueError("expected at most 4096 attempt records")
    arms, seen = {}, set()
    fields = {"attempt_id", "arm", "total_tokens", "usage_final", "elapsed_seconds"}
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != fields:
            raise ValueError("invalid attempt fields")
        for name in ("attempt_id", "arm"):
            if (
                not isinstance(attempt[name], str)
                or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", attempt[name]) is None
            ):
                raise ValueError(f"invalid {name}")
        identity = attempt["attempt_id"]
        if identity in seen:
            raise ValueError("duplicate attempt_id; do not count shared calls twice")
        seen.add(identity)
        tokens, final = attempt["total_tokens"], attempt["usage_final"]
        elapsed = attempt["elapsed_seconds"]
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError("total_tokens must be a nonnegative integer or null")
        if type(final) is not bool or (final and tokens is None):
            raise ValueError("final usage requires observed total_tokens")
        if elapsed is not None and (
            type(elapsed) not in (int, float)
            or elapsed > 1_000_000_000
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError("elapsed_seconds must be within 0..1e9 or null")
        arm = arms.setdefault(
            attempt["arm"],
            {
                "attempts": 0,
                "final_usage_attempts": 0,
                "partial_usage_attempts": 0,
                "missing_usage_attempts": 0,
                "observed_token_sum": 0,
                "final_token_total": None,
                "observed_call_seconds_sum": 0.0,
                "missing_elapsed_attempts": 0,
                "call_seconds_total": None,
            },
        )
        arm["attempts"] += 1
        if tokens is None:
            arm["missing_usage_attempts"] += 1
        else:
            arm["observed_token_sum"] += tokens
            arm["final_usage_attempts" if final else "partial_usage_attempts"] += 1
        if elapsed is None:
            arm["missing_elapsed_attempts"] += 1
        else:
            arm["observed_call_seconds_sum"] += elapsed
    for arm in arms.values():
        if arm["final_usage_attempts"] == arm["attempts"]:
            arm["final_token_total"] = arm["observed_token_sum"]
        if not arm["missing_elapsed_attempts"]:
            arm["call_seconds_total"] = arm["observed_call_seconds_sum"]
    return arms
