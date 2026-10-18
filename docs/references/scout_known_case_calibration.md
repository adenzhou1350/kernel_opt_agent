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
