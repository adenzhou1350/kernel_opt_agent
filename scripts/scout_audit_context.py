"""Bounded overlapping context for tiny source-discovery tails, not a verdict."""


def contextual_audit_tail(context, repo, commit, path, source):
    """Retain every original numbered EOF line when adding preceding context.

    Discovery may overlap; explicit follow-up selectors must not use this.
    Keep the original on clipping or optional source-budget failure. The
    source provider is responsible for immutable cache and URL validation.
    """
    start, end, total = (
        source.get("start_line"), source.get("end_line"), source.get("total_lines")
    )
    if not (
        all(type(value) is int for value in (start, end, total))
        and 1 < start <= end == total
        and end - start + 1 < 24
        and source.get("text")
    ):
        return source
    try:
        expanded = context.source(
            repo, commit, path, start=max(1, total - 119), max_lines=120
        )
    except ValueError as exc:
        if str(exc) not in {
            "binary source is not supported", "source exceeds read budget",
            "public source exceeds read budget",
        }:
            raise
        return source
    if (
        expanded.get("url") == source.get("url")
        and expanded.get("total_lines") == total
        and expanded.get("end_line") == end
        and expanded.get("start_line", start) < start
        and expanded.get("text", "").endswith(source["text"])
    ):
        return expanded
    return source
