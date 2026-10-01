# Native backend-identity counterexample

Based on [AnyIO #1353](https://github.com/agronholm/anyio/issues/1353).
This is a reproduction, not a competing implementation of existing PR #1354.

Use a task-private Python 3.12 environment and install:

```sh
python -m pip install anyio==4.15.1 pytest==9.1.1 hypothesis==6.168.3 trio==0.34.0
python -m pytest examples/scout-native-anyio/test_backend_identity.py -q
REVERSE_BACKEND_ORDER=1 python -m pytest examples/scout-native-anyio/test_backend_identity.py -q
```

The final command uses POSIX environment syntax; on PowerShell set
`$env:REVERSE_BACKEND_ORDER = '1'` before the second invocation.

The Hypothesis case labelled with the second backend should fail: it executes
on the first backend. Both plain tests should pass. Reversing order in a fresh
process reverses the mismatch. The immutable session-scoped name fixture avoids
Hypothesis's function-scoped-fixture health check without suppressing it.

No sockets, external requests, native build or GPU are required by these tests.
Package download is a separate setup cost. This release-level counterexample
does not qualify current main or PR #1354, measure recall or establish a general
fault in parametrized testing. Use it to check a verification assumption, not to
manufacture a community PR or count intentional failures as successful CI.
