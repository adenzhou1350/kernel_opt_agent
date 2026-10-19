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
source_root = parser.parse_args().source.resolve()
sys.path.insert(0, str(source_root))

import fsspec.caching as caching  # noqa: E402
from fsspec.implementations.memory import MemoryFileSystem  # noqa: E402
from fsspec.spec import AbstractBufferedFile  # noqa: E402

for owner in (caching, MemoryFileSystem, AbstractBufferedFile):
    assert Path(inspect.getfile(owner)).resolve().is_relative_to(source_root)

counters = dict(cases=0, read_checks=0, position_checks=0, backend_requests=0)


class StrictMemoryFileSystem(MemoryFileSystem):
    """Use real memory storage; assert the byte-range contract at its boundary."""

    def cat_file(self, path, start=None, end=None, **kwargs):
        assert type(start) is int and type(end) is int
        assert 0 <= start < end <= self.payload_size, (start, end, self.payload_size)
        counters["backend_requests"] += 1
        return super().cat_file(path, start=start, end=end, **kwargs)


class CachePublicReadTests(unittest.TestCase):
    def check_cache(self, cache_type):
        for size in (0, 1, 3, 4, 5, 7, 8, 9, 31, 32, 33, 97):
            for block in (1, 4, 8, 16):
                for maxblocks in (0, 1, 3):
                    with self.subTest(
                        cache=cache_type, size=size, block=block, maxblocks=maxblocks
                    ):
                        data = bytes((i * 31 + 17) % 256 for i in range(size))
                        fs = StrictMemoryFileSystem(skip_instance_cache=True)
                        fs.payload_size = size
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
                            cache_options={"maxblocks": maxblocks},
                        ) as actual:
                            expected_type = (
                                caching.BlockCache
                                if cache_type == "blockcache"
                                else caching.BackgroundBlockCache
                            )
                            self.assertIsInstance(actual.cache, expected_type)
                            owned_cache = actual.cache
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
                        counters["cases"] += 1

    def test_block_cache_public_read_traces(self):
        self.check_cache("blockcache")

    def test_background_cache_public_read_traces(self):
        self.check_cache("background")


if __name__ == "__main__":
    result = unittest.TextTestRunner().run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CachePublicReadTests)
    )
    print(
        json.dumps(
            dict(
                counters=counters,
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
