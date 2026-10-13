//go:build linux && !appengine

package fsnotify

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
)

func ownerKernelWatchCount(t *testing.T, fd int) int {
	t.Helper()
	body, err := os.ReadFile(fmt.Sprintf("/proc/self/fdinfo/%d", fd))
	if err != nil {
		t.Fatal(err)
	}
	return strings.Count(string(body), "inotify wd:")
}

func ownerWaitForEventBackpressure(t *testing.T) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		buffer := make([]byte, 256<<10)
		n := runtime.Stack(buffer, true)
		for _, frame := range strings.Split(string(buffer[:n]), "\n\n") {
			if strings.Contains(frame, ".sendEvent(") && strings.Contains(frame, ".readEvents(") {
				return
			}
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("could not establish real readEvents/sendEvent backpressure; no injected error used")
}

// Uses upstream's existing test-only recursion enablement, not a source change.
// Closing the task-owned watcher always releases any observed leftover watches.
func TestOwnerInternalRecursiveRemoveInvalidation(t *testing.T) {
	if !enableRecurse {
		t.Fatal("upstream test-only init was not active")
	}
	trial := func(label string, invalidate int, validChildren int) (int, error) {
		root := t.TempDir()
		children := make([]string, invalidate+validChildren)
		for i := range children {
			children[i] = filepath.Join(root, fmt.Sprint(i))
			if err := os.Mkdir(children[i], 0700); err != nil {
				t.Fatal(err)
			}
		}
		w, err := NewWatcher()
		if err != nil {
			t.Fatal(err)
		}
		defer w.Close()
		if err := w.Add(filepath.Join(root, "...")); err != nil {
			t.Fatal(err)
		}
		b := w.b.(*inotify)
		if err := os.WriteFile(filepath.Join(root, "park-reader"), nil, 0600); err != nil {
			t.Fatal(err)
		}
		ownerWaitForEventBackpressure(t)
		for _, dir := range children[:invalidate] {
			if err := os.Remove(dir); err != nil {
				t.Fatal(err)
			}
		}
		before := ownerKernelWatchCount(t, b.fd)
		if before != 1+validChildren {
			t.Fatalf("%s: expected actual kernel invalidation, kernel count=%d", label, before)
		}
		err = w.Remove(root)
		remaining := ownerKernelWatchCount(t, b.fd)
		if count := len(w.WatchList()); count != 0 {
			t.Fatalf("cache not cleared: %d", count)
		}
		t.Logf("label=%s invalidated=%d valid_children=%d kernel_before=%d kernel_after=%d cache_after=0 remove_error=%v", label, invalidate, validChildren, before, remaining, err)
		return remaining, err
	}
	if left, err := trial("all-valid-control", 0, 3); err != nil || left != 0 {
		t.Fatalf("normal recursive cleanup failed: left=%d err=%v", left, err)
	}
	if left, err := trial("error-with-no-live-child-control", 3, 0); !errors.Is(err, syscall.EINVAL) || left != 0 {
		t.Fatalf("invalid-only control unexpected: left=%d err=%v", left, err)
	}
	for round := 0; round < 16; round++ {
		left, err := trial(fmt.Sprintf("mixed-round-%d", round), 8, 1)
		if !errors.Is(err, syscall.EINVAL) {
			t.Fatalf("expected real invalidation EINVAL, got %v", err)
		}
		if left > 0 {
			t.Log("OBSERVED_TEST_ONLY_RECURSIVE_KERNEL_WATCH_REMAINS_UNTIL_CLOSE")
			return
		}
	}
	t.Fatal("no mixed-order counterexample in bounded 16 trials; do not label the hypothesis confirmed")
}

