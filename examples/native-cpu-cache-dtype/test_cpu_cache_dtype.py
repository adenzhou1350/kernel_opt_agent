"""Require a quantized middle layer rather than an all-boundary tiny-model pass."""
import hashlib
import json
import os
from pathlib import Path


def test_real_engine_middle_layer_rejection_and_auto_control():
    import torch
    import vllm
    from vllm import LLM, SamplingParams
    from vllm.platforms import cpu, current_platform
    from vllm.v1.attention.backends import cpu_attn

    root = Path(os.environ['EXPECTED_PACKAGE_ROOT'])
    assert Path(vllm.__file__).resolve().parent == root
    expected = json.loads(os.environ['EXPECTED_MODULES'])
    for module in (cpu, cpu_attn):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(root)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected[str(path.relative_to(root))]
    assert current_platform.is_cpu() and not torch.cuda.is_initialized()
    assert json.loads((Path(os.environ['PRIVATE_MODEL']) / 'config.json').read_text())['num_hidden_layers'] == 3
    common = dict(model=os.environ['PRIVATE_MODEL'], dtype='float32',
                  skip_tokenizer_init=True, max_model_len=128, max_num_seqs=1,
                  enforce_eager=True, enable_prefix_caching=False,
                  enable_chunked_prefill=False, max_num_batched_tokens=128)
    observed = {}
    for dtype in ('turboquant_k8v4', 'auto'):
        llm = None
        try:
            llm = LLM(**common, kv_cache_dtype=dtype)
            observed[dtype] = dict(constructed=True)
            if dtype == 'auto':
                out = llm.generate([{'prompt_token_ids': [3, 4, 5]}],
                                   SamplingParams(temperature=0, max_tokens=2, ignore_eos=True),
                                   use_tqdm=False)
                observed[dtype]['tokens'] = list(out[0].outputs[0].token_ids)
        except Exception as error:
            observed[dtype] = dict(error=type(error).__name__, message=str(error))
        finally:
            if llm is not None:
                llm.llm_engine.engine_core.shutdown(timeout=5)
            Path(os.environ['ROUTE_RESULT']).write_text(json.dumps(observed))
    # Spawned engine errors may be wrapped; the controller also checks the
    # captured child traceback identifies the exact dtype/selector ValueError.
    assert observed['turboquant_k8v4'].get('error') in ('ValueError', 'RuntimeError'), observed
    assert observed['auto'].get('constructed') and len(observed['auto']['tokens']) == 2, observed
