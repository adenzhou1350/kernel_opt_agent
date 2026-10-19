# Check the fallback predicate before proposing an index repair

This small native witness checks an allegation about Mooncake's unchanged
[range-index header](https://github.com/kvcache-ai/Mooncake/blob/1f65cf13c9f886f8db8b88b7733367b18340ebf0/mooncake-transfer-engine/include/buffer_range_index.h)
and its real
[caller guard](https://github.com/kvcache-ai/Mooncake/blob/1f65cf13c9f886f8db8b88b7733367b18340ebf0/mooncake-transfer-engine/src/transport/rdma_transport/rdma_transport.cpp#L65-L73).
It includes the real complete header; it does not copy its algorithm or stand in
for the RDMA transport. Plain `{addr, length}` records instantiate the actual
template without transport/build dependencies.

For equal starts and a positive-length record followed by a zero-length record,
the overlap check compares the second start with the first **exclusive end**,
not just its start. It reports overlap, so the caller uses its linear fallback.
Reversing those records leaves the positive record as the index candidate.
The alleged fast-path miss therefore does not follow for these bounded inputs.
This does not prove that zero-length MR registration is supported, overflowing
addresses are valid, or every transport/lifetime case is correct.

In an existing authorized task-private Linux directory, with a reviewed local
Mooncake clone and this example's `check.cpp`:

```sh
git -C "$MOONCAKE_REPO" show 1f65cf13c9f886f8db8b88b7733367b18340ebf0:mooncake-transfer-engine/include/buffer_range_index.h > buffer_range_index.h
printf '%s\n' '0a8afa863c29c0ccbc3a512c2939a874b0c11d30cef07893e87d16225b5077d2  buffer_range_index.h' | sha256sum -c -
g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all -I . check.cpp -o check
./check
```

Use fresh output paths and the existing reviewed execution limits. Do not add
`-DNDEBUG`: assertions are the observations. This witness ran on Linux/G++11.5
with one CPU, a 512 MiB address-space cap, 15-second CPU cap and process-group
deadlines. Compilation and execution exited zero without sanitizer output;
source hashes were unchanged and owned process groups exited. This is raw
component evidence, not GoogleTest, a full Mooncake build, RDMA, performance,
discovery recall or a paper result. No local WSL is required.

The originating model response remains failed because it cited an unsupplied path.
Do not fix that URL into an accepted answer. Independently checking its mechanism
is separate owner work, with its own cost; it does not rehabilitate that result.
