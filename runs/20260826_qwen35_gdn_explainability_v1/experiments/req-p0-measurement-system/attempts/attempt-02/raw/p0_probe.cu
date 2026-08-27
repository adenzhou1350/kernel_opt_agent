#include <cuda_runtime.h>

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#define CUDA_CHECK(call) do { cudaError_t status_ = (call); if (status_ != cudaSuccess) throw std::runtime_error(std::string(#call) + ": " + cudaGetErrorString(status_)); } while (0)

struct Options {
  int device = 0;
  int rounds = 31;
  int warm_samples = 15;
  int graph_nodes = 64;
  int blocks = 170;
  int threads = 256;
  int arithmetic_repeats = 1024;
  int preheat_ms = 1800;
};

int parse_int(const char* text) { return std::stoi(text); }

Options parse_options(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string key = argv[index];
    if (index + 1 >= argc) throw std::invalid_argument("missing value for " + key);
    const int value = parse_int(argv[++index]);
    if (key == "--device") options.device = value;
    else if (key == "--rounds") options.rounds = value;
    else if (key == "--warm-samples") options.warm_samples = value;
    else if (key == "--graph-nodes") options.graph_nodes = value;
    else if (key == "--blocks") options.blocks = value;
    else if (key == "--threads") options.threads = value;
    else if (key == "--arithmetic-repeats") options.arithmetic_repeats = value;
    else if (key == "--preheat-ms") options.preheat_ms = value;
    else throw std::invalid_argument("unknown option " + key);
  }
  if (options.rounds < 9 || options.warm_samples < 9 || options.graph_nodes < 1 ||
      options.blocks < 1 || options.threads < 1 || options.threads > 1024 ||
      options.arithmetic_repeats < 1 || options.preheat_ms < 0)
    throw std::invalid_argument("invalid P0 option");
  return options;
}

__global__ void zero_work_kernel(uint32_t* sink) {
  const uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
  sink[tid] = tid ^ 0x5a5a5a5au;
}

__global__ void positive_work_kernel(uint32_t* sink, int repeats) {
  uint32_t value = static_cast<uint32_t>(blockIdx.x * blockDim.x + threadIdx.x) ^ 0x9e3779b9u;
  #pragma unroll 4
  for (int index = 0; index < repeats; ++index)
    value = value * 1664525u + 1013904223u;
  sink[blockIdx.x * blockDim.x + threadIdx.x] = value | 1u;
}

double elapsed_us(cudaEvent_t start, cudaEvent_t stop) {
  CUDA_CHECK(cudaEventSynchronize(stop));
  float elapsed_ms = 0.0f;
  CUDA_CHECK(cudaEventElapsedTime(&elapsed_ms, start, stop));
  return static_cast<double>(elapsed_ms) * 1000.0;
}

template <typename Launcher>
double time_direct(cudaStream_t stream, cudaEvent_t start, cudaEvent_t stop,
                   int launches, Launcher launch) {
  CUDA_CHECK(cudaEventRecord(start, stream));
  for (int index = 0; index < launches; ++index) launch(stream);
  CUDA_CHECK(cudaEventRecord(stop, stream));
  return elapsed_us(start, stop) / launches;
}

template <typename Launcher>
cudaGraphExec_t make_graph(cudaStream_t stream, int nodes, Launcher launch,
                           cudaGraph_t* graph) {
  CUDA_CHECK(cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal));
  for (int index = 0; index < nodes; ++index) launch(stream);
  CUDA_CHECK(cudaStreamEndCapture(stream, graph));
  cudaGraphExec_t executable;
  CUDA_CHECK(cudaGraphInstantiate(&executable, *graph, nullptr, nullptr, 0));
  return executable;
}

double time_graph(cudaStream_t stream, cudaEvent_t start, cudaEvent_t stop,
                  cudaGraphExec_t graph, int nodes) {
  CUDA_CHECK(cudaEventRecord(start, stream));
  CUDA_CHECK(cudaGraphLaunch(graph, stream));
  CUDA_CHECK(cudaEventRecord(stop, stream));
  return elapsed_us(start, stop) / nodes;
}

void print_array(const char* name, const std::vector<double>& values, bool comma) {
  std::cout << (comma ? ",\"" : "\"") << name << "\":[";
  for (size_t index = 0; index < values.size(); ++index) {
    if (index) std::cout << ',';
    std::cout << values[index];
  }
  std::cout << ']';
}

int main(int argc, char** argv) {
  try {
    const Options options = parse_options(argc, argv);
    CUDA_CHECK(cudaSetDevice(options.device));
    cudaDeviceProp properties{};
    CUDA_CHECK(cudaGetDeviceProperties(&properties, options.device));
    const size_t workers = static_cast<size_t>(options.blocks) * options.threads;
    uint32_t* sink = nullptr;
    CUDA_CHECK(cudaMalloc(&sink, workers * sizeof(uint32_t)));
    CUDA_CHECK(cudaMemset(sink, 0, workers * sizeof(uint32_t)));
    cudaStream_t stream;
    CUDA_CHECK(cudaStreamCreate(&stream));
    cudaEvent_t start, stop;
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));

    const auto zero = [&](cudaStream_t selected) {
      zero_work_kernel<<<options.blocks, options.threads, 0, selected>>>(sink);
      CUDA_CHECK(cudaGetLastError());
    };
    const auto positive = [&](cudaStream_t selected) {
      positive_work_kernel<<<options.blocks, options.threads, 0, selected>>>(sink, options.arithmetic_repeats);
      CUDA_CHECK(cudaGetLastError());
    };

    std::vector<double> cold_first;
    for (int index = 0; index < 3; ++index)
      cold_first.push_back(time_direct(stream, start, stop, 1, positive));

    const auto preheat_start = std::chrono::steady_clock::now();
    do {
      for (int index = 0; index < options.graph_nodes; ++index) positive(stream);
      CUDA_CHECK(cudaStreamSynchronize(stream));
    } while (std::chrono::duration_cast<std::chrono::milliseconds>(
                 std::chrono::steady_clock::now() - preheat_start).count() < options.preheat_ms);

    cudaGraph_t graph{};
    cudaGraphExec_t graph_exec = make_graph(stream, options.graph_nodes, positive, &graph);
    for (int index = 0; index < 5; ++index) {
      CUDA_CHECK(cudaGraphLaunch(graph_exec, stream));
      CUDA_CHECK(cudaStreamSynchronize(stream));
    }

    // CUDA events and their timestamp path are themselves warmed before the
    // bracket distribution; cold launch evidence was preserved above.
    for (int index = 0; index < 20; ++index) {
      CUDA_CHECK(cudaEventRecord(start, stream));
      CUDA_CHECK(cudaEventRecord(stop, stream));
      (void)elapsed_us(start, stop);
    }

    std::vector<double> timer, zero_samples, positive_samples, graph_samples, direct_samples, warm_samples;
    for (int round = 0; round < options.rounds; ++round) {
      CUDA_CHECK(cudaEventRecord(start, stream));
      CUDA_CHECK(cudaEventRecord(stop, stream));
      timer.push_back(elapsed_us(start, stop));
      zero_samples.push_back(time_direct(stream, start, stop, options.graph_nodes, zero));
      positive_samples.push_back(time_direct(stream, start, stop, options.graph_nodes, positive));
      if ((round & 1) == 0) {
        direct_samples.push_back(time_direct(stream, start, stop, options.graph_nodes, positive));
        graph_samples.push_back(time_graph(stream, start, stop, graph_exec, options.graph_nodes));
      } else {
        graph_samples.push_back(time_graph(stream, start, stop, graph_exec, options.graph_nodes));
        direct_samples.push_back(time_direct(stream, start, stop, options.graph_nodes, positive));
      }
    }
    for (int index = 0; index < options.warm_samples; ++index)
      warm_samples.push_back(time_direct(stream, start, stop, 1, positive));

    std::vector<uint32_t> host_sink(workers);
    CUDA_CHECK(cudaMemcpy(host_sink.data(), sink, workers * sizeof(uint32_t), cudaMemcpyDeviceToHost));
    const uint64_t checksum = std::accumulate(host_sink.begin(), host_sink.end(), uint64_t{0});
    int driver_version = 0, runtime_version = 0;
    CUDA_CHECK(cudaDriverGetVersion(&driver_version));
    CUDA_CHECK(cudaRuntimeGetVersion(&runtime_version));
    std::cout << std::setprecision(12) << '{'
              << "\"schema_version\":\"p0-native-probe-v1\","
              << "\"device_name\":\"" << properties.name << "\","
              << "\"compute_capability\":\"" << properties.major << '.' << properties.minor << "\","
              << "\"sm_count\":" << properties.multiProcessorCount << ','
              << "\"driver_version\":" << driver_version << ','
              << "\"runtime_version\":" << runtime_version << ','
              << "\"blocks\":" << options.blocks << ','
              << "\"threads\":" << options.threads << ','
              << "\"graph_nodes\":" << options.graph_nodes << ','
              << "\"arithmetic_repeats\":" << options.arithmetic_repeats << ','
              << "\"sink_checksum\":" << checksum << ',';
    print_array("timer_overhead_us", timer, false);
    print_array("zero_work_us", zero_samples, true);
    print_array("positive_work_us", positive_samples, true);
    print_array("graph_us", graph_samples, true);
    print_array("direct_us", direct_samples, true);
    print_array("cold_region_us", cold_first, true);
    print_array("warm_us", warm_samples, true);
    std::cout << "}\n";

    CUDA_CHECK(cudaGraphExecDestroy(graph_exec));
    CUDA_CHECK(cudaGraphDestroy(graph));
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaStreamDestroy(stream));
    CUDA_CHECK(cudaFree(sink));
    return checksum == 0 ? 2 : 0;
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    return 1;
  }
}
