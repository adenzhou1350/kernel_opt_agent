//go:build !nogs

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
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sort"
	"sync"
	"testing"
	"time"

	"cloud.google.com/go/storage"
	"google.golang.org/api/option"
)

func TestListAllPreservesGCSPageTokenAcrossRetries(t *testing.T) {
	allKeys := make([]string, 2*maxResults+1)
	for i := range allKeys {
		allKeys[i] = fmt.Sprintf("key-%05d", i)
	}
	for _, failures := range []int{0, 1, 2} {
		t.Run(fmt.Sprintf("failures_%d", failures), func(t *testing.T) {
			var mu sync.Mutex
			var tokens []string
			remaining := failures
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mu.Lock()
				defer mu.Unlock()
				page := r.URL.Query().Get("pageToken")
				tokens = append(tokens, page)
				w.Header().Set("Content-Type", "application/json")
				if page == "one" && remaining > 0 {
					remaining--
					w.WriteHeader(http.StatusServiceUnavailable)
					fmt.Fprint(w, `{"error":{"code":503,"message":"temporary listing failure"}}`)
					return
				}
				start := 0
				switch page {
				case "one":
					start = maxResults
				case "two":
					start = 2 * maxResults
				default:
					// GCS startOffset is inclusive when the page token is lost.
					start = sort.SearchStrings(allKeys, r.URL.Query().Get("startOffset"))
				}
				end := start + maxResults
				if end > len(allKeys) {
					end = len(allKeys)
				}
				var next string
				if end < len(allKeys) {
					if end == maxResults {
						next = "one"
					} else {
						next = "two"
					}
				}
				// The real SDK fills a requested iterator page, so full HTTP pages
				// are needed to fail a subsequent List call rather than the first.
				items := make([]map[string]string, 0, end-start)
				for _, key := range allKeys[start:end] {
					items = append(items, map[string]string{"name": key, "size": "1", "updated": "2026-01-01T00:00:00Z"})
				}
				_ = json.NewEncoder(w).Encode(map[string]interface{}{
					"nextPageToken": next,
					"items":         items,
				})
			}))
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			client, err := storage.NewClient(ctx, option.WithEndpoint(server.URL), option.WithHTTPClient(server.Client()), option.WithoutAuthentication())
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			client.SetRetry(storage.WithPolicy(storage.RetryNever))
			out, err := ListAll(ctx, &gs{clients: []*storage.Client{client}, bucket: "bucket"}, "", "", false, true)
			if err != nil {
				t.Fatal(err)
			}
			var keys []string
			failed := false
			for item := range out {
				if item == nil {
					failed = true
				} else {
					keys = append(keys, item.Key())
				}
			}
			mu.Lock()
			defer mu.Unlock()
			want := []string{"", "one"}
			for i := 0; i < failures; i++ {
				want = append(want, "one")
			}
			want = append(want, "two")
			if failed || fmt.Sprint(keys) != fmt.Sprint(allKeys) || fmt.Sprint(tokens) != fmt.Sprint(want) {
				t.Fatalf("key count=%d (want %d) failure=%t page tokens=%q, want %q", len(keys), len(allKeys), failed, tokens, want)
			}
		})
	}
}
