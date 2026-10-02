"""Resolve review citations against displayed evidence, without judging claims.

This optional experiment helper performs no fetch, model call or source execution.
Excerpt rows are one-based display positions, not original repository line numbers.
A valid citation locates supplied text; it does not prove the explanation is true.
"""

import hashlib
import json

DECISIONS = frozenset(("STOP_REFUTED", "SUPPORTED_STATIC_DEFECT", "INSUFFICIENT"))


def citation_view(sources):
    """Preserve bounded displayed excerpts and assign unambiguous local IDs."""
    if not isinstance(sources, list) or len(sources) > 25:
        raise ValueError("invalid bounded sources")
    result, total = [], 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError("invalid source")
        url, text = source.get("url"), source.get("text")
        if (
            not isinstance(url, str)
            or not 0 < len(url) <= 2048
            or not isinstance(text, str)
            or len(text) > 10000
        ):
            raise ValueError("invalid displayed excerpt")
        total += len(text)
        if total > 20000:
            raise ValueError("displayed text budget exceeded")
        # Avoid splitlines: Unicode line separators can occur inside literals.
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        rows = normalized.split("\n") if text else []
        result.append(
            {
                "evidence_id": f"s{index}",
                "url": url,
                "rows": rows,
                "display_sha256": hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest(),
                "scope": (
                    "Rows index this displayed excerpt, not original file lines; "
                    "text may be clipped."
                ),
            }
        )
    return result


def numbered_citation_view(sources):
    """Render explicit row labels for the model; resolve against citation_view.

    Numbered rows distinguish excerpt positions from embedded file-line prefixes.
    This changes presentation only, not evidence selection or semantic judgment.
    """
    return [
        {
            **source,
            "rows": [
                {"row": number, "text": text}
                for number, text in enumerate(source["rows"], 1)
            ],
        }
        for source in citation_view(sources)
    ]


def resolve_review(text, displayed):
    """Accept exact row references and extract their text, never repair guesses.

    This checks the output interface and supplied spans only. Separate owner
    adjudication must assess producer/consumer contracts and the decisive reason.
    """

    def fail(error):
        return {"valid": False, "error": error}

    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return fail("INVALID_JSON")
    if not isinstance(value, dict) or set(value) != {
        "decision",
        "reason",
        "citations",
        "next_verification",
    }:
        return fail("INVALID_FIELDS")
    if not isinstance(value["decision"], str) or value["decision"] not in DECISIONS:
        return fail("INVALID_DECISION")
    for key, limit in (("reason", 600), ("next_verification", 500)):
        if not isinstance(value[key], str) or not 0 < len(value[key].strip()) <= limit:
            return fail("INVALID_EXPLANATION")
    refs = value["citations"]
    if not isinstance(refs, list) or len(refs) > 2:
        return fail("INVALID_CITATION_COUNT")
    if value["decision"] != "INSUFFICIENT" and not refs:
        return fail("DECISIVE_WITHOUT_CITATION")
    quotes, seen = [], set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {
            "evidence_id",
            "first_row",
            "last_row",
        }:
            return fail("INVALID_CITATION")
        first, last = ref["first_row"], ref["last_row"]
        if type(first) is not int or type(last) is not int or not 1 <= first <= last:
            return fail("INVALID_ROWS")
        if not isinstance(ref["evidence_id"], str):
            return fail("INVALID_EVIDENCE_ID")
        matches = [s for s in displayed if s["evidence_id"] == ref["evidence_id"]]
        if len(matches) != 1:
            return fail("UNKNOWN_OR_AMBIGUOUS_EVIDENCE")
        source = matches[0]
        if last > len(source["rows"]) or last - first + 1 > 8:
            return fail("ROWS_OUTSIDE_BUDGET")
        quote = "\n".join(source["rows"][first - 1 : last])
        if not quote.strip() or len(quote) > 1400:
            return fail("EMPTY_OR_OVERSIZE_CITATION")
        identity = (ref["evidence_id"], first, last)
        if identity in seen:
            return fail("DUPLICATE_CITATION")
        seen.add(identity)
        quotes.append(
            {
                **ref,
                "url": source["url"],
                "quote": quote,
                "display_sha256": source["display_sha256"],
            }
        )
    return {"valid": True, "parsed": value, "resolved_citations": quotes}
