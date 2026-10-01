"""Bounded, advisory reuse of curated lessons; never a qualification verdict."""

import json

import knowledge_notes

MAX_QUERY_CHARS = 1024
MAX_CARD_BYTES = 8192


def fit_lesson_context(packet, limit, prefix=""):
    """Optional advice must never displace supplied primary source evidence."""
    suggestion = packet.get("lesson_suggestions", {})
    if suggestion.get("status") == "NO_MATCH":
        packet.pop("lesson_suggestions", None)
        return
    size = len(
        (prefix + json.dumps(packet, ensure_ascii=False, sort_keys=True)).encode()
    )
    if size > limit:
        packet.pop("lesson_suggestions", None)


def lesson_suggestions(query, *, exclude=(), directory=None):
    """Add at most one intact related card, without copying private source paths.

    No card is an unconditional baseline. Match scores are lexical suggestions,
    not applicability, confidence or policy. Optional
    library errors must not stop discovery or turn into a defect verdict.
    """
    text = str(query).strip()
    result = {
        "matches": [],
        "caution": knowledge_notes.CAUTION,
        "query_truncated": len(text) > MAX_QUERY_CHARS,
        "oversized_matches_omitted": 0,
        "status": "NO_MATCH",
    }
    if not text:
        return result
    excluded = set(exclude)
    try:
        found = knowledge_notes.search(
            text[:MAX_QUERY_CHARS],
            directory=directory or knowledge_notes.DEFAULT_DIRECTORY,
            limit=16,
        )
    except (OSError, ValueError):
        result["status"] = "LIBRARY_UNAVAILABLE"
        return result
    for match in found["matches"]:
        card = match["card"]
        if card["id"] in excluded:
            continue
        if len(json.dumps(card, ensure_ascii=False).encode()) > MAX_CARD_BYTES:
            result["oversized_matches_omitted"] += 1
            continue
        result["matches"] = [card]
        result["status"] = "ADVISORY_MATCH"
        break
    return result
