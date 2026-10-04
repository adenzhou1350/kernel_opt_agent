/*
 * JuiceFS, Copyright 2026 Juicedata, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package object

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestEncryptedStoreNonceCorruption(t *testing.T) {
	cases := []struct {
		name string
		kek  string
		algo string
	}{
		{"rsa_aesgcm", "rsa", AES256GCM_RSA},
		{"rsa_chacha20", "rsa", CHACHA20_RSA},
		{"sm2_sm4gcm", "sm2", SM4GCM},
	}
	ctx := context.Background()
	want := bytes.Repeat([]byte("payload"), 100)
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			dc, err := NewDataEncryptor(NewKeyEncryptor(genPrivateKey(c.kek)), c.algo)
			require.NoError(t, err)
			for _, chunked := range []bool{false, true} {
				t.Run(fmt.Sprintf("chunked=%t", chunked), func(t *testing.T) {
					backend, err := CreateStorage("mem", "", "", "", "")
					require.NoError(t, err)
					var store ObjectStorage = NewEncrypted(backend, dc)
					header := 0
					if chunked {
						store = NewChunkedEncrypted(backend, dc)
						header = chunkHeaderSize
					}
					require.NoError(t, store.Put(ctx, "key", bytes.NewReader(want)))
					r, err := backend.Get(ctx, "key", 0, -1)
					require.NoError(t, err)
					original, err := io.ReadAll(r)
					require.NoError(t, err)
					require.NoError(t, r.Close())
					for _, nonceLen := range []byte{0, 1, 11, 13, 255} {
						t.Run(fmt.Sprintf("nonce=%d", nonceLen), func(t *testing.T) {
							bad := append([]byte(nil), original...)
							bad[header+2] = nonceLen
							require.NoError(t, backend.Put(ctx, "bad", bytes.NewReader(bad)))
							require.NotPanics(t, func() {
								r, err := store.Get(ctx, "bad", 0, -1)
								if err == nil {
									defer r.Close()
									_, err = io.ReadAll(r)
								}
								require.Error(t, err)
							})
						})
					}
					// Reject authenticated-payload corruption without changing the nonce size.
					t.Run("ciphertext", func(t *testing.T) {
						bad := append([]byte(nil), original...)
						keyLen := int(bad[header])<<8 + int(bad[header+1])
						bad[header+3+keyLen+int(bad[header+2])] ^= 1
						require.NoError(t, backend.Put(ctx, "bad", bytes.NewReader(bad)))
						r, err := store.Get(ctx, "bad", 0, -1)
						if err == nil {
							_, err = io.ReadAll(r)
							require.NoError(t, r.Close())
						}
						require.Error(t, err)
					})
					r, err = store.Get(ctx, "key", 3, 17)
					require.NoError(t, err)
					got, err := io.ReadAll(r)
					require.NoError(t, err)
					require.NoError(t, r.Close())
					require.Equal(t, want[3:20], got)
				})
			}
		})
	}
}
