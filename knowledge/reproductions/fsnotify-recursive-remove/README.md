# Separate default reachability from an internal cleanup defect

This bounded reproduction targets **fsnotify/fsnotify at
`20b1e15ef3c70caeb37ea2bd184f48ef8382669e`**, Linux inotify. It is development
evidence, not a vulnerability report, upstream-ready patch or performance result.

There are two distinct observations:

- Production `enableRecurse` is unexported and false. The external client does not
  link `_test.go` initialization: `/...` does not enable recursive watching.
- Upstream's test `init()` enables recursion. Under real event backpressure,
  deleting child directories invalidates their kernel watches before `Remove`.
  The early EINVAL return can leave a live child watch after all Go mappings have
  been removed. This test-only-path defect is not disproved by the default gate.

Use a fresh checkout of that revision. Read its contribution rules before proposing
changes. From the checkout, run the external client without copying it into the
library directory:

```sh
go run /absolute/path/to/default_client.go
```

For the **internal test-only** observation, copy `recursive_remove_test.go` to a
fresh filename in the checkout root, then run:

```sh
go test -race -count=1 -timeout=30s -run '^TestOwnerInternalRecursiveRemoveInvalidation$' .
```

The probe does not modify production source or enable a flag itself. It relies on
the pinned upstream test initialization and checks it explicitly. It creates only
temporary directories and watchers belonging to its process. Each watcher closes;
the observed leftover is until watcher close, not a permanent OS resource leak.
Only `/proc/self/fdinfo` is read. No external service, mount, GPU or syscall-error
mock is used.

The test parks the real event reader, performs real directory removal, then checks
both kernel and Go watch counts. Normal cleanup and invalid-only controls separate
an error return from a leftover resource. The mixed case retains map-order
dependence: at most 16 small attempts are made, and no witness fails the probe
rather than manufacturing a positive result. The stack-based parking observation
can fail on a different compiler/runtime; keep that inconclusive evidence.

`observation.json` is a small sanitized Linux/Go1.25.10 observation, not the full
private validation log or a cross-platform guarantee. Re-run on the relevant
revision and environment. Default behavior and internal behavior need separate
labels; neither alone qualifies a public change. Maintainer scope discussion is
still needed before proposing a repair for an unreleased feature.
