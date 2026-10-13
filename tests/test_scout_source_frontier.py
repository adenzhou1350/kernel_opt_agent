import unittest
from scripts.scout_source_frontier import tail_window_starts


class TailFrontierTests(unittest.TestCase):
    def test_short_files_and_boundary(self):
        self.assertEqual(tail_window_starts(720, 720), [])
        self.assertEqual(tail_window_starts(721, 720), [721])
        self.assertEqual(tail_window_starts(1000, 720), [721, 841, 961])

    def test_large_file_keeps_tail_and_cap(self):
        starts = tail_window_starts(3000, 720)
        self.assertEqual(starts, [721, 1801, 2881])
        self.assertEqual(len(set(starts)), 3)
        self.assertTrue(all(s > 720 and s <= 3000 for s in starts))
        self.assertEqual(tail_window_starts(3000, 720, max_windows=1), [721])

    def test_invalid_budgets(self):
        for args, kwargs in [((True, 720), {}), ((100, -1), {}),
                             ((100, 0), {'max_windows': 9}), ((100, 0), {'width': 161})]:
            with self.assertRaises(ValueError):
                tail_window_starts(*args, **kwargs)


if __name__ == '__main__':
    unittest.main()
