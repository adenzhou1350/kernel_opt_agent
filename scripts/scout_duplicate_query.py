"""Use a visible pinned declaration as a related-work hint, never a verdict."""

import re
from urllib.parse import urlsplit

try:
    from .scout_symbol_references import _native_code_lines
except ImportError:
    from scout_symbol_references import _native_code_lines


def _native_declarations(text):
    """Numbered out-of-line C++ definitions only; not a C++ parser."""
    rows = [re.fullmatch(r"([1-9][0-9]*):(.*)", row)
            for row in text[:9000].splitlines()]
    if not rows or any(row is None for row in rows):
        return []
    numbers = [int(row[1]) for row in rows]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return []
    lines = _native_code_lines("\n".join(row[2] for row in rows))
    if lines is None:
        return []
    code = "\n".join(lines)
    definitions = []
    for match in re.finditer(
        r"(?m)^[ \t]*([A-Za-z_][\w:<>,*& \t]*?)[ \t]+"
        r"(?:[A-Za-z_][A-Za-z0-9_]*::)+([A-Za-z_][A-Za-z0-9_]{2,63})"
        r"[ \t]*\([^;{}]*\)[ \t]*(?:const[ \t]*)?(?:noexcept[ \t]*)?\{",
        code,
    ):
        if match[1].split()[0] in {"return", "throw", "co_return", "using"}:
            continue
        definitions.append((numbers[code.count("\n", 0, match.start())], match[2]))
    return definitions


def source_duplicate_title(repo, title, sources):
    """Prefer one title-mentioned visible definition over generic feature prose.

    No network, source execution or additional queries. Missing/ambiguous/clipped
    declarations retain the original search. C++ support is limited to numbered
    out-of-line definitions with a visible body opener; no macro/owner resolution.
    Metadata alone is insufficient.
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
            or not parts[3].endswith((".py", ".cpp", ".cc", ".cxx", ".cu", ".h", ".hpp", ".cuh"))
            or url.query
            or url.fragment
        ):
            continue
        text = source.get("text")
        if not isinstance(text, str):
            continue
        if not parts[3].endswith(".py"):
            for line, name in _native_declarations(text):
                if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", title[:1000]):
                    declarations.add((source["url"], line, name))
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
    if len(declarations) != 1:
        return title
    name = next(iter(declarations))[2]
    # Keep a title's owner/module spelling instead of reducing e.g.
    # OneToOne.update to the generic word "update". Only the visible method
    # declaration is source-checked; its qualified prefix is an untrusted
    # relevance hint, not proof of ownership, dispatch, novelty or duplication.
    qualified = set(
        re.findall(
            rf"(?<![\w./:])(?:[A-Za-z_][A-Za-z0-9_]{{0,63}}\.)+"
            rf"{re.escape(name)}(?!\w)",
            title[:1000],
        )
    )
    if qualified:
        hint = next(iter(qualified))
        return hint if len(qualified) == 1 and len(hint) <= 256 else title
    return name
