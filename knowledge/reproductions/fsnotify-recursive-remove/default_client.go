package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/fsnotify/fsnotify"
)

// This is an external client: the package's test-only init is not linked.
func main() {
	root, err := os.MkdirTemp("", "fsnotify-public-recursion-")
	must(err)
	defer os.RemoveAll(root)
	child := filepath.Join(root, "child")
	must(os.Mkdir(child, 0700))
	w, err := fsnotify.NewWatcher()
	must(err)
	defer w.Close()
	alias := filepath.Join(root, "...")
	if err = w.Add(alias); err == nil {
		panic("nonexistent ellipsis path unexpectedly enabled recursion")
	}
	if len(w.WatchList()) != 0 {
		panic("failed Add left a watch")
	}
	must(w.Add(root))
	if len(w.WatchList()) != 1 {
		panic("ordinary Add created descendant watches")
	}
	must(w.Add(child))
	if len(w.WatchList()) != 2 {
		panic("explicit child Add failed")
	}
	must(w.Remove(root))
	remaining := w.WatchList()
	if len(remaining) != 1 || remaining[0] != child {
		panic(fmt.Sprintf("ordinary Remove must retain separately watched child: %v", remaining))
	}
	must(w.Remove(child))
	if len(w.WatchList()) != 0 {
		panic("explicit cleanup left a watch")
	}
	must(w.Close())

	// On Linux an actual directory named ... is literal, not a recursive alias.
	must(os.Mkdir(alias, 0700))
	w2, err := fsnotify.NewWatcher()
	must(err)
	defer w2.Close()
	must(w2.Add(alias))
	literal := w2.WatchList()
	sort.Strings(literal)
	if len(literal) != 1 || literal[0] != alias {
		panic("literal ellipsis watch changed semantics")
	}
	must(w2.Remove(alias))
	if len(w2.WatchList()) != 0 {
		panic("literal cleanup left a watch")
	}
	must(json.NewEncoder(os.Stdout).Encode(map[string]any{
		"status":                                  "PASS_PUBLIC_DEFAULT_NONRECURSIVE_BOUNDARY",
		"missing_ellipsis_add_rejected":           true,
		"ordinary_parent_add_watch_count":         1,
		"explicit_parent_child_add_watch_count":   2,
		"remove_parent_preserves_explicit_child":  true,
		"literal_ellipsis_directory_is_one_watch": true,
		"final_watch_counts":                      []int{0, 0},
		"production_files_modified":               false,
		"test_only_init_linked":                   false,
	}))
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}

