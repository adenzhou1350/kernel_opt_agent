#include <cuda_runtime.h>

#include <cstdio>
#include <cstdlib>

int main(int argc, char** argv) {
  int device = argc > 1 ? std::atoi(argv[1]) : 0;
  cudaDeviceProp p{};
  cudaError_t status = cudaGetDeviceProperties(&p, device);
  if (status != cudaSuccess) {
    std::fprintf(stderr, "cudaGetDeviceProperties failed: %s\n", cudaGetErrorString(status));
    return 1;
  }
  std::printf(
      "{\"architecture\":\"sm_%d%d\",\"compute_capability\":\"%d.%d\","
      "\"sm_count\":%d,\"memory_bytes\":%llu,\"warp_size\":%d,"
      "\"registers_per_sm\":%d,\"shared_memory_per_sm_bytes\":%llu,"
      "\"shared_memory_per_block_bytes\":%llu,"
      "\"shared_memory_per_block_optin_bytes\":%llu,"
      "\"max_threads_per_sm\":%d,\"max_threads_per_block\":%d}\n",
      p.major, p.minor, p.major, p.minor, p.multiProcessorCount,
      static_cast<unsigned long long>(p.totalGlobalMem), p.warpSize,
      p.regsPerMultiprocessor,
      static_cast<unsigned long long>(p.sharedMemPerMultiprocessor),
      static_cast<unsigned long long>(p.sharedMemPerBlock),
      static_cast<unsigned long long>(p.sharedMemPerBlockOptin),
      p.maxThreadsPerMultiProcessor, p.maxThreadsPerBlock);
  return 0;
}
