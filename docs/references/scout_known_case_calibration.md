# Known-case calibration: observation helps diagnosis, not repair qualification

This diagnostic was selected **after the owner found and qualified a repair**.
It is not a prospective enrollment, replacement for either frozen pilot, or a
new model discovery. Preserve the [completed v2 null/negative result](scout_source_inception_pilot_v2_results.md).
No new default evidence-selection policy follows from this one case.

## Inputs and cost

Public source: `grantjenks/python-diskcache` at
`ebfa37cd99d7ef716ec452ad8af4b4276a8e2233`. Both inputs contained the same
complete selected `Index` mapping/comparison methods and old `test_index.py`;
other package bodies were omitted explicitly. Neither contained the final
repair, new regression tests or lesson cards. Author-owned #378's distinct
missing-key/sentinel concern was explicitly excluded in both.

The observation arm additionally received 24 actual `eq`/`ne` observations:
empty/populated Index, six other operands, both operators. Healthy dictionary
controls remained in the table. These came from the real pinned package in an
offline, nonroot CPU sandbox with Python 3.12.10, 512 MiB and no GPU. Source
hashes were checked; this was not a full upstream suite or a proposed fix.

Two stateless GLM-5.3 calls requested low effort, one attempt per arm, 120 seconds
per request, 8,192 output tokens and an 80,000-token combined reservation ceiling.
No model retries or corrective prompts. Realized gateway effort, reasoning usage
and prices are unknown. Equal ceilings are not equal realized cost.

| Arm | Input | Output | Reported total | Result |
| --- | ---: | ---: | ---: | --- |
| Source only | 4,236 | 1,041 | 5,277 | Abstained; missed the known nonmapping concern |
| Same source + native table | 5,052 | 1,188 | 6,240 | Recognized concern; repair suggestion remained incomplete |

Each reported 768 cached input tokens, a subset of input rather than an extra
charge to add. Recorded job walls were 9.017 and 9.753 seconds, respectively;
these exclude preparation, policy/duplicate review, native acquisition and owner
assessment. Those costs are unpriced, not zero. Total is 2 calls / 11,517
reported tokens / zero new discoveries or PRs. Both answers passed JSON and
supplied-source-quote checks. Neither was qualified by those checks.

## Independent check of the incomplete suggestion

The observation arm suggested a Mapping guard and claimed inequality would
follow automatically. A separate owner-defined guard-only subclass of the real
pinned Index falsified this: equality returned the peer's equality sentinel,
but inequality returned `False`, not its distinct inequality sentinel. The
inherited Index `__ne__` was still present. The answer also incorrectly asserted
that MutableMapping had no inherited equality; actual resolution was
`Mapping.__eq__`. Original answers were retained, not corrected or retried.

This small executable example illustrates only the language mechanism, **not**
an independent DiskCache qualification. Run its doctests with the standard
library; no model, target import, network, queue or GPU is required:

    >>> class GuardOnly:
    ...     def __eq__(self, other):
    ...         return NotImplemented
    ...     def __ne__(self, other):
    ...         return not self == other
    >>> class Peer:
    ...     def __eq__(self, other):
    ...         return 'peer equality'
    ...     def __ne__(self, other):
    ...         return 'peer inequality'
    >>> left, peer = GuardOnly(), Peer()
    >>> left == peer
    'peer equality'
    >>> left != peer
    False
    >>> peer != left
    'peer inequality'
    >>> class PreserveProtocol(GuardOnly):
    ...     def __ne__(self, other):
    ...         result = self.__eq__(other)
    ...         return result if result is NotImplemented else not result
    >>> PreserveProtocol() != peer
    'peer inequality'
    >>> from collections.abc import Mapping, MutableMapping
    >>> MutableMapping.__eq__ is Mapping.__eq__
    True

```sh
python -B -m doctest docs/references/scout_known_case_calibration.md
```

[Python's operator contract](https://docs.python.org/3.12/reference/datamodel.html#object.__ne__)
and [the pinned ABC implementation](https://github.com/python/cpython/blob/v3.12.10/Lib/_collections_abc.py#L771-L774)
support these mechanics. Preserve supported mapping and order-sensitive controls
in a real repair; do not impose complement semantics on every custom class.

## What this changes, and what it does not

The actionable result is to separate diagnostic recognition from repair
qualification, and include inherited/reflected behavior when choosing a cheap
counterexample. This observation does not show a broken definition selector:
the selected target methods were complete, while external base implementations
were outside the supplied context. Automatically fetching every ancestor or
increasing all prompt budgets is not justified.

The owner knew the outcome and selected the scope, both provider responses have
one sample, the evidence is highly targeted, and the assessor is not independent.
Private captures preserve inputs, original outputs and native run identities;
the language example is reproducible but these model responses are not a
public benchmark dataset. No population recall, causal model superiority,
cost-optimality, PR-yield gain, strong-model comparison or paper claim is supported.

## Separate no-model control: nested annotation scope

This later development check is not another arm or successful repair of the
two-call diagnostic above. A Scout lead inferred that an unresolved inner image
annotation would make an outer kwargs-container `get_type_hints()` call fail.
The [pinned vLLM implementation](https://github.com/vllm-project/vllm/blob/81f7c69577433b938ee16539020792dae37c7d0c/vllm/transformers_utils/processor.py#L323-L354)
instead resolves the outer class-valued annotations, then reads inner field
names without evaluating them. The two levels need separate controls.

This standard-library example is independent of Transformers and vLLM:

    >>> from typing import TypedDict, get_type_hints
    >>> class ImageOptions(TypedDict):
    ...     interpolation: 'NotImportedImageType'
    >>> class ProcessorOptions(TypedDict):
    ...     images_kwargs: ImageOptions
    >>> get_type_hints(ProcessorOptions)['images_kwargs'] is ImageOptions
    True
    >>> try:
    ...     get_type_hints(ImageOptions)
    ... except NameError:
    ...     print('inner field still unresolved')
    inner field still unresolved
    >>> class UnresolvedProcessorOptions(TypedDict):
    ...     images_kwargs: 'NotImportedKwargsClass'
    >>> try:
    ...     get_type_hints(UnresolvedProcessorOptions)
    ... except NameError:
    ...     print('outer annotation unresolved')
    outer annotation unresolved

[CPython's versioned implementation](https://github.com/python/cpython/blob/v3.12.13/Lib/typing.py#L406-L443)
supports the distinction; generic argument resolution is not arbitrary recursive
inspection of every referenced class.

In the existing native Linux/Python 3.12.13, Torch 2.14 CPU environment, the
complete pinned processor module was imported under a private audit name with
the existing package dependencies, not reduced to extracted functions. Ten
checks passed against Transformers 5.19.0: the base class, seven actual Qwen/GLM
kwargs classes, unresolved-inner control and synthetic unresolved-outer control.
No model construction/download or CUDA initialization was involved. The seven
real classes retained the expected dynamic keys; the inner unresolved control
did too. Only the synthetic outer control produced the four-key fallback.

The first diagnostic run retained nine passes and one test failure because it
over-specified which unresolved name would fail first: inherited
`PILImageResampling` preceded the synthetic field. A fresh version corrected that
test expectation, not production code. A static inventory found 118 kwargs
classes in 159 installed processor files; it is not a runtime qualification of
all those classes. Original test/log/hash evidence remains separate.

Decision: do not publish the speculative fix without a supported actual outer
annotation/caller failure on its required dependency version. This is a scoped
negative result, not proof every custom processor or older version works. The
executable example documents a language mechanism; it does not reproduce the
complete target environment, measure Scout benefit, or establish a paper result.

## Separate model calibration: requested definitions are not a complete witness

This later, owner-selected development case concerns repeated polling in
[pinned vLLM ServerRole](https://github.com/vllm-project/vllm/blob/2cea893821861c1007b3c7f1da44f9774bb0c18c/vllm/v1/kv_offload/tiering/p2p/session/server.py).
The fixed question was whether repeated `serve_external_requests()` calls,
without another `LookupMsg`, cumulatively allocate lookup objects or synthetic
contexts. The owner already knew a bounded native negative result; neither
model input received that result, repair, new tests or indexed lesson.

Both arms retained the identical primary excerpt, lines 481–550. The original
follow-up added unrelated API-server and Rust-test excerpts. The other arm
replaced only those two reads with complete `_resolve_pending_lookups` and
`_finalize_lookup` definitions, obtained by the current cached-definition reader.
It did not supply the complete message-ingestion or allocation methods.

The existing Scout CLI made two stateless GLM-5.3 calls, low effort requested,
concurrency two, one attempt per arm, no retries, 120-second request limits,
8,192 output tokens each and an 80,000-token combined reservation ceiling.
These are equal ceilings, not equal input lengths or realized cost.

| Arm | Input | Output | Reported total | Result | Job wall (s) |
| --- | ---: | ---: | ---: | --- | ---: |
| Original follow-up | 4,856 | 782 | 5,638 | Needs context | 8.033 |
| Same primary + requested definitions | 3,324 | 1,291 | 4,615 | Needs context | 12.182 |

Both responses passed the existing JSON/source-quote checks, not native
qualification. Both requested the complete `serve_external_requests` and
`_process_inbound_lookup` definitions before deciding. The targeted arm described
the supplied polling/finalization path more directly but did not reach a terminal
source verdict. Total: two calls, 10,253 reported tokens, zero new discoveries or
PRs. Cached-token counts, realized reasoning effort and prices were not reported;
preparation, native acquisition and owner assessment are outside the job walls.

The independently retained native check used the actual pinned session component
with upstream fake transport/parent helpers: ten existing upstream cases plus
four private diagnostics passed. Repeated polling retained the same lookup and
ID counter, followed by one completion on hit, miss, timeout or finish. This is
not RDMA, real serving, the full suite or a general leak-free proof. Its result
was withheld from both calls and is not an independent assessor's label.

Decision: preserve this null terminal-verdict contrast; do not add another prompt
or replace labels to make the preferred arm win. Correctly fulfilling two
definition requests is not the same as obtaining the complete caller/allocation
witness. A future sequential comparison must account for subsequent reads and
native checks through a stopping decision, rather than score excerpt relevance
as verified bug rejection. One known case does not establish a better policy,
cheaper research, higher PR yield or paper novelty.
