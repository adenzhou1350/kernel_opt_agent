"""Deterministic source coverage order, not semantic deduplication or ranking."""

import hashlib
import re

SOURCE_ORDER_POLICY = "changed_blobs_family_round_robin_v2"
CHANGE_WINDOW_POLICY = "cached_changed_envelope_v1"


def audit_start_line(spec, path, window, *, plan=None):
    """Explicit per-file locations or the unchanged bounded prefix policy."""
    starts = spec.get("source_start_lines", {}).get(path)
    if starts is not None:
        return starts[window]
    return plan["starts"][window] if plan is not None else 1 + window * 120


def changed_envelope_windows(before, after, windows):
    """Reuse window slots for late cached-text boundaries, not a complete diff.

    Linear common-prefix/suffix comparison avoids quadratic diff work. Interior
    changes, deleted text, character-truncated windows and semantic reachability
    are not recovered. The caller must bind the two immutable source identities.
    """
    if type(windows) is not int or not 1 <= windows <= 32:
        raise ValueError("source windows must be 1..32")
    plan = {"policy": CHANGE_WINDOW_POLICY, "starts": [1 + i * 120 for i in range(windows)]}
    if not isinstance(before, str) or not isinstance(after, str):
        return {**plan, "selection": "CACHED_PAIR_UNAVAILABLE"}
    if (len(before) > 512 * 1024 or len(after) > 512 * 1024
            or "\x00" in before or "\x00" in after):
        return {**plan, "selection": "CACHED_PAIR_UNSUPPORTED"}
    try:
        old_bytes, new_bytes = before.encode("utf-8"), after.encode("utf-8")
    except UnicodeEncodeError:
        return {**plan, "selection": "CACHED_PAIR_UNSUPPORTED"}
    if max(len(old_bytes), len(new_bytes)) > 512 * 1024:
        return {**plan, "selection": "CACHED_PAIR_UNSUPPORTED"}
    old, new = before.splitlines(), after.splitlines()
    if old == new:
        return {**plan, "selection": "SAME_LOGICAL_LINES"}
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-1 - suffix] == new[-1 - suffix]:
        suffix += 1
    first, last = prefix + 1, len(new) - suffix
    plan.update(
        before_sha256=hashlib.sha256(old_bytes).hexdigest(),
        after_sha256=hashlib.sha256(new_bytes).hexdigest(),
        changed_new_start=first, changed_new_end=last,
        deletion_boundary=last < first,
    )
    if windows == 1 or not new:
        return {**plan, "selection": "PREFIX_ONLY_NO_SLOT" if new else "EMPTY_CURRENT"}
    targets = [first, last] if first <= last else [min(len(new), first)]
    starts = [1]
    for line in targets:
        if line <= windows * 120 or any(start <= line < start + 120 for start in starts):
            continue
        if len(starts) == windows:
            break
        starts.append(max(1, line - 30))
    selected = len(starts) > 1
    starts.extend(start for start in plan["starts"][1:] if start not in starts)
    plan.update(starts=starts[:windows], selection="CHANGED_ENVELOPE" if selected else "PREFIX_COVERS_BOUNDARIES")
    return plan


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
