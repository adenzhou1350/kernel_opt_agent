package sjson

import (
	"encoding/json"
	"testing"
)

func TestSetBytesOptionsInPlaceEscapedStrings(t *testing.T) {
	const input = `{"key":"old-long-value","tail":17}`
	values := []struct {
		name  string
		value string
	}{
		{"plain", "short"},
		{"quote", `a"b`},
		{"backslash", `a\b`},
		{"newline", "a\nb"},
		{"tab", "a\tb"},
		{"nul", "a\x00b"},
		{"unicode", "你好"},
		{"emoji", "😀"},
		{"escaped_growth", `""""""""""""""`},
	}
	for _, tc := range values {
		for _, bytesValue := range []bool{false, true} {
			name := tc.name + "/string"
			var value interface{} = tc.value
			if bytesValue {
				name = tc.name + "/bytes"
				value = []byte(tc.value)
			}
			t.Run(name, func(t *testing.T) {
				encoded, err := json.Marshal(tc.value)
				if err != nil {
					t.Fatal(err)
				}
				want := `{"key":` + string(encoded) + `,"tail":17}`
				for _, inplace := range []bool{false, true} {
					opts := &Options{Optimistic: true, ReplaceInPlace: inplace}
					got, err := SetBytesOptions([]byte(input), "key", value, opts)
					if err != nil {
						t.Fatal(err)
					}
					if string(got) != want {
						t.Fatalf("inplace=%v: got %q, want %q", inplace, got, want)
					}
				}
			})
		}
	}
}
