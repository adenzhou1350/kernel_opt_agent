#include <cuda_runtime.h>

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#define CUDA_CHECK(call)                                                        \
  do {                                                                          \
    cudaError_t status_ = (call);                                                \
    if (status_ != cudaSuccess) {                                                \
      throw std::runtime_error(std::string(#call) + ": " +                     \
                               cudaGetErrorString(status_));                     \
    }                                                                           \
  } while (0)

struct Options {
  std::string mode = "launch";
  int device = 0;
  int blocks = 0;
  int threads = 256;
  int repeats = 1;
  int rounds = 25;
  int warmup = 5;
  int graph_nodes = 128;
  size_t bytes_per_repeat = 16ull << 20;
  size_t dynamic_smem = 0;
};

__global__ void launch_sink_kernel(uint32_t* sink) {
  extern __shared__ unsigned char reserved[];
  const uint32_t index = blockIdx.x * blockDim.x + threadIdx.x;
  sink[index] = index ^ 0x9e3779b9u;
  if (reserved == nullptr) sink[index] ^= 1u;
}

template <int Repeats>
__global__ void barrier_kernel(uint32_t* sink) {
  extern __shared__ uint32_t scratch[];
  const uint32_t tid = threadIdx.x;
  uint32_t value = tid ^ (blockIdx.x * 0x9e3779b9u);
#pragma unroll
  for (int repeat = 0; repeat < Repeats; ++repeat) {
    const uint32_t page = repeat * blockDim.x;
    scratch[page + tid] = value;
    __syncthreads();
    const uint32_t peer = tid + 1 == blockDim.x ? 0 : tid + 1;
    value = scratch[page + peer] + 1u;
  }
  sink[blockIdx.x * blockDim.x + tid] = value;
}

template <int Repeats>
__global__ void load_kernel(const uint4* source, uint32_t* sink,
                            size_t vectors_per_repeat) {
  extern __shared__ unsigned char reserved[];
  const size_t tid = blockIdx.x * blockDim.x + threadIdx.x;
  const size_t workers = gridDim.x * blockDim.x;
  uint32_t checksum = static_cast<uint32_t>(tid);
#pragma unroll
  for (int repeat = 0; repeat < Repeats; ++repeat) {
    const size_t base = static_cast<size_t>(repeat) * vectors_per_repeat;
    for (size_t index = tid; index < vectors_per_repeat; index += workers) {
      const uint4 value = source[base + index];
      checksum ^= value.x + value.y * 3u + value.z * 5u + value.w * 7u;
    }
  }
  sink[tid] = checksum + (reserved == nullptr ? 1u : 0u);
}

template <int Repeats>
__global__ void store_kernel(uint4* destination, size_t vectors_per_repeat) {
  extern __shared__ unsigned char reserved[];
  const size_t tid = blockIdx.x * blockDim.x + threadIdx.x;
  const size_t workers = gridDim.x * blockDim.x;
  const uint32_t value = static_cast<uint32_t>(tid) ^ 0xa5a5a5a5u;
#pragma unroll
  for (int repeat = 0; repeat < Repeats; ++repeat) {
    const size_t base = static_cast<size_t>(repeat) * vectors_per_repeat;
    for (size_t index = tid; index < vectors_per_repeat; index += workers) {
      destination[base + index] = make_uint4(value, value + 1u, value + 2u,
                                             value + 3u);
    }
  }
  if (reserved == nullptr && tid == 0) destination[0].x ^= 1u;
}

int parse_int(const char* text) { return std::stoi(text); }
size_t parse_size(const char* text) { return static_cast<size_t>(std::stoull(text)); }

Options parse_options(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string key = argv[index];
    if (index + 1 >= argc) throw std::invalid_argument("missing value for " + key);
    const char* value = argv[++index];
    if (key == "--mode") options.mode = value;
    else if (key == "--device") options.device = parse_int(value);
    else if (key == "--blocks") options.blocks = parse_int(value);
    else if (key == "--threads") options.threads = parse_int(value);
    else if (key == "--repeats") options.repeats = parse_int(value);
    else if (key == "--rounds") options.rounds = parse_int(value);
    else if (key == "--warmup") options.warmup = parse_int(value);
    else if (key == "--graph-nodes") options.graph_nodes = parse_int(value);
    else if (key == "--bytes-per-repeat") options.bytes_per_repeat = parse_size(value);
    else if (key == "--dynamic-smem") options.dynamic_smem = parse_size(value);
    else throw std::invalid_argument("unknown option " + key);
  }
  if (options.threads <= 0 || options.threads > 1024 || options.rounds <= 0 ||
      options.graph_nodes <= 0 || options.warmup < 0)
    throw std::invalid_argument("invalid launch/timing option");
  const std::vector<int> supported{0, 1, 2, 4, 8, 16};
  if (std::find(supported.begin(), supported.end(), options.repeats) == supported.end())
    throw std::invalid_argument("repeats must be one of 0,1,2,4,8,16");
  if (options.bytes_per_repeat % sizeof(uint4) != 0)
    throw std::invalid_argument("bytes-per-repeat must be divisible by 16");
  return options;
}

template <int Repeats>
void set_attributes(const Options& options, size_t barrier_smem) {
  if (options.dynamic_smem > 0) {
    CUDA_CHECK(cudaFuncSetAttribute(load_kernel<Repeats>, cudaFuncAttributeMaxDynamicSharedMemorySize,
                                    static_cast<int>(options.dynamic_smem)));
    CUDA_CHECK(cudaFuncSetAttribute(store_kernel<Repeats>, cudaFuncAttributeMaxDynamicSharedMemorySize,
                                    static_cast<int>(options.dynamic_smem)));
  }
  if (barrier_smem > 0)
    CUDA_CHECK(cudaFuncSetAttribute(barrier_kernel<Repeats>, cudaFuncAttributeMaxDynamicSharedMemorySize,
                                    static_cast<int>(barrier_smem)));
}

template <int Repeats>
void launch_selected(const Options& options, cudaStream_t stream, uint4* data,
                     uint32_t* sink, size_t vectors_per_repeat,
                     size_t barrier_smem) {
  if (options.mode == "launch")
    launch_sink_kernel<<<options.blocks, options.threads, options.dynamic_smem, stream>>>(sink);
  else if (options.mode == "barrier")
    barrier_kernel<Repeats><<<options.blocks, options.threads, barrier_smem, stream>>>(sink);
  else if (options.mode == "load")
    load_kernel<Repeats><<<options.blocks, options.threads, options.dynamic_smem, stream>>>(data, sink, vectors_per_repeat);
  else if (options.mode == "store")
    store_kernel<Repeats><<<options.blocks, options.threads, options.dynamic_smem, stream>>>(data, vectors_per_repeat);
  else
    throw std::invalid_argument("mode must be launch, barrier, load or store");
}

template <typename Function>
void dispatch_repeats(int repeats, Function function) {
  switch (repeats) {
    case 0: function(std::integral_constant<int, 0>{}); break;
    case 1: function(std::integral_constant<int, 1>{}); break;
    case 2: function(std::integral_constant<int, 2>{}); break;
    case 4: function(std::integral_constant<int, 4>{}); break;
    case 8: function(std::integral_constant<int, 8>{}); break;
    case 16: function(std::integral_constant<int, 16>{}); break;
    default: throw std::invalid_argument("unsupported repeats");
  }
}

int main(int argc, char** argv) {
  try {
    Options options = parse_options(argc, argv);
    CUDA_CHECK(cudaSetDevice(options.device));
    cudaDeviceProp properties{};
    CUDA_CHECK(cudaGetDeviceProperties(&properties, options.device));
    if (options.blocks == 0) options.blocks = properties.multiProcessorCount;
    const size_t workers = static_cast<size_t>(options.blocks) * options.threads;
    const size_t vectors_per_repeat = options.bytes_per_repeat / sizeof(uint4);
    const size_t data_vectors = std::max<size_t>(1, vectors_per_repeat * std::max(1, options.repeats));
    const size_t barrier_smem = std::max(options.dynamic_smem,
        static_cast<size_t>(options.repeats) * options.threads * sizeof(uint32_t));
    if (barrier_smem > properties.sharedMemPerBlockOptin)
      throw std::invalid_argument("requested barrier shared memory exceeds per-block opt-in limit");

    uint4* data = nullptr;
    uint32_t* sink = nullptr;
    CUDA_CHECK(cudaMalloc(&data, data_vectors * sizeof(uint4)));
    CUDA_CHECK(cudaMalloc(&sink, workers * sizeof(uint32_t)));
    CUDA_CHECK(cudaMemset(data, 0x5a, data_vectors * sizeof(uint4)));
    CUDA_CHECK(cudaMemset(sink, 0, workers * sizeof(uint32_t)));
    cudaStream_t stream;
    CUDA_CHECK(cudaStreamCreate(&stream));

    if (options.dynamic_smem > 0)
      CUDA_CHECK(cudaFuncSetAttribute(launch_sink_kernel,
                                     cudaFuncAttributeMaxDynamicSharedMemorySize,
                                     static_cast<int>(options.dynamic_smem)));

    dispatch_repeats(options.repeats, [&](auto repeat_tag) {
      constexpr int repeats = decltype(repeat_tag)::value;
      set_attributes<repeats>(options, barrier_smem);
    });
    cudaGraph_t graph;
    CUDA_CHECK(cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal));
    for (int node = 0; node < options.graph_nodes; ++node) {
      dispatch_repeats(options.repeats, [&](auto repeat_tag) {
        constexpr int repeats = decltype(repeat_tag)::value;
        launch_selected<repeats>(options, stream, data, sink, vectors_per_repeat, barrier_smem);
      });
    }
    CUDA_CHECK(cudaStreamEndCapture(stream, &graph));
    cudaGraphExec_t graph_exec;
    CUDA_CHECK(cudaGraphInstantiate(&graph_exec, graph, nullptr, nullptr, 0));
    for (int warmup = 0; warmup < options.warmup; ++warmup)
      CUDA_CHECK(cudaGraphLaunch(graph_exec, stream));
    CUDA_CHECK(cudaStreamSynchronize(stream));

    cudaEvent_t start, stop;
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));
    std::vector<double> samples;
    for (int round = 0; round < options.rounds; ++round) {
      CUDA_CHECK(cudaEventRecord(start, stream));
      CUDA_CHECK(cudaGraphLaunch(graph_exec, stream));
      CUDA_CHECK(cudaEventRecord(stop, stream));
      CUDA_CHECK(cudaEventSynchronize(stop));
      float elapsed_ms = 0.0f;
      CUDA_CHECK(cudaEventElapsedTime(&elapsed_ms, start, stop));
      samples.push_back(static_cast<double>(elapsed_ms) * 1000.0 / options.graph_nodes);
    }

    std::vector<uint32_t> host_sink(workers);
    CUDA_CHECK(cudaMemcpy(host_sink.data(), sink, workers * sizeof(uint32_t), cudaMemcpyDeviceToHost));
    uint64_t checksum = std::accumulate(host_sink.begin(), host_sink.end(), uint64_t{0});
    if (options.mode == "store") {
      uint4 first{};
      CUDA_CHECK(cudaMemcpy(&first, data, sizeof(first), cudaMemcpyDeviceToHost));
      checksum = static_cast<uint64_t>(first.x) + first.y + first.z + first.w;
    }
    int driver = 0, runtime = 0;
    CUDA_CHECK(cudaDriverGetVersion(&driver));
    CUDA_CHECK(cudaRuntimeGetVersion(&runtime));
    std::cout << std::setprecision(12)
              << "{\"schema_version\":\"cuda-particle-result-v1\","
              << "\"mode\":\"" << options.mode << "\","
              << "\"device\":" << options.device << ","
              << "\"device_name\":\"" << properties.name << "\","
              << "\"compute_capability\":\"" << properties.major << "." << properties.minor << "\","
              << "\"sm_count\":" << properties.multiProcessorCount << ","
              << "\"driver_version\":" << driver << ",\"runtime_version\":" << runtime << ","
              << "\"blocks\":" << options.blocks << ",\"threads\":" << options.threads << ","
              << "\"repeats\":" << options.repeats << ","
              << "\"bytes_per_repeat\":" << options.bytes_per_repeat << ","
              << "\"dynamic_smem_bytes\":" << (options.mode == "barrier" ? barrier_smem : options.dynamic_smem) << ","
              << "\"graph_nodes\":" << options.graph_nodes << ",\"rounds\":" << options.rounds << ","
              << "\"checksum\":" << checksum << ",\"samples_gpu_us\":[";
    for (size_t index = 0; index < samples.size(); ++index) {
      if (index) std::cout << ',';
      std::cout << samples[index];
    }
    std::cout << "]}\n";

    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaGraphExecDestroy(graph_exec));
    CUDA_CHECK(cudaGraphDestroy(graph));
    CUDA_CHECK(cudaStreamDestroy(stream));
    CUDA_CHECK(cudaFree(sink));
    CUDA_CHECK(cudaFree(data));
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    return 1;
  }
}
