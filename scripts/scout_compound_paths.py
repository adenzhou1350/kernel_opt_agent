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
