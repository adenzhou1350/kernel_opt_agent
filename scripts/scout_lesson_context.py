"""Bounded, advisory reuse of curated lessons; never a qualification verdict."""

import json
import re

import knowledge_notes

MAX_QUERY_CHARS = 1024
MAX_CARD_BYTES = 8192
MAX_SOURCE_CHARS = 24000


def source_api_query(source_text):
    """Bounded lexical import/use anchors, not parsing or applicability proof.

    Do not fetch more code. Comments/strings can match; missing imports and
    unrecognized package names fall back to the task question.
    """
    source = str(source_text)[:MAX_SOURCE_CHARS]
    aliases = set()
    for module, alias in re.findall(
        r"(?m)^\s*(?:\d+:\s*)?import\s+([A-Za-z_][\w.]*)(?:\s+as\s+(\w+))?", source
    ):
        aliases.add(alias or module.split(".")[0])
    for imported in re.findall(
        r"(?m)^\s*(?:\d+:\s*)?from\s+[\w.]+\s+import\s+([^\n#]+)", source
    ):
        for name in imported.split(","):
            match = re.fullmatch(r"\s*(\w+)(?:\s+as\s+(\w+))?\s*", name)
            if match:
                aliases.add(match.group(2) or match.group(1))
    aliases.update(re.findall(r"\bimport\s+\*\s+as\s+(\w+)\s+from\b", source))
    # Constant dynamic imports only. These are lexical hints, never eval/JS execution.
    assignment = (
        r"(?m)^\s*(?:\d+:\s*)?(?:(?:const|let|var)\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*(?:await\s+)?"
    )
    module = r"[@A-Za-z0-9_./-]+"
    js_imports = [
        (alias, package)
        for alias, _, package in re.findall(
            assignment + r"import\s*\(\s*(['\"])(" + module
            + r")\2\s*\)\s*(?:;|$)", source
        )
    ]
    js_imports.extend(
        (alias, double_quoted or single_quoted)
        for alias, double_quoted, single_quoted in re.findall(
            assignment + r"eval\s*\(\s*(?:'import\(\"(" + module
            + r")\"\)'|\"import\('(" + module + r")'\)\")\s*\)\s*(?:;|$)", source
        )
    )
    js_namespaces = {
        alias: package.rsplit("/", 1)[-1] for alias, package in js_imports
    }
    aliases.update(js_namespaces)
    go_imports = re.findall(
        r'(?m)^\s*(?:\d+:\s*)?import\s+(?:(\w+|\.)\s+)?"([\w./-]+)"', source
    )
    for block in re.findall(
        r"(?ms)^\s*(?:\d+:\s*)?import\s*\((.*?)^\s*(?:\d+:\s*)?\)", source
    ):
        go_imports.extend(re.findall(
            r'(?m)^\s*(?:\d+:\s*)?(?:(\w+|\.)\s+)?"([\w./-]+)"', block
        ))
    go_namespaces = {
        alias or module.rsplit("/", 1)[-1]: module.rsplit("/", 1)[-1]
        for alias, module in go_imports if alias not in ("_", ".")
    }
    aliases.update(go_namespaces)
    namespaces = {**go_namespaces, **js_namespaces}
    names = re.findall(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", source)
    terms = sorted({
        term.casefold()
        for name in names if name.split(".")[0] in aliases
        for term in name.split(".") if len(term) > 1
    } | {
        namespaces[name.split(".")[0]].casefold()
        for name in names if name.split(".")[0] in namespaces
        and re.fullmatch(r"[A-Za-z_]\w*", namespaces[name.split(".")[0]])
    })
    selected, size = [], 0
    for term in terms:
        if size + len(term) + 1 > MAX_QUERY_CHARS:
            break
        selected.append(term)
        size += len(term) + 1
    return " ".join(selected)


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


def lesson_suggestions(query, *, source_text="", exclude=(), directory=None):
    """Add at most one intact related card, without copying private source paths.

    The existing three baseline lessons remain with their callers. Match scores
    are lexical suggestions, not applicability, confidence or policy. Optional
    library errors must not stop discovery or turn into a defect verdict.
    """
    text = str(query).strip()
    result = {
        "matches": [],
        "caution": knowledge_notes.CAUTION,
        "query_truncated": len(text) > MAX_QUERY_CHARS,
        "oversized_matches_omitted": 0,
        "status": "NO_MATCH",
        "source_query_used": False,
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
        api_query = source_api_query(source_text)
        api_terms = set(api_query.split())
        source_matches = []
        if len(api_terms) >= 2:
            source_found = knowledge_notes.search(
                api_query, directory=directory or knowledge_notes.DEFAULT_DIRECTORY, limit=16,
            )
            source_matches = [
                match for match in source_found["matches"]
                if len(api_terms & set(knowledge_notes.normalized(
                    match["card"]["title"]).split())) >= 2
            ]
    except (OSError, ValueError):
        result["status"] = "LIBRARY_UNAVAILABLE"
        return result
    for from_source, match in (
        [(True, match) for match in source_matches]
        + [(False, match) for match in found["matches"]]
    ):
        card = match["card"]
        if card["id"] in excluded:
            continue
        if len(json.dumps(card, ensure_ascii=False).encode()) > MAX_CARD_BYTES:
            result["oversized_matches_omitted"] += 1
            continue
        result["matches"] = [card]
        result["status"] = "ADVISORY_MATCH"
        result["source_query_used"] = from_source
        break
    return result
