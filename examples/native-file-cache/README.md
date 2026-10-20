# Public byte-range cache oracle

When a cache lead concerns byte boundaries, exercise the actual buffered-file
caller before changing its internals. This small standard-library test imports
the real fsspec package from an explicitly supplied, reviewed source root and
uses a real `MemoryFileSystem`. It compares seek/read/readinto results and file
positions with `io.BytesIO`. The original block-cache checks also reject empty
or out-of-file backend fetches; other cache policies retain their own backend
range contracts. No cache algorithm is copied or replaced.

```sh
python -B examples/native-file-cache/check.py --source /path/to/reviewed/filesystem_spec
# Add serial none/bytes (trimmed and untrimmed)/readahead/first/all/mmap checks:
python -B examples/native-file-cache/check.py --source /path/to/reviewed/filesystem_spec --suite all
# Separately exercise the adaptive cache through its real background producer:
python -B examples/native-file-cache/check.py --source /path/to/reviewed/filesystem_spec --suite adaptive
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

The extended `--suite all` audit at
[941e6f9](https://github.com/fsspec/filesystem_spec/blob/941e6f910a1d4683f31a56a9adf78dccb50ecdcf/fsspec/caching.py)
passed nine test methods, 624 size/block/capacity/configuration combinations,
42,432 read checks and 39,936 position checks on both Windows/Python3.14.3 and
offline Linux/Python3.12.10. Both imported the same raw-Git `caching.py` bytes;
the example checks the selected cache class and nonempty mmap disposal too.
`--suite simple` selects only the seven added configurations. These passes found
no new defect; they are not a reason to submit a production change. KnownParts
zero-fill semantics and adaptive paths are not covered by that `all` cohort.

For the Linux replay, an initial package-wide archive included an unrelated
large upstream test cassette and hit the sandbox's file-size limit before any
oracle test ran. A fresh raw-Git bundle containing only package Python files
passed under the unchanged limits. Keep extraction and execution in the same
container when using an ephemeral directory; do not claim upstream pytest
coverage from that production-only export.

## Adaptive reads: avoid a warm-buffer-only oracle

The separate `--suite adaptive` cohort uses the same pinned 941e6f9 source and
real buffered-file/memory-backend caller. It requires an active prefetcher, not
the synchronous fallback. Across 288 size/block/concurrency/prefetch-limit cases
it checks 21,024 reads and 19,872 file positions on both Windows/Python3.14.3 and
offline Linux/Python3.12.10. Concurrency settings are 1 and 4; limits are 1 byte,
16 bytes and the default. Sizes remain 0..97 bytes: this does not cover the
5 MiB chunk or 64 MiB variable-I/O regimes, network failures or racing callers.

An initial version began with a read-all and passed 19,584 checks while making
only 264 backend calls: the entire tiny file could stay in one buffer. The final
cohort starts with bounded sequential reads and backward/forward seeks, asserts
an actual partial backend range for files larger than the block, then runs the
existing fixed-seed traces. It made 1,128 backend calls in each development run
and found no byte/position mismatch. Counts demonstrate exercised requests, not
complete branch/schedule coverage, speed, recall or new upstream defects. The
initial capture is retained; more assertions alone would not establish a better
oracle. No production change or new fsspec PR is justified by these passes.

## Cancellation/retry: distinguish data from position

```sh
python -B examples/native-file-cache/cancellation.py --source /path/to/reviewed/filesystem_spec
```

This separate standard-library probe calls the real `BackgroundPrefetcher.afetch`
with an event-gated async byte source. It checks cancellation during an inflight
read, a lock waiter, partial assembly, and a soft seek after partial skipping.
Every offset holds a different byte, and retried reads must equal the original
range. Teardown releases gates, joins owned readers, closes the prefetcher and
checks its queue/tasks. It does not replace the actual prefetch implementation.

All four cases passed on Windows/Python3.14.3 and isolated Linux/Python3.12.10
against raw 941e6f9 sources. The first private version timed out before the
soft-seek cancellation: it had primed too few reads to schedule the gated block.
The corrected fixture waits for actual backend entry and checks the intermediate
offset before cancelling; the original setup failure is not a target bug.
These four controlled schedules found no incorrect retry bytes. They do not
qualify physical network/MRD cancellation, the public buffered-file wrapper,
arbitrary interleavings, performance or the complete upstream suite. Revalidate
the priming schedule when producer batching changes; a preparation timeout is
inconclusive, not evidence to patch production or relax the byte oracle.
