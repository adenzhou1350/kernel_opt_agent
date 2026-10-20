"""Deterministic source coverage order, not semantic deduplication or ranking."""

import re

SOURCE_ORDER_POLICY = "changed_blobs_family_round_robin_v2"


def audit_start_line(spec, path, window):
    """Explicit per-file locations or the unchanged bounded prefix policy."""
    starts = spec.get("source_start_lines", {}).get(path)
    return starts[window] if starts is not None else 1 + window * 120


def family_round_robin(paths):
    """Keep every variant; interleave naming families within a bounded prefix."""
    families = {}
    for path in paths:
        family = re.sub(r"_[0-9a-f]{20}(?=_(?:kernel|binding)\.cu$)", "_<hash20>", path)
        families.setdefault(family, []).append(path)
    result = []
    depth = 0
    while families:
        active = {}
        for family, members in families.items():
            result.append(members[depth])
            if len(members) > depth + 1:
                active[family] = members
        families = active
        depth += 1
    return result


def changed_first_paths(paths, current_blobs, previous_blobs, limit=512):
    """Prefer changed blobs, without filling the prefix with one naming family."""
    changed = family_round_robin(
        [path for path in paths if current_blobs[path] != previous_blobs.get(path)]
    )[:limit]
    changed_set = set(changed)
    return changed + [path for path in paths if path not in changed_set], changed


def reset_legacy_cursor(paths, cursor, priority):
    """An integer cursor must never resume at another path after reordering.

    Seen keys are authoritative, so a rewind does not repeat admitted packets.
    Keep an alphabetical legacy cursor when the actual order is unchanged.
    Versioned priorities handle their own commit/scope/policy migration.
    """
    return bool(cursor and not priority and family_round_robin(paths) != paths)
