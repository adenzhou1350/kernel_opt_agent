# SJSON in-place string replacement: independent checks

This is a reproduction and review of the existing
[tidwall/sjson issue 85](https://github.com/tidwall/sjson/issues/85), **not a new
discovery or our upstream PR**. The existing author's
[fork PR 2](https://github.com/AdamMagued/sjson/pull/2) is separate from upstream.

Copy `regression_test.go` into a fresh source checkout as
`owner_regression_test.go`, retaining its original `go.mod` and `go.sum`, then run:

```sh
go test -race -count=1 -run '^TestSetBytesOptionsInPlaceEscapedStrings$' .
go test -race -count=1 ./...
```

On upstream `3a21ce7b0cab4e0f0d91eb8db4a3d0434622eeb8`, 16 of the 18
string/byte-value cases fail; the parent test fails too. The ordinary ASCII
controls pass. The optimization hint silently returns the unchanged document
for shorter values requiring marshaling. The tests use valid JSON, an
`encoding/json` value oracle, and preserve an unrelated trailing field. They
include escaped output larger than the replaced value despite a shorter raw input.

On author head `cfb6beb02d7614b2c1fc549cc19e9ea1ef559622`, all 18 cases pass.
However, its full suite plus this regression has 40 passing test nodes and two
failures: **one** invalid-UTF8 subtest and its parent. The expected Go string
contains a literal replacement rune, while `encoding/json.Marshal` emits the
JSON-escaped spelling. With only that expected value changed to the raw string
below, all 42 test nodes pass; author production code is unchanged:

```go
expected: `{"test":"bad\ufffdutf8"}`,
```

Keep the original head's failure separate from the fixture-corrected result.
These were non-root Linux amd64 Go 1.25.10 checks with original dependencies,
not minimum-Go/all-platform CI, benchmarks, an upstream merge or a prospective
evidence-selection experiment. They do not justify a competing PR.
