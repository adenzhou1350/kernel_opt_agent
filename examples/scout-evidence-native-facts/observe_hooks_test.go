package mapstructure

import (
	"encoding/json"
	"fmt"
	"reflect"
	"testing"
)

// This observer deliberately records panics instead of treating them as passes
// for the repaired contract. The upstream regression tests are separate.
func TestObserveHookOutputs(t *testing.T) {
	observe := func(fn func() (any, error)) (out string) {
		defer func() {
			if recover() != nil {
				out = "PANIC"
			}
		}()
		value, err := fn()
		if err != nil {
			return "ERROR"
		}
		if value == nil {
			return "NIL"
		}
		return fmt.Sprint(value)
	}
	identity := func(f reflect.Kind, t reflect.Kind, data any) (any, error) {
		return data, nil
	}
	addFoo := func(f reflect.Kind, t reflect.Kind, data any) (any, error) {
		return data.(string) + "foo", nil
	}
	addBar := func(f reflect.Kind, t reflect.Kind, data any) (any, error) {
		return data.(string) + "bar", nil
	}
	values := []string{
		observe(func() (any, error) {
			return DecodeHookExec(ComposeDecodeHookFunc(identity, identity), reflect.Value{}, reflect.ValueOf(""))
		}),
		observe(func() (any, error) {
			return DecodeHookExec(ComposeDecodeHookFunc(addFoo, addBar), reflect.ValueOf(""), reflect.ValueOf(""))
		}),
		observe(func() (any, error) {
			return DecodeHookExec(ComposeDecodeHookFunc(), reflect.Value{}, reflect.ValueOf(""))
		}),
	}
	if values[1] != "foobar" {
		t.Fatalf("ordinary composition control failed: %q", values[1])
	}
	body, err := json.Marshal(values)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Printf("OBSERVED_VALUES=%s\n", body)
}
