"""Go declaration anchors in already acquired source; not a Go parser/resolver.

Only an explicit definition(name), definition(package.name), or simple receiver
request is supported. Comments/literals are masked, brace depth excludes nested
code, and ambiguity abstains. This locates one declaration, not its complete body,
build-selected implementation, imported symbol binding or runtime reachability.
"""
import re

IDENT = r"[A-Za-z_][A-Za-z0-9_]{0,127}"
FREE = re.compile(rf"^func\s+({IDENT})\s*(?:\[|\()")
METHOD = re.compile(
    rf"^func\s*\(\s*(?:{IDENT}\s+)?\*?({IDENT})\s*\)\s*({IDENT})\s*\("
)


def _code(raw):
    """Preserve line positions, masking Go comments, strings and rune literals."""
    output = list(raw)
    index = 0
    while index < len(raw):
        start = index
        if raw.startswith("//", index):
            end = raw.find("\n", index + 2)
            index = len(raw) if end < 0 else end
        elif raw.startswith("/*", index):
            end = raw.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
        elif raw[index] in "\"'`":
            quote = raw[index]
            index += 1
            while index < len(raw) and raw[index] != quote:
                if quote != "`" and raw[index] == "\\":
                    index += 2
                elif quote != "`" and raw[index] in "\r\n":
                    return None
                else:
                    index += 1
            if index >= len(raw):
                return None
            index += 1
        else:
            index += 1
            continue
        for offset in range(start, index):
            if raw[offset] not in "\r\n":
                output[offset] = " "
    return "".join(output)


def go_declaration_anchor(raw, request):
    if (not isinstance(raw, str) or len(raw.encode("utf-8")) > 131072
            or "\x00" in raw or not isinstance(request, str)):
        return None
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request[:2000]))
    names = set()
    for marker in markers:
        match = re.match(rf"[ \t]*({IDENT}(?:\.{IDENT})?)[ \t]*\)",
                         request[:2000][marker.end():])
        if match is None:
            return None
        names.add(match[1])
    if len(names) != 1:
        return None
    target = names.pop()
    owner, _, name = target.rpartition(".")
    name = name or target
    masked = _code(raw)
    if masked is None:
        return None
    package = re.match(rf"\s*package[ \t]+({IDENT})\b", masked)
    if package is None:
        return None
    depth, found = 0, []
    for number, line in enumerate(masked.splitlines(), 1):
        if depth == 0:
            free, method = FREE.match(line.lstrip()), METHOD.match(line.lstrip())
            if free and free[1] == name and owner in ("", package[1]):
                found.append(number)
            if method and method[2] == name and owner in ("", method[1]):
                found.append(number)
        for character in line:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth < 0:
                    return None
    if depth != 0 or len(found) != 1:
        return None
    return dict(
        name=target, line=found[0],
        scope="Lexical declaration in this pinned Go file only; not a complete body, import/type binding, build selection or runtime reachability proof.",
    )
