#!/usr/bin/env bash
set -euo pipefail

repo=/home/oem/community-agent/vllm-lmhead-pr
experiment=/home/oem/community-agent/vllm-lmhead-sm120-20260908
model=/home/oem/community-agent/models/Qwen3.5-0.8B-W4A16-AutoRound-GPTQ-fbfcca
output_root="$experiment/uniproc-logprob-oracle-v1"
expected_commit=4048b5edbad29bed0d052c6e258fd1c53072218f
expected_uuid=GPU-14f89acf-cf7c-3a09-80d5-e43035823f0d

mkdir -p "$output_root"
cd "$repo"
[[ "$(git rev-parse HEAD)" == "$expected_commit" ]]
[[ -z "$(git status --porcelain)" ]]

run_arm() {
  local arm=$1
  local multiprocessing=$2
  local output_dir="$output_root/$arm"
  local cache_root="$experiment/cache/uniproc-logprob-oracle-v1-$arm"
  [[ ! -e "$output_dir" ]]
  [[ ! -e "$cache_root" ]]
  mkdir -p "$output_dir" "$cache_root"
  local uuid memory util
  read -r uuid memory util <<<"$(
    nvidia-smi --query-gpu=uuid,memory.used,utilization.gpu \
      --format=csv,noheader,nounits | tr -d ','
  )"
  [[ "$uuid" == "$expected_uuid" ]]
  (( memory <= 1024 ))
  (( util <= 10 ))
  if nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits \
      | grep -q '[0-9]'; then
    echo "GPU has a compute process before arm=$arm" >&2
    return 3
  fi
  export PATH="$repo/.venv/bin:/usr/local/cuda/bin:$PATH"
  export CUDA_VISIBLE_DEVICES=0
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
  export VLLM_CACHE_ROOT="$cache_root"
  export VLLM_USE_PRECOMPILED=1
  export VLLM_USE_V2_MODEL_RUNNER=0
  export VLLM_BATCH_INVARIANT=0
  export VLLM_ENABLE_V1_MULTIPROCESSING="$multiprocessing"
  unset DEBUGINFOD_URLS
  timeout --signal=TERM --kill-after=30s 600s \
    .venv/bin/python "$experiment/profile_batch_logprobs.py" \
      --model "$model" \
      --output "$output_dir/result.json" \
      --batch-size 8 \
      --new-tokens 64 \
      >"$output_dir/run.log" 2>&1
}

run_arm control 1
run_arm uniproc 0
echo "logprob_oracle_complete"
