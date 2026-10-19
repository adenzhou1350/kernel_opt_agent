"""Python declarations and explicitly requested C++/Rust literal locations.

Syntax-only, never imported/executed code or production-reachability proof.
Ambiguous/missing declarations fall back to existing context selection. C++/Rust
locations are explicitly lexical, not parsed definitions or complete bodies.
"""
import ast
import hashlib
import io
import re
import tokenize
from urllib.parse import unquote, urlsplit


def prefer_supplied_snapshot_source(sources, selected, repo, commit):
    """Prefer an already-supplied current-pin window of the selected exact path.

    Never relabel old bytes, choose another file, fetch or mutate a source. If
    the packet has no matching pin within its first eight items, preserve the
    original selection so callers keep their existing drift/URL abstention.
    """
    if not isinstance(selected, dict):
        return selected
    try:
        url = urlsplit(selected.get("url", ""))
        match = re.fullmatch(rf"/{re.escape(repo)}/[0-9a-f]{{40}}/(.+)", url.path)
        if (url.scheme != "https" or url.netloc != "raw.githubusercontent.com"
                or url.query or url.fragment or match is None):
            return selected
        target = f"/{repo}/{commit}/{match[1]}"
        for source in sources[:8]:
            if not isinstance(source, dict):
                continue
            candidate = urlsplit(source.get("url", ""))
            if (candidate.scheme == "https" and candidate.netloc == "raw.githubusercontent.com"
                    and candidate.path == target and not candidate.query and not candidate.fragment):
                return source
    except (TypeError, ValueError):
        pass
    return selected


def requested_code_search_symbols(request):
    """Bounded lexical search keys, not a receiver or definition resolver.

    One/two explicit unqualified targets retain the existing query route.
    One/two Class.method definitions with the same capitalized owner search
    that owner once. Mixed, nested, malformed or competing owners abstain.
    """
    if not isinstance(request, str):
        return []
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)(definition|references)[ \t]*\(", request))
    if not 1 <= len(markers) <= 2:
        return []
    names, owners = [], []
    for marker in markers:
        match = re.match(
            r"[ \t]*([A-Za-z_][A-Za-z0-9_-]{3,127})"
            r"(?:\.([A-Za-z_][A-Za-z0-9_]{0,127}))?[ \t]*\)",
            request[marker.end():],
        )
        if match is None:
            return []
        if match[2] is not None:
            if marker[1] != "definition" or not re.fullmatch(r"[A-Z][A-Za-z0-9_]{3,127}", match[1]):
                return []
            owners.append(match[1])
        else:
            names.append(match[1])
    if owners:
        return [owners[0]] if not names and len(set(owners)) == 1 else []
    return list(dict.fromkeys(names))


def cached_reference_binding_symbol(packet, snapshot, analysis, cached_source):
    """Prefer an explicitly requested class-instance binding as a search literal.

    Two unqualified references must name a unique cached module-level class and
    its single direct ``INSTANCE = Class(...)`` assignment. This is syntax, not
    a resolved receiver/call graph. No fetch, invented target or extra query.
    Rebinding, ambiguity, missing/drifted cache or mixed requests abstain.
    """
    request = analysis.get("next_check", "")
    symbols = requested_code_search_symbols(request)
    if (
        not callable(cached_source)
        or len(symbols) != 2
        or re.findall(r"(?<!\w)(definition|references)[ \t]*\(", request[:2000])
        != ["references", "references"]
    ):
        return None
    repo, commit = packet.get("repo"), snapshot.get("commit")
    if (
        not isinstance(repo, str)
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        return None
    prefix = f"/{repo}/{commit}/"
    paths, matches = set(), []
    for source in packet.get("sources", [])[:8]:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            continue
        url = urlsplit(source["url"])
        if (
            url.scheme != "https"
            or url.netloc != "raw.githubusercontent.com"
            or url.query
            or url.fragment
            or not url.path.startswith(prefix)
        ):
            continue
        path = unquote(url.path[len(prefix) :])
        if (
            path in paths
            or path not in snapshot.get("files", [])
            or not path.endswith(".py")
        ):
            continue
        paths.add(path)
        try:
            raw = cached_source(repo, commit, path)
            if not isinstance(raw, str) or len(raw.encode("utf8")) > 100_000:
                continue
            tree = ast.parse(raw)
        except (OSError, ValueError, SyntaxError, RecursionError):
            continue
        nodes = list(ast.walk(tree))
        classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        imported = [
            a.asname or a.name.split(".")[0]
            for n in nodes
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in n.names
        ]
        if "*" in imported:
            continue
        for node in tree.body:
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ):
                continue
            binding, owner = node.targets[0].id, node.value.func.id
            if {binding, owner} != set(symbols) or classes.count(owner) != 1:
                continue
            stores = [
                n.id
                for n in nodes
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
            ]
            if (
                stores.count(binding) != 1
                or owner in stores
                or binding in imported
                or owner in imported
                or sum(
                    isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == owner
                    for n in nodes
                )
                != 1
                or any(isinstance(n, ast.arg) and n.arg in symbols for n in nodes)
                or any(
                    isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == binding
                    for n in nodes
                )
            ):
                continue
            matches.append((path, binding))
    return matches[0][1] if len(matches) == 1 else None


def cached_qualified_definition_path(packet, snapshot, analysis, cached_source):
    """Locate one explicit Class.method declaration in <=8 already-cached files.

    No fetch, import, execution, new path or receiver-resolution claim. Ambiguous
    or unavailable caches abstain. Callers retain their existing read budgets.
    """
    request = analysis.get("next_check") if isinstance(analysis, dict) else None
    if not isinstance(request, str) or not callable(cached_source):
        return None
    request = request[:2000]
    if len(re.findall(r"(?<!\w)definition[ \t]*\(", request)) != 1:
        return None
    if not re.search(
        r"(?<!\w)definition[ \t]*\([ \t]*[A-Za-z_]\w{0,127}"
        r"\.[A-Za-z_]\w{0,127}[ \t]*\)", request
    ):
        return None
    repo, commit = packet.get("repo"), snapshot.get("commit")
    if (
        not isinstance(repo, str)
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        return None
    prefix = f"https://raw.githubusercontent.com/{repo}/{commit}/"
    files = set(snapshot.get("files", []))
    candidates = []
    for source in packet.get("sources", [])[:8]:
        url = source.get("url") if isinstance(source, dict) else None
        if not isinstance(url, str) or not url.startswith(prefix):
            continue
        path = unquote(url[len(prefix) :])
        if path in files and path.endswith(".py") and path not in candidates:
            candidates.append(path)
    explicit_paths = [path for path in candidates if path in request]
    matches = []
    for path in candidates:
        if explicit_paths and path not in explicit_paths:
            continue
        try:
            raw = cached_source(repo, commit, path)
            if not isinstance(raw, str) or len(raw) > 1_000_000:
                continue
            target = requested_function_window(raw.splitlines(), request)
        except (OSError, ValueError, RecursionError):
            continue
        if target is not None:
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def cached_definition_pair_requests(packet, snapshot, analysis, cached_source):
    """Two explicit methods of one cached owner replace two ordinary reads.

    Require unique declarations in the same observed, Git-blob-verified file.
    No cache fill, receiver resolution, new source slot or completeness claim.
    Mixed, repeated, malformed or unavailable targets retain the old fallback.
    """
    request = analysis.get("next_check") if isinstance(analysis, dict) else None
    if not isinstance(request, str) or not callable(cached_source):
        return []
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)(definition|references)[ \t]*\(", request))
    if len(markers) != 2 or any(marker[1] != "definition" for marker in markers):
        return []
    targets = []
    for marker in markers:
        match = re.match(
            r"[ \t]*([A-Z][A-Za-z0-9_]{3,127})"
            r"\.([A-Za-z_][A-Za-z0-9_]{0,127})[ \t]*\)",
            request[marker.end():],
        )
        if match is None:
            return []
        targets.append((match[1], match[2]))
    if targets[0][0] != targets[1][0] or targets[0] == targets[1]:
        return []
    cache = {}

    def verified(repo, commit, path):
        if path not in cache:
            cache[path] = None
            raw = cached_source(repo, commit, path)
            if not isinstance(raw, str):
                return None
            body = raw.encode("utf-8")
            if len(body) > 1_000_000 or "\x00" in raw:
                return None
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            if blob == snapshot.get("blobs", {}).get(path):
                cache[path] = raw
        return cache[path]

    paths = []
    for owner, method in targets:
        # Keep other prose/path restrictions, but give the old unique-target
        # resolver only this marker. The reader receives that exact target too.
        one = re.sub(r"(?<!\w)definition[ \t]*\([^)]*\)", "", request)
        one = f"definition({owner}.{method}) " + one
        paths.append(cached_qualified_definition_path(
            packet, snapshot, {"next_check": one}, verified,
        ))
    if paths[0] is None or paths[0] != paths[1]:
        return []
    return [
        {"path": paths[0], "max_lines": 80,
         "request_hints": f"definition({owner}.{method})"}
        for owner, method in targets
    ]


def cached_definition_tail_request(packet, snapshot, analysis, cached_source):
    """Continue one explicitly re-requested, incomplete Python declaration.

    Only existing raw caches may establish the old window's identity. Its Git
    blob must equal the current tree's blob, including across revision changes.
    Read the next unread line, not the same declaration prefix. No network,
    body execution, extra source slot or completeness/reachability claim.
    """
    request = analysis.get("next_check") if isinstance(analysis, dict) else None
    if not isinstance(request, str) or not callable(cached_source):
        return None
    request = request[:2000]
    markers = re.findall(r"(?<!\w)(definition|references)[ \t]*\(", request)
    if markers != ["definition"] or re.search(r"\bbefore\s+line\b|之前|以前", request, re.IGNORECASE):
        return None
    repo = packet.get("repo")
    if (not isinstance(repo, str) or not isinstance(snapshot.get("commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", snapshot["commit"])):
        return None
    matches, cached = {}, {}
    for source in packet.get("sources", [])[:8]:
        if (not isinstance(source, dict) or source.get("requested_definition_complete") is not False
                or source.get("truncated") is not True):
            continue
        try:
            url = urlsplit(source.get("url", ""))
            match = re.fullmatch(rf"/{re.escape(repo)}/([0-9a-f]{{40}})/(.+)", url.path)
            if (url.scheme != "https" or url.netloc != "raw.githubusercontent.com"
                    or url.query or url.fragment or match is None):
                continue
            revision, path = match[1], unquote(match[2])
            literal_paths = re.findall(r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.py(?![\w/])", request)
            if any(p not in {path, path.rsplit("/", 1)[-1]} for p in literal_paths):
                continue
            blob = snapshot.get("blobs", {}).get(path)
            if (path not in snapshot.get("files", []) or not path.endswith(".py")
                    or not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40}", blob)):
                continue
            key = (revision, path)
            if key not in cached:
                cached[key] = cached_source(repo, revision, path)
            raw = cached[key]
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1_000_000:
                continue
            data = raw.encode("utf-8")
            if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != blob:
                continue
            lines = raw.splitlines()
            target = requested_function_window(lines, request)
            start, end, total = (source.get(k) for k in ("start_line", "end_line", "total_lines"))
            if (target is None or target != source.get("requested_definition")
                    or any(type(v) is not int for v in (start, end, total))
                    or not target["start_line"] <= start <= end < target["end_line"] <= total
                    or total != len(lines)):
                continue
            ranges = re.findall(r"(?:\blines?\s+|(?<!\d))(\d{1,7})\s*[-–—]\s*(\d{1,7})(?:\b|行)", request)
            if any(not target['start_line'] <= int(first) <= int(last) <= target['end_line']
                   or int(last) <= end for first, last in ranges):
                continue
            # Two fragments of this same declaration are one target. Start
            # after the furthest observed line; never claim the gap was read.
            candidate = {"path": path, "start": end + 1,
                         "max_lines": min(120, target["end_line"] - end)}
            if path not in matches or candidate["start"] > matches[path]["start"]:
                matches[path] = candidate
        except (OSError, ValueError, TypeError, RecursionError):
            continue
    return next(iter(matches.values())) if len(matches) == 1 else None


def requested_rust_fn_anchor(raw, request):
    """Locate one explicit unqualified Rust fn literal, not a parsed body.

    Comments/strings, macros, cfg branches and impl ownership are unresolved.
    Every repeated occurrence abstains, even if one is only documentation.
    """
    if not isinstance(raw, str) or len(raw) > 1_000_000 or not isinstance(request, str):
        return None
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request))
    if len(markers) != 1:
        return None
    match = re.match(
        r"[ \t]*([A-Za-z_][A-Za-z0-9_]{0,127})[ \t]*\)",
        request[markers[0].end():],
    )
    if match is None:
        return None
    name = match[1]
    matches = re.finditer(
        rf"(?<!\w)fn[ \t]+{re.escape(name)}(?!\w)[ \t]*(?=[(<])", raw
    )
    first = next(matches, None)
    if first is None or next(matches, None) is not None:
        return None
    return {
        "literal": "fn " + name,
        "line": raw.count("\n", 0, first.start()) + 1,
        "scope": (
            "Unique requested Rust fn-name literal followed by ( or < in this "
            "pinned file, including comments/strings. Not a parsed definition, "
            "resolved impl owner, active cfg branch, macro expansion or complete body."
        ),
    }


def requested_native_literal_anchor(raw, request):
    """Locate one explicit qualified C++ literal, not a parsed definition.

    Comments/generated strings and inactive branches are not resolved. Repeated
    occurrences abstain; no overload/owner/body inference or complete-body flag.
    """
    if not isinstance(raw, str) or len(raw) > 1_000_000 or not isinstance(request, str):
        return None
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request))
    if len(markers) != 1:
        return None
    match = re.match(
        r"[ \t]*([A-Za-z_][A-Za-z0-9_]{0,127}"
        r"(?:::[A-Za-z_][A-Za-z0-9_]{0,127}){1,4})[ \t]*\)",
        request[markers[0].end():],
    )
    if match is None or len(match[1]) > 256:
        return None
    symbol = match[1]
    pattern = rf"(?<![\w:]){re.escape(symbol)}(?![\w:])\s*\("
    matches = re.finditer(pattern, raw)
    first = next(matches, None)
    if first is None or next(matches, None) is not None:
        return None
    return {
        "literal": symbol,
        "line": raw.count("\n", 0, first.start()) + 1,
        "scope": (
            "Unique requested qualified literal followed by ( in this pinned "
            "C-family file, including comments/strings. Not a parsed definition, "
            "resolved owner, active preprocessor branch or complete body."
        ),
    }


def absent_requested_identifiers(raw, request):
    """Disclose missing literal names in already-read source, in any language.

    Do not silently substitute a spelling or infer a missing declaration. Even
    a comment/string occurrence prevents this conservative absence observation.
    Qualified requests test only their terminal identifier, not a binding.
    """
    if not isinstance(raw, str) or not isinstance(request, str):
        return []
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)(?:definition|references)[ \t]*\(", request))
    names = []
    for marker in markers:
        match = re.match(
            r"[ \t]*([A-Za-z_][A-Za-z0-9_]{0,127}"
            r"(?:\.[A-Za-z_][A-Za-z0-9_]{0,127}){0,4})[ \t]*\)",
            request[marker.end():],
        )
        if match is None:
            return []
        name = match[1].rsplit(".", 1)[-1]
        if name not in names:
            names.append(name)
    if not 1 <= len(names) <= 2:
        return []
    return [name for name in names if name not in raw]


def requested_definition_inventory(lines, request, symbol):
    """Expose ambiguous Python declarations without selecting a receiver/body.

    Only an explicit unqualified definition(symbol) activates this advisory
    inventory. Its source is the already acquired exact file, not another read.
    """
    if not isinstance(symbol, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]{3,127}", symbol
    ):
        return None
    if not isinstance(request, str) or not re.search(
        rf"(?<!\w)definition[ \t]*\([ \t]*{re.escape(symbol)}[ \t]*\)",
        request[:2000],
    ):
        return None
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError, RecursionError):
        return None
    declarations = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    stack = [(tree, ())]
    matches = []
    while stack:
        node, owners = stack.pop()
        if isinstance(node, declarations):
            qualified = owners + (node.name,)
            if node.name == symbol:
                name = ".".join(qualified)
                # Do not admit an unbounded lexical owner into a model packet.
                if len(name) > 256:
                    return None
                matches.append(
                    {
                        "qualified_name": name,
                        "kind": type(node).__name__,
                        "declaration_line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )
            owners = qualified
        stack.extend((child, owners) for child in ast.iter_child_nodes(node))
    if len(matches) < 2:
        return None
    matches.sort(key=lambda item: item["declaration_line"])
    return {
        "symbol": symbol,
        "total_matches": len(matches),
        "candidates": matches[:8],
        "truncated": len(matches) > 8,
        "scope": (
            "Syntax-only declarations in this pinned Python file; locations may be "
            "outside the visible body window. Not receiver resolution, inheritance "
            "dispatch, callable identity or proof of unread implementation behavior."
        ),
    }


def requested_function_window(lines, request):
    if not request:
        return None
    request = request[:2000]
    # Explicit syntax chooses the evidence target, not other API names in the
    # explanation. Reject malformed/multiple targets rather than silently
    # selecting a different function mentioned in prose.
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request))
    explicit = set()
    for marker in markers:
        match = re.match(
            r"[ \t]*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)[ \t]*\)",
            request[marker.end():],
        )
        if match is None:
            return None
        explicit.add(match[1])
    if markers and len(explicit) != 1:
        return None
    if explicit:
        request = next(iter(explicit))
    text = "\n".join(lines)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    qualified = set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_]\w*)\b", request))
    if explicit and "." in request:
        qualified = {tuple(request.split("."))}
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    if qualified:
        if len(qualified) != 1:
            return None
        owner, name = next(iter(qualified))
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == owner]
        if len(classes) != 1:
            return None
        matches = [node for node in classes[0].body if isinstance(node, functions) and node.name == name]
    else:
        names = explicit or set(re.findall(r"[A-Za-z_]\w{2,}", request))
        # Classes can contain the requested lifecycle evidence. Admit them only
        # for definition(Name), not incidental class names in free-form prose.
        # A same-name function/class remains ambiguous rather than guessing.
        declarations = functions + (ast.ClassDef,) if explicit else functions
        matches = [node for node in ast.walk(tree) if isinstance(node, declarations) and node.name in names]
    if len(matches) != 1:
        return None
    node = matches[0]
    start = node.lineno
    if node.decorator_list:
        # AST decorator expressions can start *inside* a parenthesized @(...).
        # Find its actual @ token, not a comment/string or a matrix operator.
        first_expression = min(decorator.lineno for decorator in node.decorator_list)
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.start[0] > first_expression:
                break
            if (token.type == tokenize.OP and token.string == "@"
                    and token.start[1] == node.col_offset):
                start = token.start[0]
    return {"name": node.name, "start_line": start, "end_line": node.end_lineno}
