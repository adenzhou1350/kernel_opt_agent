#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cuda_arch="${CUDA_ARCH:-sm_120a}"
output_dir="${BUILD_DIR:-${script_dir}/build}"
nvcc_bin="${NVCC:-}"

if [[ -z "${nvcc_bin}" ]] && command -v nvcc >/dev/null 2>&1; then
  nvcc_bin="$(command -v nvcc)"
fi
if [[ -z "${nvcc_bin}" ]] && [[ -x "${CUDA_HOME:-/usr/local/cuda}/bin/nvcc" ]]; then
  nvcc_bin="${CUDA_HOME:-/usr/local/cuda}/bin/nvcc"
fi
if [[ -z "${nvcc_bin}" ]]; then
  for candidate in /usr/local/cuda-*/bin/nvcc; do
    if [[ -x "${candidate}" ]]; then
      nvcc_bin="${candidate}"
    fi
  done
fi
if [[ -z "${nvcc_bin}" ]]; then
  echo "nvcc not found; set NVCC or CUDA_HOME" >&2
  exit 2
fi

mkdir -p "${output_dir}"
"${nvcc_bin}" \
  -O3 \
  -std=c++17 \
  -lineinfo \
  -arch="${cuda_arch}" \
  "${script_dir}/particle_bench.cu" \
  -o "${output_dir}/particle_bench"

sha256sum "${script_dir}/particle_bench.cu" "${output_dir}/particle_bench"
