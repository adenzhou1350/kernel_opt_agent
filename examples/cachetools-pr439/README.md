# Independent review of an existing cachetools optimization

This is supporting evidence for [author PR439](https://github.com/tkem/cachetools/pull/439),
not our implementation, new bug discovery, or a competing PR.

The originally reviewed head could not parse. After the author's fix, exact head
`74d2169cf4721f8d2857d982abe508a805f4bdc5` and its exact base
`9976f1a8076631560f49c5b0dfda7e4d00ee0a4a` each passed the same 338 upstream tests
under native Windows CPython 3.14.3 / pytest 9.1.1 (zero failures, errors or skips).
This is not the full tox, lint, docs, threading or supported-runtime matrix.

An initial baseline capture used the wrong expected JUnit classname and stayed
inconclusive. Its saved XML was subsequently accounted offline with the actual
identity; the baseline was not rerun. That reporting error is not a source failure.

## Small matched measurement

The measured private precursor uses the same timed loops as `benchmark.py`.
Each process imports a selected unchanged source tree; there are 1024 resident
keys, capacity 2048, 10,240 warmup accesses and 262,144 measured accesses. Every
access is a hit. Setup and process startup are excluded from the timed loop.
GC is disabled only during that loop. Each case ran four fresh-process pairs
in B/C, C/B, B/C, C/B order, with no retries or discarded timing observations.
Keep the module-scope loop unchanged when comparing with these numbers: moving
it into a function changes global lookups into locals and changes the benchmark.

| Operation | Keys | Median paired B/C | Pair min–max |
| --- | --- | ---: | ---: |
| `cache[key]` | int | 1.569 | 1.390–1.614 |
| `cache[key]` | str | 1.512 | 1.391–1.590 |
| `cache[key]` | tuple | 1.516 | 1.448–1.658 |
| `cache.get(key)` | int | 1.257 | 1.167–1.345 |
| `cache.get(key)` | str | 1.340 | 1.278–1.598 |
| `cache.get(key)` | tuple | 1.244 | 1.153–1.308 |

Ratios are elapsed baseline / candidate for equal work. These are noisy,
local CPU microbenchmarks, not confidence intervals, author-number replication,
miss-path measurements, whole-application gains or cross-runtime predictions.
No GPU, model calls, WSL or shared-package installation was used.

## Reproduce

Use separate reviewed source roots for the two exact commits. The existing
`scripts/qualification_source_bundle.py` can export raw Git bytes without
Windows checkout conversion. No cachetools installation is necessary.

```text
python -B examples/cachetools-pr439/benchmark.py --package BASELINE/src --sha256 c595cd9ea1ce7e52be423397398f33ad9fb8074d568bd664f229570e97f7a660 --mode getitem --keys int
python -B examples/cachetools-pr439/benchmark.py --package CANDIDATE/src --sha256 b49df7958eab2f282eaae33649a2b0c33ed5855eb2b935e28f387be554095e94 --mode getitem --keys int
```

Repeat with `get` and `str`/`tuple`, reversing arm order between pairs. Record
the emitted Python build and per-process timings; do not compare rates from
different workloads as if they were a matched ratio. The published helper adds
a pre-import hash guard and omits private absolute paths from its output; those
changes are outside the timed region. Check source identity before and after
actual repository tests separately; this helper is not their test runner.
