# Native GCS pagination retry reproduction

This is a supplemental reproduction for the existing
[JuiceFS PR #7578](https://github.com/juicedata/juicefs/pull/7578), not a competing
fix or a new PR candidate. It exercises actual `object.ListAll`, `gs.List` and
the pinned Google Cloud Storage Go SDK against a loopback HTTP fixture. No real
cloud credentials, bucket, GPU, service interruption or Python model is involved.

## Scope and reproduction

Use a fresh disposable JuiceFS checkout at
`adcca1cc61bb4d668a945d64b2e176b44ac8e5b5`. Put
`listall_page_token_test.go` into its `pkg/object/` directory, leaving the
production source unchanged for the failing control. The pinned module uses
`cloud.google.com/go/storage v1.48.0` and `google.golang.org/api v0.210.0`.
Development verification used Go 1.25.10 on an authorized Linux CPU worker.

Use task-private Go build/module caches and the repository's normal dependencies.
Provision and verify them separately; with a complete cache the run can stay
offline. Do not overwrite an existing test or another task's checkout. Then run:

```sh
go test -json -count=1 -timeout=45s ./pkg/object \
  -run '^TestListAllPreservesGCSPageTokenAcrossRetries$'
```

The zero-error subtest must pass. The one-error and two-error subtests must fail
on that unchanged control. At one error, 20,000 of 20,001 objects are emitted
before the inclusive restart repeats the preceding key and produces the error
sentinel. At two errors, the retry itself loses the input token: only 10,000
objects are emitted. The test checks both exact keys and the request token
sequence, not merely process exit or goroutine termination.

For the repaired comparison apply **only** PR #7578's production assignment:
the retry call writes its returned cursor to `nextToken2`, not `nextToken`.
Keep the input token unchanged through retries, and publish the returned token
only after success. Run the same test in a separate checkout/output:

```sh
go test -json -race -count=3 -timeout=45s ./pkg/object \
  -run '^TestListAllPreservesGCSPageTokenAcrossRetries$'
```

Development observation: three distinct cases (zero/one/two failed attempts)
pass; the race command reports 12 passing terminal test events because it
includes parent tests and three repeats, not 12 independent cases. This checks
the replayed production hunk against this native SDK path; it does not run the
entire older PR head or every backend. Raw outputs, worker addresses and caches
stay private. No cloud-service, throughput or automatic PR-readiness claim.

## Why the fixture uses full pages

`iterator.NewPager(..., maxResults, token).NextPage` fills the requested page,
potentially issuing several HTTP requests inside one `gs.List`. A one-object
HTTP page followed by an error therefore fails the **initial** `ListAll` call;
it never reaches the pagination retry under investigation. That first failed
prototype was retained as a test-design negative, not a product regression.

The fixture supplies two complete 10,000-object pages and a final one-object
page. The [GCS list contract](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/list)
defines `startOffset` as inclusive; the mock honors that restart behavior.
SDK automatic retries are explicitly disabled with `RetryNever`, so injected
503s reach JuiceFS's own retry loop. The mathematical page layout, actual SDK
page aggregation, and the outer producer's retry boundary must all agree.

This example makes that boundary reusable. It does not establish model recall,
PR conversion, cost savings, experimental generalization or paper novelty.
