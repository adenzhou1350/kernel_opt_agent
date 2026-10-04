# Encrypted-object nonce corruption reproduction

This independent native test supplements the **unmerged encryption hunk** in
[aburan28's PR #7441](https://github.com/juicedata/juicefs/pull/7441).
It is not a new discovery or a competing PR. That bundled PR was closed as a
duplicate of [#7425](https://github.com/juicedata/juicefs/pull/7425), which repaired
local-file path containment; its changes do not include the nonce guard.
Check current source and coordinate with the author/maintainer before publication.

Use a fresh disposable JuiceFS checkout at
`adcca1cc61bb4d668a945d64b2e176b44ac8e5b5`.
Copy `encrypted_nonce_test.go` into `pkg/object/` without overwriting a file.
Use the normal package/dependencies, not an extracted function or fake cipher.
This test reuses the repository's key-generation fixture and the real memory
backend, whole-object wrapper, chunked reader and AEAD implementations.
Task-private CPU Go caches can be provisioned separately and then used offline.

```sh
go test -json -count=1 -timeout=60s ./pkg/object \
  -run '^TestEncryptedStoreNonceCorruption$'
```

At that unchanged commit, the 30 nonce cases fail because the actual reader
panics: three algorithms (AES-GCM/RSA, ChaCha20-Poly1305/RSA, SM4-GCM/SM2),
two wrappers and lengths 0/1/11/13/255. The six same-length ciphertext-corruption
controls return errors normally; unmodified range reads are also checked.
The 700-byte plaintext lets all these malformed nonce lengths pass the existing
outer bounds check and reach the cipher, including 255.

In a separate checkout apply only PR #7441's three-line `encrypt.go` guard
immediately before `aead.Open`: reject `len(nonce) != aead.NonceSize()` with an
error. Its production file at commit `d85800b65c34e190a058d6662251666cc58357c7`
is Git blob `b88ecd19b40294373d599e0bfbda590b119cb61f`. Do not apply the
unrelated filestore refactor or imply that the complete old PR was qualified.
Run the same test, then repeat it with `-race -count=5`.

Development verification on Linux/Go 1.25.10: unchanged source 30 failing +
6 passing distinct leaf cases; the guard 36 passing, and five race repeats
180 passing observations (not 180 independent cases). The applicable existing
crypto selection passes; an ordinary object-package run passes with 38
backend/environment skips and `TestDisk2` excluded for its separately observed
root-permission failure. Vet passes. Full `make test.pkg`/gluster, real cloud
accounts, security impact, throughput and model/PR conversion are not qualified.
Raw output, addresses and caches stay private.
