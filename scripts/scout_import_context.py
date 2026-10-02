"""Bounded hints for missing relative-import definitions, never a resolver proof.

Use only cached, pinned primary source and members of the same observed tree.
No source execution, cache fill, model-created fetch target, or quality verdict.
Unsupported syntax/resolution leaves ordinary context acquisition unchanged.
"""

import ast
import re
from urllib.parse import unquote, urlsplit

IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
NAMED_IMPORT = re.compile(
    rf"import\s+(?:type\s+)?(?:{IDENT}\s*,\s*)?"
    r"\{([^{};]{1,4000})\}\s*from\s*(['\"])([^'\"\r\n\\]{1,512})\2\s*;?"
)
OTHER_IMPORT = re.compile(
    rf"import\s+(?:(?:{IDENT}|\*\s+as\s+{IDENT})\s+from\s+)?"
    r"(['\"])[^'\"\r\n\\]{1,512}\1\s*;?"
)
DIRECTIVE = re.compile(r"(['\"])[A-Za-z _-]{1,40}\1\s*;")


def _trivia(raw, pos):
    while pos < len(raw):
        match = re.match(r"\s+|//[^\n]*|/\*[\s\S]*?\*/", raw[pos:])
        if match is None:
            break
        pos += match.end()
    return pos


def _js_bindings(raw):
    """Conservatively scan the import prefix, not strings or later source text."""
    pos = 0
    for _ in range(128):
        pos = _trivia(raw, pos)
        directive = DIRECTIVE.match(raw, pos)
        if directive:
            pos = directive.end()
            continue
        match = NAMED_IMPORT.match(raw, pos)
        if match:
            for entry in match[1].split(","):
                name = re.fullmatch(
                    rf"\s*(?:type\s+)?({IDENT})(?:\s+as\s+({IDENT}))?\s*", entry
                )
                if name:
                    yield name[2] or name[1], name[1], match[3]
            pos = match.end()
            continue
        other = OTHER_IMPORT.match(raw, pos)
        if other:
            pos = other.end()
            continue
        break  # Unsupported/import-later syntax is not guessed.


def _bindings(path, raw):
    if path.endswith(".py"):
        try:
            tree = ast.parse(raw)
        except (SyntaxError, ValueError, RecursionError):
            return
        # Deferred imports are common at GPU wrapper boundaries. Gather hints
        # from top-level free functions as well as the module, but do not enter
        # nested functions/classes or pretend conditional imports are bindings.
        # Competing observed targets still cause import_requests() to abstain.
        nodes = list(tree.body)
        for owner in tree.body:
            if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pending = list(owner.body)
                while pending:
                    node = pending.pop()
                    if isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ):
                        continue
                    nodes.append(node)
                    pending.extend(ast.iter_child_nodes(node))
        for node in nodes:
            if (
                not isinstance(node, ast.ImportFrom)
                or not node.level
                or not node.module
            ):
                continue
            module = "../" * (node.level - 1) + "./" + node.module.replace(".", "/")
            for name in node.names:
                if name.name != "*":
                    yield name.asname or name.name, name.name, module
    elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs", ".cts", ".cjs")):
        yield from _js_bindings(raw)


def _resolve(path, module, files):
    if not module.startswith(("./", "../")):
        return None
    parts = path.split("/")[:-1]
    for part in module.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif any(c in part for c in "\\:?%#") or any(ord(c) < 32 for c in part):
            return None
        else:
            parts.append(part)
    base = "/".join(parts)
    if path.endswith(".py"):
        choices = [base + ".py", base + "/__init__.py"]
    else:
        rewrites = {
            ".js": (".ts", ".tsx", ".js"),
            ".mjs": (".mts", ".mjs"),
            ".cjs": (".cts", ".cjs"),
        }
        suffix = "." + base.rsplit(".", 1)[-1]
        if suffix in rewrites:
            choices = [base[: -len(suffix)] + ext for ext in rewrites[suffix]]
        elif suffix in {".ts", ".tsx", ".mts", ".cts", ".jsx"}:
            choices = [base]
        else:
            choices = [
                base + ext for ext in (".ts", ".tsx", ".js", "/index.ts", "/index.js")
            ]
    observed = [p for p in choices if p in files and p != path]
    return observed[0] if len(observed) == 1 else None


def import_requests(packet, snapshot, analysis, cached_source, *, limit=2):
    """Propose <=2 definitions explicitly requested in the prior next_check.

    Same-file free functions, named aliases and .js -> .ts are hints only.
    Local JS function declarations are lexical, not a complete language parser.
    Python free-function relative imports supply module hints, not proof of
    local-name resolution. A complete module already supplied is not reread.
    Ambiguous declarations/tree members,
    absent cache, revision drift, bare package imports and wildcard imports abstain.
    The callback must be a read-only cache lookup, not another acquisition step.
    """
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError("import context limit must be 1..2")
    hints = analysis.get("next_check", "")
    if not isinstance(hints, str):
        return []
    requested = list(dict.fromkeys(re.findall(IDENT, hints[:4000])))[:64]
    sources = packet.get("sources", [])
    if not sources or not requested:
        return []
    url = urlsplit(sources[0].get("url", ""))
    repo, commit = packet.get("repo", ""), snapshot.get("commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return []
    prefix = f"/{repo}/{commit}/"
    if (
        not repo
        or url.scheme != "https"
        or url.netloc != "raw.githubusercontent.com"
        or url.query
        or url.fragment
        or not url.path.startswith(prefix)
    ):
        return []
    path = unquote(url.path[len(prefix) :])
    files = set(snapshot.get("files", []))
    if path not in files or any(p in {"", ".", ".."} for p in path.split("/")):
        return []
    raw = cached_source(repo, commit, path)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 131072 or "\x00" in raw:
        return []
    bindings = {}
    for local, imported, module in _bindings(path, raw):
        target = _resolve(path, module, files)
        if target:
            bindings.setdefault(local, set()).add((imported, target))
    declarations = _local_functions(path, raw)
    qualified = set(re.findall(rf"\.({IDENT})\b", hints[:4000]))
    requests, paths = [], set()
    for symbol in requested:
        candidates = bindings.get(symbol, set())
        local = declarations.get(symbol, [])
        if local:
            # Do not resolve methods, overloads or competing imported/local names.
            if len(local) != 1 or candidates or symbol in qualified:
                continue
            start = max(1, local[0] - 8)
            end = min(len(raw.splitlines()), start + 79)
            if path in paths or any(
                source.get("url") == sources[0]["url"]
                and type(source.get("start_line")) is int
                and type(source.get("end_line")) is int
                and source["start_line"] <= start
                and source["end_line"] >= end
                for source in sources
            ):
                continue
            paths.add(path)
            requests.append({"path": path, "start": start, "max_lines": 80})
            if len(requests) == limit:
                break
            continue
        if len(candidates) != 1:
            continue
        imported, target = next(iter(candidates))
        if target in paths:
            continue
        target_url = f"https://raw.githubusercontent.com/{repo}/{commit}/{target}"
        if any(
            source.get("url") == target_url
            and source.get("truncated") is False
            and source.get("start_line") == 1
            and type(source.get("total_lines")) is int
            and source["total_lines"] > 0
            and type(source.get("end_line")) is int
            and source["end_line"] >= source["total_lines"]
            for source in sources
        ):
            continue
        paths.add(target)
        requests.append({"path": target, "hints": imported, "max_lines": 80})
        if len(requests) == limit:
            break
    return requests


def _local_functions(path, raw):
    """Locate free-function declarations without executing or resolving source.

    Python uses AST module ownership. JS/TS masks ordinary comments/literals and
    tracks lexical braces; unsupported syntax can miss declarations. These are
    acquisition hints, never proof of binding, reachability or language validity.
    """
    found = {}
    if path.endswith(".py"):
        try:
            tree = ast.parse(raw)
        except (SyntaxError, ValueError, RecursionError):
            return found
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.setdefault(node.name, []).append(node.lineno)
        return found
    if not path.endswith(
        (".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs", ".cts", ".cjs")
    ):
        return found
    literals = re.compile(
        r"//[^\n]*|/\*[\s\S]*?\*/|"
        r"'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\"|"
        r"`(?:\\[\s\S]|[^`\\])*`"
    )
    masked = literals.sub(lambda match: re.sub(r"[^\n]", " ", match[0]), raw)
    declaration = re.compile(
        rf"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+({IDENT})\s*\("
    )
    depth = 0
    for number, line in enumerate(masked.splitlines(), 1):
        match = declaration.match(line) if depth == 0 else None
        if match:
            found.setdefault(match[1], []).append(number)
        depth += line.count("{") - line.count("}")
        if depth < 0:
            return {}
    return found if depth == 0 else {}
