"""Optional deterministic tail strata; not a relevance or quality predictor."""


def tail_window_starts(total_lines, prefix_limit_lines, *, max_windows=3, width=120):
    """Sample grid-aligned unseen tail windows without raising per-task context.

    The caller verifies the prefix cutoff and exact file identity, checks dedup,
    and records actual delivered bounds. A prefix budget does not prove that
    every prefix line was delivered/read, or that a followup never read a tail.
    This does not establish complete coverage, fresh commits, higher yield or
    that a window contains whole symbols.
    """
    if (type(total_lines) is not int or not 0 <= total_lines <= 1_000_000
            or type(prefix_limit_lines) is not int or prefix_limit_lines < 0
            or type(max_windows) is not int or not 1 <= max_windows <= 8
            or type(width) is not int or not 1 <= width <= 160):
        raise ValueError('invalid source frontier bounds')
    starts = range(prefix_limit_lines+1, total_lines+1, width)
    if len(starts) <= max_windows:
        return list(starts)
    if max_windows == 1:
        return [starts[0]]
    return [starts[i*(len(starts)-1)//(max_windows-1)] for i in range(max_windows)]
