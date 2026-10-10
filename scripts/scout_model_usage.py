"""Offline token accounting for Messages API's disjoint cache counters.

Use only for a provider documented to use this convention. OpenAI-style
prompt_tokens already includes cache reads: do not apply this sum to it.
Counts are observations, not dollars, comparable compute, or quality scores.
"""


COUNTERS = (
    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
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
