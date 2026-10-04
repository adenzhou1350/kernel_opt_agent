# Native HTTP error classification boundary

Scope: LanceDB Rust client at
`7f5933594f42eeeec1ce73a7ce8e0cd0113cbd82`, remote feature.
[Issue 4394](https://github.com/lancedb/lancedb/issues/4394) reports local/remote
Python exception differences and explicitly asks for team input. Its invalid-input
and tag-conflict examples share HTTP 400 and application code 13, although their
local Python exception classes differ.

`http-error-boundary.rs` is a diagnostic module to append to
`rust/lancedb/src/remote/client.rs` in a disposable checkout of that commit.
It calls the actual native client and its repository-provided HTTP mock.
Production behavior is unchanged; four tests assert preserved request ID, status
and body for both code-13 examples, unstructured 400 and non-400 controls.

Use an existing compatible Rust/protoc environment and the repository's profiles:

```sh
cargo fmt --all
cargo test --locked --profile ci -p lancedb --no-default-features --features remote --lib remote::client::scout_http_error_boundary:: -- --nocapture
```

Add `--offline` only when the exact locked dependencies are already cached.
Check that **four named tests execute**, not merely that Cargo exits successfully.

Observed: 4 passed, 0 failed, 0 ignored; compilation and execution took about
102 seconds using a previously built dependency cache. This is not a cold-setup
cost or a performance comparison. Test response bodies are hand-authored
diagnostic fixtures following the issue's envelope shape, not captured server
responses. No live Cloud request or rebuilt Python/Node binding was tested.

The client preserves all these responses as `Error::Http`. The Python bridge
maps that variant to `HttpError`, while `InvalidInput` maps to `ValueError`.
A blanket 400/code-13 mapping cannot preserve the issue's reported tag-conflict
semantics. Also, the Rust `InvalidInput` variant has only a message, whereas
`Http` carries request ID and status. A repair needs an agreed discriminating
server/API contract and metadata-preservation behavior, not string matching or
a blanket exception-inheritance change. This diagnostic does **not** establish
that the current behavior is desirable or that the issue is resolved.
