"""Native CPU routing checks; not a model-generation or throughput qualification."""

import asyncio
import os
from pathlib import Path
import queue
import sys
import threading
from unittest.mock import patch

import pytest


configured_root = os.environ.get("TRANSFORMERS_ROUTER_SOURCE_ROOT")
if not configured_root:
    pytest.skip(
        "Set TRANSFORMERS_ROUTER_SOURCE_ROOT to a reviewed checkout",
        allow_module_level=True,
    )
SOURCE_ROOT = Path(configured_root).resolve()
sys.path.insert(0, str(SOURCE_ROOT / "src"))

import transformers  # noqa: E402
from transformers import ContinuousBatchingConfig, LlamaConfig, LlamaForCausalLM  # noqa: E402
from transformers.generation.continuous_batching.requests import (  # noqa: E402
    GenerationOutput,
    RequestStatus,
)

assert Path(transformers.__file__).resolve().is_relative_to(SOURCE_ROOT)


@pytest.fixture
def manager():
    model = LlamaForCausalLM(
        LlamaConfig(
            vocab_size=32,
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=4,
        )
    )
    result = model.init_continuous_batching(
        continuous_batching_config=ContinuousBatchingConfig(auto_switch_to_flash=False)
    )
    assert str(model.device) == "cpu"
    assert result._generation_thread is None
    return result


class LoopThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.loop.set_debug(True)
        self.started = threading.Event()
        self.thread = threading.Thread(target=self._run)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.started.set()
        self.loop.run_forever()

    def __enter__(self):
        self.thread.start()
        assert self.started.wait(3)
        return self

    def __exit__(self, *args):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)
        assert not self.thread.is_alive()
        self.loop.close()

    def flush(self):
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self.loop).result(3)

    def register(self, manager, request_id, observations, expected_callbacks=1):
        delivered = threading.Event()

        async def register_on_owner():
            future = self.loop.create_future()
            # Debug mode checks Future callback scheduling from the correct thread.
            future.add_done_callback(lambda _: None)
            received = 0

            def callback(output):
                nonlocal received
                errors = []
                if output.is_finished():
                    try:
                        future.set_result(output)
                    except RuntimeError as error:
                        errors.append(str(error))
                observations.put(
                    (
                        request_id,
                        asyncio.get_running_loop() is self.loop,
                        threading.get_ident() == self.thread.ident,
                        output.generated_tokens,
                        errors,
                    )
                )
                received += 1
                if received == expected_callbacks:
                    delivered.set()

            manager.register_result_handler(request_id, callback)

        asyncio.run_coroutine_threadsafe(register_on_owner(), self.loop).result(3)
        return delivered


@pytest.mark.parametrize("method", ["deliver", "deliver_batch"])
@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_callbacks_keep_registered_loop_and_thread(manager, method, order):
    observations = queue.Queue()
    with LoopThread() as first, LoopThread() as second:
        events = {
            "a": first.register(manager, "a", observations),
            "b": second.register(manager, "b", observations),
        }
        outputs = [
            GenerationOutput(request_id=name, status=RequestStatus.FINISHED)
            for name in order
        ]
        if method == "deliver":
            for output in outputs:
                manager.output_router.deliver(output)
        else:
            manager.output_router.deliver_batch(outputs)
        assert all(event.wait(3) for event in events.values())
        first.flush()
        second.flush()
        actual = [observations.get_nowait() for _ in order]
        assert all(item[1] and item[2] for item in actual), actual
        assert all(not item[4] for item in actual), actual
        assert manager.output_router.result_handlers == {}
        assert manager.output_router.output_queue.empty()


def test_one_loop_streaming_queue_fallback_and_batching(manager):
    observations = queue.Queue()
    with LoopThread() as owner:
        delivered = owner.register(manager, "a", observations, expected_callbacks=2)
        outputs = [
            GenerationOutput(
                request_id="a", generated_tokens=[1], status=RequestStatus.DECODING
            ),
            GenerationOutput(request_id="queue"),
            GenerationOutput(
                request_id="a", generated_tokens=[1, 2], status=RequestStatus.FINISHED
            ),
        ]
        with patch.object(
            owner.loop, "call_soon_threadsafe", wraps=owner.loop.call_soon_threadsafe
        ) as scheduled:
            manager.output_router.deliver_batch(outputs)
            assert delivered.wait(3)
            assert scheduled.call_count == 1
        owner.flush()
        actual = [observations.get_nowait() for _ in range(2)]
        assert [item[3] for item in actual] == [[1], [1, 2]]
        assert all(item[1] and item[2] and not item[4] for item in actual)
        assert manager.output_router.result_handlers == {}
        assert manager.output_router.output_queue.get_nowait() is outputs[1]
        assert manager.output_router.output_queue.empty()


def test_interleaved_loops_preserve_each_stream_and_batch_once(manager):
    observations = queue.Queue()
    with LoopThread() as first, LoopThread() as second:
        events = [
            first.register(manager, "a", observations, expected_callbacks=2),
            second.register(manager, "b", observations, expected_callbacks=2),
        ]
        outputs = [
            GenerationOutput(
                request_id="a", generated_tokens=[1], status=RequestStatus.DECODING
            ),
            GenerationOutput(
                request_id="b", generated_tokens=[2], status=RequestStatus.DECODING
            ),
            GenerationOutput(request_id="queue"),
            GenerationOutput(
                request_id="a", generated_tokens=[1, 3], status=RequestStatus.FINISHED
            ),
            GenerationOutput(
                request_id="b", generated_tokens=[2, 4], status=RequestStatus.FINISHED
            ),
        ]
        with (
            patch.object(
                first.loop,
                "call_soon_threadsafe",
                wraps=first.loop.call_soon_threadsafe,
            ) as schedule_a,
            patch.object(
                second.loop,
                "call_soon_threadsafe",
                wraps=second.loop.call_soon_threadsafe,
            ) as schedule_b,
        ):
            manager.output_router.deliver_batch(outputs)
            assert all(event.wait(3) for event in events)
            assert schedule_a.call_count == schedule_b.call_count == 1
        first.flush()
        second.flush()
        actual = [observations.get_nowait() for _ in range(4)]
        assert all(item[1] and item[2] and not item[4] for item in actual), actual
        assert [item[3] for item in actual if item[0] == "a"] == [[1], [1, 3]]
        assert [item[3] for item in actual if item[0] == "b"] == [[2], [2, 4]]
        assert manager.output_router.result_handlers == {}
        assert manager.output_router.output_queue.get_nowait() is outputs[2]
        assert manager.output_router.output_queue.empty()


def test_empty_and_unregistered_batch(manager):
    manager.output_router.deliver_batch([])
    assert manager.output_router.output_queue.empty()
    outputs = [GenerationOutput(request_id=str(index)) for index in range(3)]
    manager.output_router.deliver_batch(outputs)
    assert [manager.output_router.output_queue.get_nowait() for _ in outputs] == outputs
    assert manager.output_router.output_queue.empty()
