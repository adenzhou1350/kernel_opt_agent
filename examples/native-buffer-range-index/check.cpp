// Independent check of a failed model answer's conditional mechanism.
// Synthetic zero-length records do not establish that RDMA registration accepts them.
#include "buffer_range_index.h"
#include <cassert>
#include <iostream>

struct Buffer { uint64_t addr, length; };

int main() {
    const std::vector<Buffer> zero_last{{4096, 64}, {4096, 0}};
    mooncake::BufferRangeIndex last(zero_last);
    // This is the order alleged to enter the fast path and hide the valid MR.
    // Instead the positive interval's exclusive end forces overlap fallback.
    assert(last.overlaps());
    assert(last.findCovering(4096, 1) == -1);

    const std::vector<Buffer> zero_first{{4096, 0}, {4096, 64}};
    mooncake::BufferRangeIndex first(zero_first);
    assert(!first.overlaps());
    assert(first.findCovering(4096, 0) == 1);
    assert(first.findCovering(4096, 1) == 1);
    assert(first.findCovering(4159, 1) == 1);
    assert(first.findCovering(4160, 0) == -1);
    std::cout << "zero-last: overlap fallback; zero-first: valid covering entry; no alleged fast-path miss" << std::endl;
}
