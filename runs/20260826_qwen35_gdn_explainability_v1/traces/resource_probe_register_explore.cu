#include <cuda.h>
#include <cuda_pipeline.h>
#include <cuda_runtime.h>
#include <mma.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

__constant__ float constant_table[4096];

#define CUDA_CHECK(expr) do { \
  cudaError_t status_ = (expr); \
  if (status_ != cudaSuccess) throw std::runtime_error(cudaGetErrorString(status_)); \
} while (0)

__global__ void zero_probe(float* output) {
  if (blockIdx.x == 0 && threadIdx.x == 0) output[0] = 0.0f;
}

__global__ void shared_probe(const float* input, float* output, int stride, int repeats) {
  extern __shared__ volatile float shared_storage[];
  const int tid = threadIdx.x;
  const int lane = tid & 31;
  const int warp = tid >> 5;
  shared_storage[tid] = input[(blockIdx.x * blockDim.x + tid) & 65535];
  __syncthreads();
  float value = shared_storage[tid];
#pragma unroll 1
  for (int i = 0; i < repeats; ++i) {
    const int index = ((warp << 10) + lane * stride + ((i & 7) << 5)) % blockDim.x;
    value = fmaf(shared_storage[index], 1.000000119f, value);
  }
  if (isfinite(value)) output[blockIdx.x * blockDim.x + tid] = value;
}

__global__ void constant_probe(float* output, int divergent, int repeats) {
  const int lane = threadIdx.x & 31;
  float value = 0.25f + lane;
#pragma unroll 1
  for (int i = 0; i < repeats; ++i) {
    const int index = divergent ? ((lane * 17 + i * 32) & 4095) : ((i * 32) & 4095);
    value = fmaf(constant_table[index], 1.000000119f, value);
  }
  if (isfinite(value)) output[blockIdx.x * blockDim.x + threadIdx.x] = value;
}

__global__ void global_request_probe(const float4* input, float4* output, float* sink, size_t count, int write_only, int repeats) {
  size_t index = static_cast<size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  const size_t step = static_cast<size_t>(gridDim.x) * blockDim.x;
  float4 value = make_float4(1.f, 2.f, 3.f, 4.f);
#pragma unroll 1
  for (int r = 0; r < repeats; ++r) {
    for (size_t i = index; i < count; i += step) {
      if (!write_only) value = input[i];
      value.x += 0.000001f * r;
      output[i] = value;
    }
  }
  if (index == 0 && isfinite(value.x + value.y + value.z + value.w))
    atomicAdd(sink, value.x + value.y + value.z + value.w);
}

template <int N>
__global__ void register_probe(const float* input, float* output, int repeats, int use_shuffle) {
  float values[N];
  const int index = blockIdx.x * blockDim.x + threadIdx.x;
#pragma unroll
  for (int i = 0; i < N; ++i) values[i] = input[(index + i * 97) & 65535] + 0.0001f * i;
#pragma unroll 1
  for (int r = 0; r < repeats; ++r) {
#pragma unroll
    for (int i = 0; i < N; ++i) values[i] = fmaf(values[i], 1.000000119f, values[(i + 1) % N]);
    if (use_shuffle) values[0] += __shfl_xor_sync(0xffffffffu, values[0], 1);
  }
  float sum = 0.f;
#pragma unroll
  for (int i = 0; i < N; ++i) sum += values[i];
  if ((threadIdx.x & 31) == 0 && isfinite(sum))
    output[blockIdx.x * ((blockDim.x + 31) / 32) + (threadIdx.x >> 5)] = sum;
}

template <int PADDING>
__global__ void register_allocation_probe(const float* input, float* output, int repeats) {
  const int index = blockIdx.x * blockDim.x + threadIdx.x;
  float payload[8];
#pragma unroll
  for (int i = 0; i < 8; ++i) payload[i] = input[(index + i * 97) & 65535] + 0.0001f * i;
  float padding[PADDING > 0 ? PADDING : 1];
#pragma unroll
  for (int i = 0; i < PADDING; ++i) padding[i] = input[(index + i * 193 + 17) & 65535] + 0.00001f * i;
#pragma unroll 1
  for (int r = 0; r < repeats; ++r) {
#pragma unroll
    for (int i = 0; i < 8; ++i) payload[i] = fmaf(payload[i], 1.000000119f, payload[(i + 1) & 7]);
  }
  float sum = 0.f;
#pragma unroll
  for (int i = 0; i < 8; ++i) sum += payload[i];
#pragma unroll
  for (int i = 0; i < PADDING; ++i) sum += padding[i];
  if ((threadIdx.x & 31) == 0 && isfinite(sum))
    output[blockIdx.x * ((blockDim.x + 31) / 32) + (threadIdx.x >> 5)] = sum;
}

__global__ void collective_probe(const float* input, float* output, int repeats, int independent) {
  const int index = blockIdx.x * blockDim.x + threadIdx.x;
  float x0 = input[index & 65535] + 0.125f;
  float x1 = input[(index + 1) & 65535] + 0.25f;
  float x2 = input[(index + 2) & 65535] + 0.5f;
  float x3 = input[(index + 3) & 65535] + 1.0f;
#pragma unroll 1
  for (int r = 0; r < repeats; ++r) {
    x0 = __shfl_xor_sync(0xffffffffu, x0, 1);
    if (independent) {
      x1 = __shfl_xor_sync(0xffffffffu, x1, 2);
      x2 = __shfl_xor_sync(0xffffffffu, x2, 4);
      x3 = __shfl_xor_sync(0xffffffffu, x3, 8);
    }
  }
  float value = x0 + x1 + x2 + x3;
  if ((threadIdx.x & 31) == 0 && isfinite(value))
    output[blockIdx.x * ((blockDim.x + 31) / 32) + (threadIdx.x >> 5)] = value;
}

__global__ void simt_compute_probe(const float* input, float* output, int variant, int repeats) {
  const int index = blockIdx.x * blockDim.x + threadIdx.x;
  float x0 = input[index & 65535] + 0.125f;
  float x1 = input[(index + 1) & 65535] + 0.25f;
  float x2 = input[(index + 2) & 65535] + 0.5f;
  float x3 = input[(index + 3) & 65535] + 1.f;
  unsigned iv = static_cast<unsigned>(index + 1);
#pragma unroll 1
  for (int i = 0; i < repeats; ++i) {
    if (variant == 0) {
      x0 = fmaf(x0, 1.000000119f, 0.000001f);
    } else if (variant == 1) {
      x0 = fmaf(x0, 1.000000119f, 0.000001f);
      x1 = fmaf(x1, 1.000000238f, 0.000002f);
      x2 = fmaf(x2, 1.000000358f, 0.000003f);
      x3 = fmaf(x3, 1.000000477f, 0.000004f);
    } else if (variant == 2) {
      x0 = exp2f(fminf(x0 * 0.001f, 8.f)) * 0.125f;
    } else {
      iv = iv * 1664525u + 1013904223u;
      x0 += static_cast<float>(iv & 255u) * 0.000001f;
    }
  }
  float value = x0 + x1 + x2 + x3 + static_cast<float>(iv & 255u);
  if ((threadIdx.x & 31) == 0 && isfinite(value)) atomicAdd(output, value);
}

__global__ void init_half(half* data, int count) {
  int index = blockIdx.x * blockDim.x + threadIdx.x;
  if (index < count) data[index] = __float2half(0.03125f + 0.00001f * (index & 31));
}

__global__ void tensor_probe(const half* a, const half* b, float* output, int repeats) {
  using namespace nvcuda;
  wmma::fragment<wmma::matrix_a, 16, 16, 16, half, wmma::row_major> af;
  wmma::fragment<wmma::matrix_b, 16, 16, 16, half, wmma::col_major> bf;
  wmma::fragment<wmma::accumulator, 16, 16, 16, float> cf;
  wmma::fill_fragment(cf, 0.0f);
  const int warp = (blockIdx.x * blockDim.x + threadIdx.x) >> 5;
  const int offset = (warp & 15) * 256;
  wmma::load_matrix_sync(af, a + offset, 16);
  wmma::load_matrix_sync(bf, b + offset, 16);
#pragma unroll 1
  for (int i = 0; i < repeats; ++i) wmma::mma_sync(cf, af, bf, cf);
  if ((threadIdx.x & 31) == 0) atomicAdd(output, cf.x[0]);
}

__global__ void sync_copy_probe(const float* input, float* output, int repeats, int async_mode) {
  extern __shared__ float sync_storage[];
  const int tid = threadIdx.x;
  float value = 0.f;
#pragma unroll 1
  for (int i = 0; i < repeats; ++i) {
    int index = (blockIdx.x * blockDim.x + tid + i * blockDim.x) & 65535;
    if (async_mode) {
      __pipeline_memcpy_async(&sync_storage[tid], &input[index], sizeof(float));
      __pipeline_commit();
      __pipeline_wait_prior(0);
    } else {
      sync_storage[tid] = input[index];
    }
    __syncthreads();
    value = fmaf(sync_storage[(tid + i) % blockDim.x], 1.000000119f, value);
    __syncthreads();
  }
  if ((tid & 31) == 0 && isfinite(value)) atomicAdd(output, value);
}

struct Options {
  std::string mode = "shared";
  std::string variant = "positive";
  std::string action = "measure";
  int device = 6;
  int grid = 112;
  int block = 384;
  int repeats = 64;
  int batches = 32;
  int samples = 31;
  int stride = 1;
  int preheat_ms = 500;
  size_t bytes = 16 * 1024 * 1024;
};

Options parse(int argc, char** argv) {
  Options options;
  std::map<std::string, std::string*> strings{{"mode", &options.mode}, {"variant", &options.variant}, {"action", &options.action}};
  std::map<std::string, int*> integers{{"device", &options.device}, {"grid", &options.grid}, {"block", &options.block}, {"repeats", &options.repeats}, {"batches", &options.batches}, {"samples", &options.samples}, {"stride", &options.stride}, {"preheat-ms", &options.preheat_ms}};
  for (int i = 1; i < argc; ++i) {
    std::string argument(argv[i]);
    auto position = argument.find('=');
    if (position == std::string::npos) continue;
    std::string key = argument.substr(2, position - 2), value = argument.substr(position + 1);
    if (strings.count(key)) *strings[key] = value;
    else if (integers.count(key)) *integers[key] = std::stoi(value);
    else if (key == "bytes") options.bytes = static_cast<size_t>(std::stoull(value));
  }
  return options;
}

void launch(const Options& o, float* input, float* output, half* ha, half* hb) {
  if (o.variant == "zero") {
    zero_probe<<<o.grid, o.block>>>(output);
  } else if (o.mode == "shared") {
    if (o.variant == "constant_broadcast") constant_probe<<<o.grid, o.block>>>(output, 0, o.repeats);
    else if (o.variant == "constant_divergent") constant_probe<<<o.grid, o.block>>>(output, 1, o.repeats);
    else if (o.variant == "global_request") global_request_probe<<<o.grid, o.block>>>(reinterpret_cast<float4*>(input), reinterpret_cast<float4*>(input + 65536), output, 65536 / 4, 0, std::max(1, o.repeats / 8));
    else shared_probe<<<o.grid, o.block, o.block * sizeof(float)>>>(input, output, o.stride, o.repeats);
  } else if (o.mode == "register") {
    if (o.variant == "alloc0") register_allocation_probe<0><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc32") register_allocation_probe<32><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc64") register_allocation_probe<64><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc96") register_allocation_probe<96><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc112") register_allocation_probe<112><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc116") register_allocation_probe<116><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc120") register_allocation_probe<120><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc124") register_allocation_probe<124><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "alloc128") register_allocation_probe<128><<<o.grid, o.block>>>(input, output, o.repeats);
    else if (o.variant == "shfl_dep") collective_probe<<<o.grid, o.block>>>(input, output, o.repeats, 0);
    else if (o.variant == "shfl_ilp4") collective_probe<<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "r32") register_probe<8><<<o.grid, o.block>>>(input, output, o.repeats, 0);
    else if (o.variant == "r64") register_probe<16><<<o.grid, o.block>>>(input, output, o.repeats, 0);
    else if (o.variant == "r96") register_probe<24><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "r128") register_probe<32><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "n48") register_probe<48><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "n64") register_probe<64><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "n96") register_probe<96><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "n112") register_probe<112><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "n128") register_probe<128><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else if (o.variant == "n144") register_probe<144><<<o.grid, o.block>>>(input, output, o.repeats, 1);
    else throw std::runtime_error("unknown register variant: " + o.variant);
  } else if (o.mode == "compute") {
    if (o.variant == "tensor") tensor_probe<<<o.grid, o.block>>>(ha, hb, output, std::max(1, o.repeats / 8));
    else {
      int variant = o.variant == "fma_dep" ? 0 : o.variant == "fma_ilp4" ? 1 : o.variant == "sfu" ? 2 : 3;
      simt_compute_probe<<<o.grid, o.block>>>(input, output, variant, o.repeats);
    }
  } else if (o.mode == "memory") {
    size_t count = std::max<size_t>(1, o.bytes / sizeof(float4));
    global_request_probe<<<o.grid, o.block>>>(reinterpret_cast<float4*>(input), reinterpret_cast<float4*>(input + o.bytes / sizeof(float)), output, count, o.variant == "write", std::max(1, o.repeats / 16));
  } else if (o.mode == "sync") {
    sync_copy_probe<<<o.grid, o.block, o.block * sizeof(float)>>>(input, output, o.repeats, o.variant == "async");
  } else {
    throw std::runtime_error("unknown mode: " + o.mode);
  }
}

int main(int argc, char** argv) {
  try {
    Options o = parse(argc, argv);
    CUDA_CHECK(cudaSetDevice(o.device));
    size_t allocation_bytes = std::max<size_t>(2 * o.bytes + 4096, 128 * 1024 * 1024);
    float *input = nullptr, *output = nullptr;
    half *ha = nullptr, *hb = nullptr;
    CUDA_CHECK(cudaMalloc(&input, allocation_bytes));
    constexpr size_t output_count = 1u << 20;
    CUDA_CHECK(cudaMalloc(&output, output_count * sizeof(float)));
    CUDA_CHECK(cudaMalloc(&ha, 16 * 4096 * sizeof(half)));
    CUDA_CHECK(cudaMalloc(&hb, 16 * 4096 * sizeof(half)));
    std::vector<float> host_input(allocation_bytes / sizeof(float));
    for (size_t i = 0; i < host_input.size(); ++i)
      host_input[i] = 0.03125f + static_cast<float>(i & 1023) * 0.000001f;
    std::vector<float> constants(4096);
    for (size_t i = 0; i < constants.size(); ++i)
      constants[i] = 0.0625f + static_cast<float>(i) * 0.0000005f;
    CUDA_CHECK(cudaMemcpy(input, host_input.data(), allocation_bytes, cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpyToSymbol(constant_table, constants.data(), constants.size() * sizeof(float)));
    CUDA_CHECK(cudaMemset(output, 0, output_count * sizeof(float)));
    init_half<<<256, 256>>>(ha, 16 * 4096);
    init_half<<<256, 256>>>(hb, 16 * 4096);
    CUDA_CHECK(cudaDeviceSynchronize());
    auto preheat_start = std::chrono::steady_clock::now();
    int preheat_launches = 0;
    do {
      for (int i = 0; i < 32; ++i) launch(o, input, output, ha, hb);
      CUDA_CHECK(cudaDeviceSynchronize());
      preheat_launches += 32;
    } while (std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - preheat_start).count() < o.preheat_ms);

    int samples = o.action == "correctness" ? 3 : (o.action == "warmup" ? 9 : o.samples);
    std::vector<float> gpu_us, host_us;
    cudaEvent_t start, stop;
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));
    for (int sample = 0; sample < samples; ++sample) {
      CUDA_CHECK(cudaEventRecord(start));
      auto host_start = std::chrono::steady_clock::now();
      for (int batch = 0; batch < o.batches; ++batch) launch(o, input, output, ha, hb);
      auto host_stop = std::chrono::steady_clock::now();
      CUDA_CHECK(cudaEventRecord(stop));
      CUDA_CHECK(cudaEventSynchronize(stop));
      float milliseconds = 0.f;
      CUDA_CHECK(cudaEventElapsedTime(&milliseconds, start, stop));
      gpu_us.push_back(milliseconds * 1000.f / o.batches);
      host_us.push_back(std::chrono::duration<double, std::micro>(host_stop - host_start).count() / o.batches);
    }
    std::vector<float> host_output(output_count);
    CUDA_CHECK(cudaMemcpy(host_output.data(), output, output_count * sizeof(float), cudaMemcpyDeviceToHost));
    double sink_accumulator = 0.0;
    for (float value : host_output) sink_accumulator += value;
    float sink = static_cast<float>(sink_accumulator);
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaFree(input)); CUDA_CHECK(cudaFree(output)); CUDA_CHECK(cudaFree(ha)); CUDA_CHECK(cudaFree(hb));

    std::cout << std::setprecision(9) << "{\"status\":\"PASS\",\"mode\":\"" << o.mode
              << "\",\"variant\":\"" << o.variant << "\",\"grid\":" << o.grid
              << ",\"block\":" << o.block << ",\"stride\":" << o.stride
              << ",\"bytes\":" << o.bytes << ",\"repeats\":" << o.repeats
              << ",\"batches\":" << o.batches << ",\"sink\":" << sink << ",\"gpu_us\":[";
    for (size_t i = 0; i < gpu_us.size(); ++i) { if (i) std::cout << ','; std::cout << gpu_us[i]; }
    std::cout << "],\"host_dispatch_us\":[";
    for (size_t i = 0; i < host_us.size(); ++i) { if (i) std::cout << ','; std::cout << host_us[i]; }
    std::cout << "]}\n";
    return (o.variant == "zero" ? std::fabs(sink) < 1e-12f : std::isfinite(sink)) ? 0 : 2;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
