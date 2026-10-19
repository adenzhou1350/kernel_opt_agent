"""Conservative multiword filename hints; no fetching or symbol resolution."""
import re

_NONPRODUCTION = frozenset({
    "test", "tests", "testing", "__tests__", "fixtures", "vendor", "generated",
    "node_modules", "third_party", "dist", "build",
})
_ROLES = frozenset({
    "service", "provider", "manager", "adapter", "handler", "helper", "client",
    "controller", "factory", "config", "common", "utils", "build", "index", "main",
    "test", "tests", "spec",
})
_PACKAGE_ROLES = frozenset({
    "connector", "backend", "manager", "controller", "provider", "handler",
    "client", "service", "factory",
})
_GENERIC_PACKAGE = _ROLES | frozenset({
    "src", "lib", "data", "core", "base", "code", "types", "local", "global",
    "native", "python", "rust",
})


def qualified_class_path_hint(path, class_names):
    """Match a full observed type name to an immediate package/role filename.

    For example, NixlConnector may name nixl/connector.py after a module split.
    This is a lexical hint, not a resolved definition. The caller supplies full
    case-folded CamelCase names, not prefixes or ordinary prose keywords.
    """
    parts = path.split("/")
    if len(parts) < 2 or _NONPRODUCTION.intersection(p.lower() for p in parts[:-1]):
        return False
    role = parts[-1].rsplit(".", 1)[0].lower()
    parent = parts[-2].lower()
    if role not in _PACKAGE_ROLES or not re.fullmatch(r"[a-z][a-z0-9_-]{3,63}", parent):
        return False
    words = re.split(r"[_-]+", parent)
    if any(not word or word in _GENERIC_PACKAGE for word in words):
        return False
    return "".join(words) + role in class_names


def compound_path_hint(path, hints):
    """Match a contiguous 2..4-word phrase against an observed filename.

    Strip generic role suffixes, never the directory or a sole keyword. Simple
    plural spelling is supported, not synonyms, stemming or semantic inference.
    The caller retains source suffix, tree membership and read-budget checks.
    """
    parts = path.split("/")
    if _NONPRODUCTION.intersection(part.lower() for part in parts[:-1]):
        return False
    stem = parts[-1].rsplit(".", 1)[0]
    words = re.split(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[_.-]+", stem)
    words = [word.lower() for word in words]
    # A test suffix is not made into an implementation hint by stripping it.
    if any(word in {"test", "tests", "spec"} for word in words):
        return False
    while words and words[-1] in _ROLES:
        words.pop()
    if not 2 <= len(words) <= 4 or any(
        len(word) < 4 or not word.isascii() or not word.isalpha() or word in _ROLES
        for word in words
    ):
        return False
    plural = [re.escape(word[:-1] if word.endswith("s") and not word.endswith(("ss", "us", "is"))
                        else word) + "s?" for word in words]
    phrase = r"(?<![a-z0-9_])" + r"[\s_-]+".join(plural) + r"(?![a-z0-9_])"
    return re.search(phrase, hints[:16000], re.IGNORECASE) is not None
