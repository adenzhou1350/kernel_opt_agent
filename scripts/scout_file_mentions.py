"""Whole filename mentions for observed-tree ranking, not fetch authority."""

import re


def filename_mentions(hints):
    """Avoid reading ``test_backend.py`` as an explicit ``backend.py`` mention.

    Slash/backslash/colon delimit filenames in paths and tracebacks. Compound
    suffixes stay whole, so ``backend.py.bak`` is not an explicit Python file.
    The caller still restricts candidates to its observed repository snapshot.
    """
    return set(
        re.findall(
            r"(?<![a-z0-9_.-])([a-z0-9_.-]+\.[a-z0-9]+)(?![a-z0-9_.-])",
            hints.lower()[:16000],
        )
    )
