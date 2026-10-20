"""Explicit isolated canary checks, intentionally outside test discovery."""

import unittest

from fixture_subject import slice_exclusive


class RangeContract(unittest.TestCase):
    def test_ordinary_control(self):
        self.assertEqual(slice_exclusive(b"abcd", 0, 99), b"abcd")

    def test_exclusive_end_witness(self):
        self.assertEqual(slice_exclusive(b"abcd", 1, 3), b"bc")
