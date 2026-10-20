"""Check actual fsspec prefetch cancellation/retry with an event-gated byte source."""

import argparse
import asyncio
import hashlib
import inspect
import json
from pathlib import Path
import sys
import unittest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", required=True, type=Path)
source_root = parser.parse_args().source.resolve()
sys.path.insert(0, str(source_root))

from fsspec.prefetcher import BackgroundPrefetcher  # noqa: E402

module_path = Path(inspect.getfile(BackgroundPrefetcher)).resolve()
assert module_path.is_relative_to(source_root)
data = bytes(
    range(256)
)  # Different byte at every offset; repeated bytes hide mis-seeks.
observations = []


class GatedSource:
    def __init__(self, gate_offset):
        self.gate_offset = gate_offset
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []
        self.cancelled = []

    async def __call__(self, start, size, split_factor=1):
        self.calls.append((start, size))
        if start >= self.gate_offset and not self.release.is_set():
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.append(start)
                raise
        return data[start : start + size]


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owned = []
        self.tasks = []

    def make(self, gate_offset):
        source = GatedSource(gate_offset)
        prefetcher = BackgroundPrefetcher(
            source, size=len(data), concurrency=2, max_prefetch_size=64
        )
        self.owned.append((prefetcher, source))
        return prefetcher, source

    def start(self, prefetcher, start, end):
        task = asyncio.create_task(prefetcher.afetch(start, end))
        self.tasks.append(task)
        return task

    async def read(self, prefetcher, start, end):
        actual = await asyncio.wait_for(prefetcher.afetch(start, end), 2)
        self.assertEqual(actual, data[start:end])

    async def cancel(self, task):
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def asyncTearDown(self):
        for _, source in self.owned:
            source.release.set()
        if self.tasks:
            await asyncio.wait_for(
                asyncio.gather(*self.tasks, return_exceptions=True), 2
            )
        for prefetcher, source in self.owned:
            await asyncio.wait_for(prefetcher.aclose(), 2)
            self.assertFalse(prefetcher.producer._active_tasks)
            self.assertTrue(prefetcher.queue.empty())
            self.assertTrue(prefetcher.producer._producer_task.done())
            observations.append(
                dict(
                    case=self._testMethodName,
                    calls=source.calls,
                    cancelled_offsets=source.cancelled,
                    clean=True,
                )
            )

    async def test_cancel_inflight_read_then_retry_same_range(self):
        prefetcher, source = self.make(0)
        task = self.start(prefetcher, 0, 32)
        await asyncio.wait_for(source.entered.wait(), 2)
        await self.cancel(task)
        source.release.set()
        await self.read(prefetcher, 0, 32)
        await self.read(prefetcher, 32, 64)

    async def test_cancel_lock_waiter_does_not_cancel_active_read(self):
        prefetcher, source = self.make(0)
        first = self.start(prefetcher, 0, 64)
        await asyncio.wait_for(source.entered.wait(), 2)
        waiter = self.start(prefetcher, 128, 160)
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        await self.cancel(waiter)
        self.assertFalse(first.done())
        self.assertFalse(source.cancelled)
        source.release.set()
        self.assertEqual(await asyncio.wait_for(first, 2), data[:64])
        await self.read(prefetcher, 64, 96)

    async def test_cancel_read_after_partial_assembly_then_retry(self):
        prefetcher, source = self.make(32)
        for start in (0, 8, 16):
            await self.read(prefetcher, start, start + 8)
        task = self.start(prefetcher, 24, 48)
        await asyncio.wait_for(source.entered.wait(), 2)
        self.assertEqual(prefetcher.consumer.offset, 32)
        self.assertFalse(task.done())
        await self.cancel(task)
        source.release.set()
        await self.read(prefetcher, 24, 48)
        await self.read(prefetcher, 0, 16)

    async def test_cancel_soft_seek_after_partial_skip_then_retry(self):
        prefetcher, source = self.make(48)
        for start in (0, 8, 16, 24, 32):
            await self.read(prefetcher, start, start + 8)
        await asyncio.wait_for(source.entered.wait(), 2)
        self.assertGreaterEqual(prefetcher.producer.current_offset, 64)
        task = self.start(prefetcher, 56, 64)
        for _ in range(20):
            if prefetcher.consumer.offset == 48:
                break
            await asyncio.sleep(0)
        self.assertEqual(prefetcher.consumer.offset, 48)
        self.assertFalse(task.done())
        await self.cancel(task)
        source.release.set()
        await self.read(prefetcher, 56, 64)
        await self.read(prefetcher, 64, 72)


if __name__ == "__main__":
    result = unittest.TextTestRunner().run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CancellationTests)
    )
    print(
        json.dumps(
            dict(
                observations=observations,
                python=sys.version.split()[0],
                source=str(module_path),
                sha256=hashlib.sha256(module_path.read_bytes()).hexdigest(),
                scope="Event-gated async source, real prefetcher; not physical network/MRD, performance or arbitrary interleavings.",
            )
        )
    )
    raise SystemExit(not result.wasSuccessful())
