"""Use a visible pinned declaration as a related-work hint, never a verdict."""

import re
from urllib.parse import urlsplit


def source_duplicate_title(repo, title, sources):
    """Prefer one title-mentioned Python definition over generic feature prose.

    No network, source execution or additional queries. Missing/ambiguous/clipped
    declarations retain the original search. Metadata alone is insufficient.
    """
    if not isinstance(title, str) or not isinstance(sources, list):
        return title
    declarations = set()
    for source in sources[:24]:
        if not isinstance(source, dict):
            continue
        try:
            url = urlsplit(source.get("url", ""))
        except (TypeError, ValueError):
            continue
        parts = url.path.strip("/").split("/", 3)
        if (
            url.scheme != "https"
            or url.netloc != "raw.githubusercontent.com"
            or len(parts) != 4
            or "/".join(parts[:2]).casefold() != repo.casefold()
            or not re.fullmatch(r"[0-9a-f]{40}", parts[2])
            or not parts[3].endswith(".py")
            or url.query
            or url.fragment
        ):
            continue
        text = source.get("text")
        if not isinstance(text, str):
            continue
        definition = source.get("requested_definition")
        if "requested_definition" in source and (
            not isinstance(definition, dict)
            or type(definition.get("start_line")) is not int
            or not isinstance(definition.get("name"), str)
        ):
            continue
        # Syntax-shaped visible evidence, not a complete parse or reachability
        # claim. If AST selection metadata exists, it must match this exact line.
        for match in re.finditer(
            r"(?m)^([1-9][0-9]*):[ \t]*(?:async[ \t]+)?def[ \t]+"
            r"([A-Za-z_][A-Za-z0-9_]{2,63})[ \t]*\(",
            text[:9000],
        ):
            line, name = int(match[1]), match[2]
            if definition is not None and (
                line != definition["start_line"] or name != definition["name"]
            ):
                continue
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", title[:1000]):
                declarations.add((source["url"], line, name))
    return next(iter(declarations))[2] if len(declarations) == 1 else title
