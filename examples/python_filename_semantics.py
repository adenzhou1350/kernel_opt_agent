"""An exposed stdlib control, not packaging's native public-wrapper test.

Check individual semantic claims instead of treating a correct verdict or a
plausible explanation as evidence. No filesystem access, package install,
generated-code execution, model call or expected-answer scoring is performed.
"""
import json
import platform
import re
from pathlib import Path


def observe():
    pattern = re.compile(r"^pylock\.([^.]+)\.toml$")
    observations = []
    for value in ("pylock.toml", "pylock.spam.toml", "pylock.json", "pylock.spam.toml\n"):
        name = Path(value).name
        observations.append({
            "input": value,
            "path_name": name,
            "path_name_preserves_input": name == value,
            "regex_match": bool(pattern.match(name)),
            "regex_fullmatch": bool(pattern.fullmatch(name)),
        })
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "pattern": pattern.pattern,
        "observations": observations,
        "scope": "Stdlib semantics only; not package correctness, model quality or selector utility.",
    }


if __name__ == "__main__":
    print(json.dumps(observe(), ensure_ascii=False, indent=2))
