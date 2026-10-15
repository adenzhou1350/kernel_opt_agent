"""Offline source coverage scheduling; no semantic uniqueness assertion."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_source_order import (
    changed_first_paths,
    family_round_robin,
    reset_legacy_cursor,
)


def variant(architecture, index, kind="kernel"):
    return f"src/{architecture}/op_{index:020x}_{kind}.cu"


class FamilyOrderTests(unittest.TestCase):
    def test_prefix_covers_families_without_dropping_variants(self):
        paths = [variant("sm100", i) for i in range(5)] + [
            variant("sm103", 7),
            "src/wrapper.py",
        ]
        ordered = family_round_robin(paths)
        self.assertEqual(ordered[:3], [paths[0], paths[-2], paths[-1]])
        self.assertCountEqual(ordered, paths)
        self.assertEqual(ordered[3:], paths[1:5])
        self.assertEqual(family_round_robin(ordered), ordered)

    def test_bindings_architectures_and_nonmatching_names_stay_distinct(self):
        paths = [
            variant("sm100", 1),
            variant("sm100", 2),
            variant("sm100", 1, "binding"),
            variant("sm103", 1),
            "src/sm100/op_deadbeef_kernel.cu",
            "src/plain.cu",
        ]
        ordered = family_round_robin(paths)
        self.assertEqual(ordered, [paths[0], *paths[2:], paths[1]])

    def test_changed_first_budget_does_not_fill_with_one_family(self):
        paths = [variant("sm100", i) for i in range(5)] + [
            variant("sm103", 6),
            "src/wrapper.py",
            "src/unchanged.py",
        ]
        current = {p: "new" for p in paths}
        old = {p: "old" for p in paths}
        old[paths[-1]] = "new"
        ordered, changed = changed_first_paths(paths, current, old, limit=3)
        self.assertEqual(changed, [paths[0], paths[-3], paths[-2]])
        self.assertEqual(ordered[:3], changed)
        self.assertCountEqual(ordered, paths)
        self.assertEqual(ordered[-1], paths[-1])

    def test_empty_and_ordinary_paths_keep_original_order(self):
        self.assertEqual(family_round_robin([]), [])
        paths = ["src/alpha.py", "src/zeta.py", "src/normal.cu"]
        self.assertEqual(family_round_robin(paths), paths)

    def test_legacy_cursor_rewinds_only_when_path_order_changes(self):
        paths = [variant("sm100", i) for i in range(3)] + ["src/wrapper.py"]
        self.assertTrue(reset_legacy_cursor(paths, 2, {}))
        self.assertFalse(reset_legacy_cursor(paths, 0, {}))
        self.assertFalse(reset_legacy_cursor(["a.py", "b.py"], 1, {}))
        self.assertFalse(reset_legacy_cursor(paths, 2, {"policy": "old"}))


if __name__ == "__main__":
    unittest.main()
