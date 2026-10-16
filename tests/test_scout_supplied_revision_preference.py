"""Existing old/new windows of one path must not hide the supplied current pin."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_import_context import import_requests
from scout_symbol_references import reference_requests

REPO, OLD, CURRENT, PATH = "public/project", "a" * 40, "b" * 40, "pkg/model.py"


class SuppliedRevisionTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(url=f"https://raw.githubusercontent.com/{REPO}/{OLD}/{PATH}",
                        start_line=1, end_line=1, text="1: old excerpt")
        self.current = dict(url=f"https://raw.githubusercontent.com/{REPO}/{CURRENT}/{PATH}",
                            start_line=1, end_line=1, text="1: new excerpt")
        self.snapshot = dict(commit=CURRENT, files=[PATH, "pkg/gate.py"])

    def run_route(self, route, sources):
        packet = dict(repo=REPO, sources=sources)
        before = deepcopy(packet)
        raw = "from .gate import target\n" + "\n" * 100 + "def use():\n    return target()\n"
        cache = Mock(return_value=raw)
        request = "references(target)" if route is reference_requests else "definition(target)"
        result = route(packet, self.snapshot, dict(next_check=request + " in " + PATH), cache)
        self.assertEqual(packet, before)
        return result, cache

    def test_old_first_current_second_uses_only_current_cache(self):
        for route in (reference_requests, import_requests):
            with self.subTest(route=route.__name__):
                result, cache = self.run_route(route, [self.old, self.current])
                self.assertTrue(result)
                self.assertLessEqual(len(result), 2)
                cache.assert_called_once_with(REPO, CURRENT, PATH)
                self.assertEqual(result[0]["path"], PATH if route is reference_requests else "pkg/gate.py")

    def test_order_of_different_revisions_does_not_change_request(self):
        for route in (reference_requests, import_requests):
            left, _ = self.run_route(route, [self.old, self.current])
            right, _ = self.run_route(route, [self.current, self.old])
            self.assertEqual(left, right)

    def test_old_window_ranges_do_not_count_as_current_evidence(self):
        self.old.update(end_line=1000)
        result, cache = self.run_route(reference_requests, [self.old, self.current])
        self.assertTrue(result)
        cache.assert_called_once_with(REPO, CURRENT, PATH)

    def test_already_shown_current_ranges_still_abstain(self):
        self.current.update(end_line=1000)
        result, cache = self.run_route(reference_requests, [self.old, self.current])
        self.assertEqual(result, [])
        cache.assert_called_once_with(REPO, CURRENT, PATH)

    def test_no_same_path_current_pin_still_abstains_without_cache_read(self):
        malformed = (
            {**self.current, "url": self.current["url"] + "?secret=ignored"},
            {**self.current, "url": self.current["url"].replace("raw.githubusercontent.com", "foreign.invalid")},
            {**self.current, "url": self.current["url"].replace("/pkg/model.py", "/other/model.py")},
        )
        for route in (reference_requests, import_requests):
            for sources in ([self.old], [self.old] * 8 + [self.current],
                            *([self.old, extra] for extra in malformed)):
                with self.subTest(route=route.__name__, sources=sources):
                    result, cache = self.run_route(route, sources)
                    self.assertEqual(result, [])
                    cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
