# An implicit tool boundary must precede a later reasoning end tag

Independent component review of the author's [vLLM PR62744](https://github.com/vllm-project/vllm/pull/62744),
not a competing fix or model-serving qualification. The PR usefully accepts
cross-effort end tags. This witness checks that doing so does not reinterpret
tool content after reasoning has already ended at `<ifm|tool_calls>`.

## Reproduce with the actual package

Reuse a task-private CPU vLLM installation and the bounded native capture in
[the native validation guide](../../docs/scout_native_cpu_validation.md). Do not
overwrite a shared installation, fetch weights or start a GPU server. The small
default sandbox does not contain this complete package environment.

The observed pair used separate copies of the official
`0.32.1rc1.dev36+ge68efc685` CPU distribution, Python3.12/Torch2.14.0+cpu. Overlay
only `vllm/reasoning/k2_horizon_reasoning_parser.py` from:

- parent `7b569ec8953cf8099638a6d2ee1e915b75867c3a`;
- author `8e4b43e87bd751e864a2148f75f56ca630d0bdcc`.

Use the author's complete [unit file at that head](https://github.com/vllm-project/vllm/blob/8e4b43e87bd751e864a2148f75f56ca630d0bdcc/tests/reasoning/test_k2_horizon_reasoning_parser.py)
unchanged, then append [extra_tests.py.fragment](extra_tests.py.fragment) to a
fresh private `test_k2_boundary.py`. This is the exact added fragment used in
both arms. It reuses the author's synthetic tokenizer and request helpers; no
mock parser or copied parser implementation replaces the real imported class.

Set `PYTHONPATH` to the private package's parent, `EXPECTED_PARSER` to its exact
parser file and `EXPECTED_PARSER_SHA256` to that file's reviewed SHA256. Keep a
private HOME/TMPDIR/cache, CPU-only visibility, offline Hugging Face/uv settings
and the existing CPU distribution's private OpenMP library. Through that venv:

```text
uv --no-config run --no-project --offline --python /private/venv/bin/python python -B -m pytest -c /dev/null --rootdir /private/case /private/case/test_k2_boundary.py -q -s --tb=short
```

The tests compare `medium` and `low` with this identical constructed text:

```text
plan<ifm|tool_calls><ifm|tool_call>ping{"text":"</ifm|think>"}</ifm|tool_call></ifm|tool_calls>
```

The expected reasoning is `plan`; content starts at `<ifm|tool_calls>` and is
preserved intact. Both non-streaming and streaming extraction should retain
that split. Stream partitions are one delta, individual characters, and a split
at offset19 (inside the opening tool marker, despite its fixture mode label).
The parser's actual streaming method ignores the token-ID arguments in this
path; this component check does not simulate the entire tokenizer/engine stack.

## Observed complete inventories

| Same test bytes, 21 executions per arm | Parent | Author head |
| --- | ---: | ---: |
| Author's unchanged suite | 17 passed, 2 failed | 19 passed |
| Added implicit-boundary and partition checks | 2 passed | 2 failed |

The original parent failures are the expected `medium`/`low` cross-effort
closing-tag regressions fixed by this PR. The author's new failures are different:
non-streaming and one-delta streaming treat the later `</ifm|think>` inside the
tool content as the boundary, but characterwise streaming already closed at the
earlier tool marker and preserves the content. `_split_model_output` and the
streaming buffer branch prioritize any explicit end over the earlier implicit
boundary. This is a constructed component regression, not a claim that real
K2 model output commonly contains this argument or that the whole PR is invalid.

Both arms used identical native libraries and test bytes, separate processes,
two-CPU affinity and a 12 GiB address-space limit; captures took 9.481/9.491 wall
seconds. No network, GPU, installation, build or shared-service change; source
digests unchanged during tests; no runner-enforced post-exit group cleanup.
The project-specific `skip_global_cleanup` mark is unknown when this unit file
is run outside the project conftest, and that warning is retained. Torch emitted
shared deprecation warnings too. No full-source build, official CI, full parser
suite, real-tokenizer/model evaluation, incidence or performance claim follows.

This manual check was prompted by a fresh Scout answer that failed literal quote
validation by dropping Markdown backticks. That answer remains FAILED and charged
6,758 reported tokens; it was not repaired into a valid discovery. The native
review and this new boundary counterexample are separately acquired owner work,
not a prospective trial, measured selection-policy gain or new authored PR.

## Follow-up: author's earliest-boundary repair

On 2026-10-21 the author updated the existing PR to
[`7226521fdfb759960c1f1b171e74d76735421678`](https://github.com/vllm-project/vllm/commit/7226521fdfb759960c1f1b171e74d76735421678).
Independent fresh-process checks reused the same CPU distribution and original
21-test bytes, not a rewritten witness:

| Exact author parser overlay | Passed | Failed | Skipped/errors |
| --- | ---: | ---: | ---: |
| Previous `8e4b43e` | 19 | 2 | 0 |
| Updated `7226521` | 21 | 0 | 0 |

The previous failures are exactly the two added checks above. The new implementation
selects the earliest boundary and retains tool content when the tool marker comes
first. A separate fresh process ran the updated author's entire
[25-case unit file](https://github.com/vllm-project/vllm/blob/7226521fdfb759960c1f1b171e74d76735421678/tests/reasoning/test_k2_horizon_reasoning_parser.py)
plus the unchanged two-check fragment: all27 passed without skips/errors.
That added suite includes all three efforts and both boundary orders.

Native report/log hashes and complete inventories were checked, parser/test bytes
did not change during execution, and the original installed package remained
unchanged. The captures took9.430/9.492/9.478 wall seconds with no required owned
process-group cleanup. The existing unknown project-mark and Torch warnings were
retained. These remain task-private module overlays with a synthetic tokenizer,
not a complete source build, current full test matrix, real-model incidence,
CUDA/server qualification or merge approval. The result supports the author's
existing repair rather than another competing PR or a claimed Scout discovery.
