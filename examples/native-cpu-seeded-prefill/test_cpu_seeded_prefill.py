"""Public LLM generation, real CPU sampler, task-private tiny random weights."""
import gc
import hashlib
import json
import os
from pathlib import Path


def test_seeded_generation_and_followup_request():
    import torch
    import vllm
    from vllm import LLM, SamplingParams
    from vllm.platforms import current_platform
    from vllm.v1.worker import gpu_model_runner
    from vllm.v1.worker.cpu_model_runner import CPUModelRunner

    root = Path(os.environ['EXPECTED_PACKAGE_ROOT'])
    source = root / 'v1/worker/gpu_model_runner.py'
    assert Path(vllm.__file__).resolve().parent == root
    assert Path(gpu_model_runner.__file__).resolve() == source
    assert hashlib.sha256(source.read_bytes()).hexdigest() == os.environ['EXPECTED_RUNNER_SHA256']
    assert CPUModelRunner._bookkeeping_sync is gpu_model_runner.GPUModelRunner._bookkeeping_sync
    assert current_platform.is_cpu() and not torch.cuda.is_initialized()
    budget = int(os.environ['PREFILL_BUDGET'])
    chunked = os.environ['CHUNKED_PREFILL'] == '1'
    # Direct token input isolates sampling from tokenization. Model weights,
    # prompts, seeds and output lengths are identical across the five captures.
    prompts = [{'prompt_token_ids': [3, 4, 5, 6] * 15},
               {'prompt_token_ids': [7, 8, 9, 10] * 10},
               {'prompt_token_ids': [11, 12, 13, 14, 15]}]
    params = [SamplingParams(temperature=0.8, seed=seed, max_tokens=8, ignore_eos=True)
              for seed in (1, 2, 3)]
    llm = None
    try:
        llm = LLM(model=os.environ['PRIVATE_MODEL'], dtype='float32',
                  skip_tokenizer_init=True, max_model_len=128, max_num_seqs=3,
                  enforce_eager=True, enable_prefix_caching=False,
                  enable_chunked_prefill=chunked, max_num_batched_tokens=budget)
        outputs = llm.generate(prompts, params, use_tqdm=False)
        tokens = [list(output.outputs[0].token_ids) for output in outputs]
        assert len(tokens) == 3 and all(len(row) == 8 for row in tokens)
        followup = llm.generate([{'prompt_token_ids': [3, 4, 5]}],
                               SamplingParams(temperature=0, max_tokens=2, ignore_eos=True),
                               use_tqdm=False)
        assert len(followup[0].outputs[0].token_ids) == 2
        assert not torch.cuda.is_initialized()
        Path(os.environ['TOKEN_RESULT']).write_text(json.dumps(dict(
            seeded_tokens=tokens,followup_tokens=list(followup[0].outputs[0].token_ids),
            runner_sha256=os.environ['EXPECTED_RUNNER_SHA256'],
            chunked_prefill=chunked,budget=budget,torch=torch.__version__,vllm=vllm.__version__)))
    finally:
        if llm is not None:
            llm.llm_engine.engine_core.shutdown(timeout=5)
            del llm
            gc.collect()
