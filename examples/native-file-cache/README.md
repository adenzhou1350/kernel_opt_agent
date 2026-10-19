# Public byte-range cache oracle

When a cache lead concerns byte boundaries, exercise the actual buffered-file
caller before changing its internals. This small standard-library test imports
the real fsspec package from an explicitly supplied, reviewed source root and
uses a real `MemoryFileSystem`. It compares seek/read/readinto results and file
positions with `io.BytesIO`; only the backend boundary is instrumented to reject
empty or out-of-file fetches. No cache algorithm is copied or replaced.

```sh
python -B examples/native-file-cache/check.py --source /path/to/reviewed/filesystem_spec
```

Use a fresh process, existing execution limits, and the project's supported
Python. The example needs no network, GPU, WSL or third-party test framework.
It verifies import roots rather than falling through to an installed package.
To export committed sources first, reuse `qualification_source_bundle.py`'s
raw-Git reader; do not copy a Windows-converted archive or omit imported fixtures
when running upstream pytest. This example itself imports production modules,
not that pytest fixture graph.

The development audit targets
[fsspec 4c15b0e](https://github.com/fsspec/filesystem_spec/blob/4c15b0ec8d4a1b676e1377be54312af261e847e3/fsspec/caching.py),
including the existing author's [final-block fix #2319](https://github.com/fsspec/filesystem_spec/pull/2319).
It is not our new bug or patch. The two cache types cover 288 combinations of
empty/partial/exact-block sizes, block sizes and cache capacities, with fixed
seed traces and 19,584 read checks per run. The close check follows the real
file's cache-disposal hook, retaining the cache reference before close. A first
private harness incorrectly dereferenced `file.cache` after that hook cleared it;
its failures were retained, not classified as cache defects.

The corresponding development run passed on Windows/Python3.14.3 and an offline
Linux/Python3.12.10 CPU sandbox. That supports these bounded serial memory-backed
paths only. It does not establish network transport, malformed configuration,
arbitrary thread schedules, performance, full upstream-suite coverage, a universal
no-bug result, discovery recall, or evidence-selector research efficacy. Backend
request counts may depend on background scheduling; they are not speed metrics.
Recheck changed cache/lifecycle contracts rather than weakening the oracle.
