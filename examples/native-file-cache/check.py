"""Check real fsspec buffered reads against BytesIO, without network or mocks."""

import argparse
import hashlib
import inspect
import io
import json
from pathlib import Path
import random
import sys
import unittest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--source",
    required=True,
    type=Path,
    help="Reviewed fsspec repository or exported package root",
)
parser.add_argument(
    "--suite",
    choices=("block", "simple", "adaptive", "all"),
    default="block",
    help="Select block/simple/adaptive checks; all retains the block+simple cohort",
)
options = parser.parse_args()
source_root = options.source.resolve()
sys.path.insert(0, str(source_root))

import fsspec.caching as caching  # noqa: E402
from fsspec.implementations.memory import MemoryFileSystem  # noqa: E402
from fsspec.spec import AbstractBufferedFile  # noqa: E402

for owner in (caching, MemoryFileSystem, AbstractBufferedFile):
    assert Path(inspect.getfile(owner)).resolve().is_relative_to(source_root)

counters = dict(cases=0, read_checks=0, position_checks=0, backend_requests=0)


class ObservedMemoryFileSystem(MemoryFileSystem):
    """Count real backend calls without imposing a new range restriction."""

    def cat_file(self, path, start=None, end=None, **kwargs):
        counters["backend_requests"] += 1
        self.observed_ranges.append((start, end))
        return super().cat_file(path, start=start, end=end, **kwargs)


class StrictMemoryFileSystem(ObservedMemoryFileSystem):
    """Use real memory storage; assert the byte-range contract at its boundary."""

    def cat_file(self, path, start=None, end=None, **kwargs):
        assert type(start) is int and type(end) is int
        assert 0 <= start < end <= self.payload_size, (start, end, self.payload_size)
        return super().cat_file(path, start=start, end=end, **kwargs)


class CachePublicReadTests(unittest.TestCase):
    def check_cache(self, cache_type, *, trim=True, adaptive_options=None):
        blocked = cache_type in ("blockcache", "background")
        for size in (0, 1, 3, 4, 5, 7, 8, 9, 31, 32, 33, 97):
            for block in (1, 4, 8, 16):
                for maxblocks in (0, 1, 3) if blocked else (0,):
                    cache_options = (
                        {"maxblocks": maxblocks}
                        if blocked
                        else {"trim": trim}
                        if cache_type == "bytes"
                        else adaptive_options or {}
                    )
                    with self.subTest(
                        cache=cache_type, size=size, block=block, options=cache_options
                    ):
                        data = bytes((i * 31 + 17) % 256 for i in range(size))
                        fs_type = (
                            StrictMemoryFileSystem
                            if blocked
                            else ObservedMemoryFileSystem
                        )
                        fs = fs_type(skip_instance_cache=True)
                        fs.payload_size = size
                        fs.observed_ranges = []
                        path = f"/cache-probe/{cache_type}-{size}-{block}-{maxblocks}"
                        fs.pipe_file(path, data)
                        ref = io.BytesIO(data)
                        rng = random.Random(size * 103546 + block * 251 + maxblocks)
                        with AbstractBufferedFile(
                            fs,
                            path,
                            mode="rb",
                            size=size,
                            block_size=block,
                            cache_type=cache_type,
                            cache_options=cache_options,
                        ) as actual:
                            expected_type = caching.caches[cache_type]
                            self.assertIsInstance(actual.cache, expected_type)
                            owned_cache = actual.cache
                            if cache_type == "adaptive":
                                self.assertIsNotNone(owned_cache._prefetcher)
                                # A leading read-all can keep this small file in
                                # one buffer, masking seek/restart mistakes.
                                for offset in (0, block, 2 * block, 0, size // 2):
                                    self.assertEqual(
                                        actual.seek(offset), ref.seek(offset)
                                    )
                                    self.assertEqual(
                                        actual.read(block), ref.read(block)
                                    )
                                    self.assertEqual(actual.tell(), ref.tell())
                                    counters["read_checks"] += 1
                                    counters["position_checks"] += 1
                                if size > block:
                                    self.assertTrue(
                                        any(
                                            0 < end - start < size
                                            for start, end in fs.observed_ranges
                                        )
                                    )
                            for offset, whence in (
                                (0, 0),
                                (size + 3, 0),
                                (0, 2),
                                (0, 0),
                            ):
                                self.assertEqual(
                                    actual.seek(offset, whence),
                                    ref.seek(offset, whence),
                                )
                                self.assertEqual(actual.read(), ref.read())
                                counters["read_checks"] += 1
                            for _ in range(64):
                                whence = rng.choice((0, 1, 2))
                                if whence == 0:
                                    offset = rng.randrange(size + 8)
                                elif whence == 1:
                                    offset = rng.randrange(-ref.tell(), size + 8)
                                else:
                                    offset = rng.randrange(-size, 8)
                                self.assertEqual(
                                    actual.seek(offset, whence),
                                    ref.seek(offset, whence),
                                )
                                length = rng.choice(
                                    (None, -1, 0, 1, 3, block, block + 1, size + 7)
                                )
                                if (
                                    rng.randrange(3) == 0
                                    and length is not None
                                    and length >= 0
                                ):
                                    expected_buffer = bytearray([165]) * length
                                    actual_buffer = bytearray(expected_buffer)
                                    self.assertEqual(
                                        actual.readinto(actual_buffer),
                                        ref.readinto(expected_buffer),
                                    )
                                    self.assertEqual(actual_buffer, expected_buffer)
                                else:
                                    self.assertEqual(
                                        actual.read(length), ref.read(length)
                                    )
                                counters["read_checks"] += 1
                                self.assertEqual(actual.tell(), ref.tell())
                                counters["position_checks"] += 1
                        self.assertTrue(actual.closed)
                        self.assertIsNone(actual.cache)
                        if cache_type == "background":
                            self.assertTrue(owned_cache._closed)
                        if cache_type == "adaptive":
                            self.assertIsNone(owned_cache._prefetcher)
                        if cache_type == "mmap" and size:
                            self.assertTrue(owned_cache.cache.closed)
                        fs.rm(path)
                        counters["cases"] += 1

    def test_block_cache_public_read_traces(self):
        self.check_cache("blockcache")

    def test_background_cache_public_read_traces(self):
        self.check_cache("background")

    def test_no_cache_public_read_traces(self):
        self.check_cache("none")

    def test_bytes_trim_public_read_traces(self):
        self.check_cache("bytes")

    def test_bytes_untrimmed_public_read_traces(self):
        self.check_cache("bytes", trim=False)

    def test_readahead_public_read_traces(self):
        self.check_cache("readahead")

    def test_first_chunk_public_read_traces(self):
        self.check_cache("first")

    def test_all_bytes_public_read_traces(self):
        self.check_cache("all")

    def test_mmap_public_read_traces(self):
        self.check_cache("mmap")

    def test_adaptive_cache_public_read_traces(self):
        for concurrency in (1, 4):
            for limit in (1, 16, None):
                with self.subTest(concurrency=concurrency, max_prefetch_size=limit):
                    self.check_cache(
                        "adaptive",
                        adaptive_options={
                            "concurrency": concurrency,
                            "max_prefetch_size": limit,
                        },
                    )


if __name__ == "__main__":
    block_methods = [
        "test_block_cache_public_read_traces",
        "test_background_cache_public_read_traces",
    ]
    simple_methods = [
        "test_no_cache_public_read_traces",
        "test_bytes_trim_public_read_traces",
        "test_bytes_untrimmed_public_read_traces",
        "test_readahead_public_read_traces",
        "test_first_chunk_public_read_traces",
        "test_all_bytes_public_read_traces",
        "test_mmap_public_read_traces",
    ]
    methods = {
        "block": block_methods,
        "simple": simple_methods,
        "adaptive": ["test_adaptive_cache_public_read_traces"],
        "all": block_methods + simple_methods,
    }[options.suite]
    result = unittest.TextTestRunner().run(
        unittest.TestSuite(CachePublicReadTests(name) for name in methods)
    )
    print(
        json.dumps(
            dict(
                counters=counters,
                suite=options.suite,
                python=sys.version.split()[0],
                module=str(caching.__file__),
                module_sha256=hashlib.sha256(
                    Path(caching.__file__).read_bytes()
                ).hexdigest(),
                scope="Bounded serial real buffered-file/memory-backend traces, not network, arbitrary concurrency, performance or full upstream qualification.",
            )
        )
    )
    raise SystemExit(not result.wasSuccessful())
