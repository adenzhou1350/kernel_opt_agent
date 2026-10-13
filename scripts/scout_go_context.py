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


def _code(raw, strings=None):
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
            if strings is not None and quote != "'":
                strings.append((start, index, raw[start + 1:index - 1]))
        else:
            index += 1
            continue
        for offset in range(start, index):
            if raw[offset] not in "\r\n":
                output[offset] = " "
    return "".join(output)


def go_declaration_anchor(raw, request, *, free_only=False):
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
            if not free_only and method and method[2] == name and owner in ("", method[1]):
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


def _imports(raw):
    """Simple Go import prefix only; never scan import-shaped string contents."""
    strings = []
    masked = _code(raw, strings)
    if masked is None:
        return []
    package = re.match(rf"\s*package[ \t]+{IDENT}\b", masked)
    if package is None:
        return []
    cursor, result = package.end(), []
    while cursor < len(masked):
        cursor += len(masked[cursor:]) - len(masked[cursor:].lstrip(" \t\r\n;"))
        marker = re.match(r"import\b", masked[cursor:])
        if marker is None:
            break
        cursor += marker.end()
        literal_start = next((start for start, _, _ in strings if start >= cursor), len(masked))
        while cursor < literal_start and masked[cursor].isspace():
            cursor += 1
        grouped = masked[cursor:cursor + 1] == "("
        end = masked.find(")", cursor + 1) if grouped else len(masked)
        if end < 0:
            return []
        selected = [s for s in strings if cursor <= s[0] < end]
        if not selected:
            return []
        if not grouped:
            selected = selected[:1]
        previous = cursor + int(grouped)
        for start, stop, path in selected:
            alias = masked[previous:start].strip(" \t\r\n;")
            if alias and re.fullmatch(rf"{IDENT}|[._]", alias) is None:
                return []
            # Escaped, absolute, traversal and nonliteral paths abstain rather
            # than reinterpret a model string or Go import escape sequence.
            if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,511}", path)
                    and all(p not in ("", ".", "..") for p in path.split("/"))):
                if alias not in (".", "_"):
                    result.append((alias or None, path))
            previous = stop
        if grouped and masked[previous:end].strip(" \t\r\n;"):
            return []
        cursor = end + 1 if grouped else selected[0][1]
    return result


def go_import_requests(path, raw, files, sources, repo, commit, request, cached, *, limit):
    """<=2 same-module cached declaration hints, replacing ordinary source reads.

    A missing observed go.mod consumes one existing read slot first. The next
    followup may reuse it. Scan <=16 package files/1 MiB of already cached text;
    unread files, build tags, workspace/replace/vendor and local alias shadowing
    are not resolved. Never fetch here or infer a bound call/defect from a hint.
    """
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request[:2000]))
    targets = []
    for marker in markers:
        match = re.match(rf"[ \t]*({IDENT})\.({IDENT})[ \t]*\)", request[:2000][marker.end():])
        if match is None:
            return []
        if match.groups() not in targets:
            targets.append(match.groups())
    if not 1 <= len(targets) <= 2:
        return []
    # A supplied same-file declaration needs no imported-package lookup. In
    # particular, an unaliased stdlib import must not turn Result.Bool into a
    # speculative package name and consume a go.mod read. This only suppresses
    # redundant acquisition for that exact lexical declaration, not a body or
    # type-resolution claim; other requested imported targets remain eligible.
    targets = [(owner, symbol) for owner, symbol in targets
               if go_declaration_anchor(raw, f"definition({owner}.{symbol})") is None]
    if not targets:
        return []
    imports = _imports(raw)
    if not imports or not any(alias is None or alias == target[0] for alias, _ in imports for target in targets):
        return []
    parts = path.split("/")[:-1]
    modules = ["/".join(parts[:n] + ["go.mod"]) for n in range(len(parts) + 1)]
    module_file = next((p for p in reversed(modules) if p in files), None)
    if module_file is None:
        return []
    module_raw = cached(repo, commit, module_file)
    if module_raw is None:
        return [dict(path=module_file, hints="module directive", max_lines=80)]
    if not isinstance(module_raw, str) or len(module_raw.encode()) > 131072 or "\x00" in module_raw:
        return []
    masked = _code(module_raw)
    modules = re.findall(r"(?m)^\s*module[ \t]+([A-Za-z0-9][A-Za-z0-9._/-]*)[ \t]*$", masked or "")
    if len(modules) != 1 or any(p in ("", ".", "..") for p in modules[0].split("/")):
        return []
    module, prefix = modules[0], module_file[:-len("go.mod")]
    results, read_cache, total_bytes = [], {}, 0
    for owner, symbol in targets:
        matches, bindings = [], set()
        if len({p for a, p in imports if a == owner}) > 1:
            continue
        for alias, imported in imports:
            if alias is not None and alias != owner:
                continue
            if imported == module:
                directory = prefix.rstrip("/")
            elif imported.startswith(module + "/"):
                directory = prefix + imported[len(module) + 1:]
            else:
                continue  # No installed dependency/package-registry lookup.
            parents = directory.split("/") if directory else []
            if any("/".join(parents[:n] + ["go.mod"]) in files
                   and "/".join(parents[:n] + ["go.mod"]) != module_file
                   for n in range(len(prefix.rstrip("/").split("/")) if prefix else 0, len(parents) + 1)):
                continue  # A nested module is a separate identity.
            candidates = sorted(p for p in files if p.endswith(".go")
                and not p.endswith("_test.go") and p.rpartition("/")[0] == directory and p != path)
            if len(candidates) > 16:
                continue
            for candidate in candidates:
                if candidate not in read_cache:
                    if len(read_cache) >= 16:
                        return []
                    text = cached(repo, commit, candidate)
                    if text is not None and (not isinstance(text, str) or len(text.encode()) > 131072):
                        return []
                    total_bytes += len(text.encode()) if text is not None else 0
                    if total_bytes > 1_048_576:
                        return []
                    read_cache[candidate] = text
                text = read_cache[candidate]
                if text is None:
                    continue  # Missing cached files are unknown, not absent declarations.
                code = _code(text)
                package = re.match(rf"\s*package[ \t]+({IDENT})\b", code or "")
                if package is None or (alias is None and package[1] != owner):
                    continue
                bindings.add(imported)
                found = go_declaration_anchor(text, f"definition({package[1]}.{symbol})", free_only=True)
                if found is not None:
                    matches.append((candidate, found["line"], len(text.splitlines())))
        matches = sorted(set(matches))
        if len(matches) != 1 or len(bindings) != 1:
            continue  # Competing cached declarations/build variants abstain.
        candidate, line, total_lines = matches[0]
        url = f"https://raw.githubusercontent.com/{repo}/{commit}/{candidate}"
        if any(s.get("url") == url and type(s.get("start_line")) is int
               and type(s.get("end_line")) is int and s["start_line"] <= line
               and s["end_line"] >= min(total_lines, line + 79) for s in sources):
            continue
        read = dict(path=candidate, start=line, max_lines=80, go_import_hint=dict(
            target=owner + "." + symbol,
            scope="Cached same-module declaration hint only; unread package files, build tags, workspace/replace/vendor and alias shadowing are unresolved. Not a bound caller, complete body or defect verdict.",
        ))
        if read not in results:
            results.append(read)
        if len(results) == limit:
            break
    return results
