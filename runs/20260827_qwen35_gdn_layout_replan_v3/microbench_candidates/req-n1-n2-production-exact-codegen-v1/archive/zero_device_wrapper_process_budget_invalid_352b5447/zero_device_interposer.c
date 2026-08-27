#define _GNU_SOURCE

#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Runtime half of the zero-device audit.  It is loaded with LD_AUDIT into
 * every phase child and inherited subprocess.  Sensitive entry points are
 * rebound to non-returning blockers before any CUDA implementation executes.
 *
 * la_symbind64 observes normal PLT binding and dlsym/dlvsym lookup.  CUDA's
 * private function-pointer paths are covered separately by rebinding
 * cuGetProcAddress[_v2] and cudaGetDriverEntryPoint[ByVersion], then replacing
 * sensitive returned pointers.
 */

typedef int CUresult;
typedef int cudaError_t;
typedef unsigned long long cuuint64_t;

typedef CUresult (*cu_get_proc_address_fn)(
    const char *, void **, int, cuuint64_t
);
typedef CUresult (*cu_get_proc_address_v2_fn)(
    const char *, void **, int, cuuint64_t, void *
);
typedef cudaError_t (*cuda_get_driver_entry_point_fn)(
    const char *, void **, cuuint64_t, void *
);
typedef cudaError_t (*cuda_get_driver_entry_point_by_version_fn)(
    const char *, void **, int, cuuint64_t, void *
);

static _Atomic(uintptr_t) real_cu_get_proc_address = 0;
static _Atomic(uintptr_t) real_cu_get_proc_address_v2 = 0;
static _Atomic(uintptr_t) real_cuda_get_driver_entry_point = 0;
static _Atomic(uintptr_t) real_cuda_get_driver_entry_point_by_version = 0;
static _Atomic(uintptr_t) real_cuda_get_driver_entry_point_ptsz = 0;
static _Atomic(uintptr_t) real_cuda_get_driver_entry_point_by_version_ptsz = 0;
static int audit_fd = -1;

static size_t bounded_length(const char *value, size_t maximum) {
    size_t length = 0;
    if (value == NULL) {
        return 0;
    }
    while (length < maximum && value[length] != '\0') {
        ++length;
    }
    return length;
}

static void emit_pair(const char *kind, const char *value) {
    char buffer[2304];
    size_t position = 0;
    size_t kind_length;
    size_t value_length;
    if (audit_fd < 0) {
        return;
    }
    kind_length = bounded_length(kind, 96);
    value_length = bounded_length(value, 2048);
    if (kind_length + value_length + 2 > sizeof(buffer)) {
        return;
    }
    memcpy(buffer + position, kind, kind_length);
    position += kind_length;
    buffer[position++] = '|';
    if (value_length != 0) {
        memcpy(buffer + position, value, value_length);
        position += value_length;
    }
    buffer[position++] = '\n';
    /* O_APPEND plus one write keeps records from inherited children intact. */
    (void)write(audit_fd, buffer, position);
}

static int starts_with(const char *value, const char *prefix) {
    size_t length = bounded_length(prefix, 128);
    return value != NULL && strncmp(value, prefix, length) == 0;
}

enum sensitive_kind {
    SENSITIVE_NONE = 0,
    SENSITIVE_DRIVER_LAUNCH = 1,
    SENSITIVE_RUNTIME_LAUNCH = 2,
    SENSITIVE_GRAPH_REPLAY = 3,
    SENSITIVE_CUDA_EVENT = 4,
};

static enum sensitive_kind classify_symbol(const char *name) {
    if (starts_with(name, "cuGraphLaunch") ||
        starts_with(name, "cudaGraphLaunch")) {
        return SENSITIVE_GRAPH_REPLAY;
    }
    if (starts_with(name, "cuEvent") || starts_with(name, "cudaEvent")) {
        return SENSITIVE_CUDA_EVENT;
    }
    if (starts_with(name, "cuptiActivity") ||
        starts_with(name, "cuptiProfiler") ||
        starts_with(name, "cuptiSubscribe") ||
        starts_with(name, "cuptiEvent") ||
        starts_with(name, "cuptiMetric")) {
        return SENSITIVE_CUDA_EVENT;
    }
    if (starts_with(name, "cuProfiler") ||
        starts_with(name, "cudaProfiler")) {
        return SENSITIVE_CUDA_EVENT;
    }
    if (starts_with(name, "cuLaunch")) {
        return SENSITIVE_DRIVER_LAUNCH;
    }
    if (starts_with(name, "cudaLaunch") || starts_with(name, "__cudaLaunch")) {
        return SENSITIVE_RUNTIME_LAUNCH;
    }
    return SENSITIVE_NONE;
}

__attribute__((noreturn)) static void block_driver_launch(void) {
    emit_pair("INVOKE", "cuda_driver_launch");
    _exit(191);
}

__attribute__((noreturn)) static void block_runtime_launch(void) {
    emit_pair("INVOKE", "cuda_runtime_launch");
    _exit(191);
}

__attribute__((noreturn)) static void block_graph_replay(void) {
    emit_pair("INVOKE", "cuda_graph_replay");
    _exit(191);
}

__attribute__((noreturn)) static void block_cuda_event(void) {
    emit_pair("INVOKE", "cuda_event_or_timer");
    _exit(191);
}

__attribute__((noreturn)) static void block_auditor_failure(void) {
    emit_pair("AUDITOR_FAILURE", "missing_real_dynamic_lookup");
    _exit(192);
}

static uintptr_t blocker_for(const char *name) {
    switch (classify_symbol(name)) {
        case SENSITIVE_DRIVER_LAUNCH:
            return (uintptr_t)&block_driver_launch;
        case SENSITIVE_RUNTIME_LAUNCH:
            return (uintptr_t)&block_runtime_launch;
        case SENSITIVE_GRAPH_REPLAY:
            return (uintptr_t)&block_graph_replay;
        case SENSITIVE_CUDA_EVENT:
            return (uintptr_t)&block_cuda_event;
        default:
            return 0;
    }
}

static void rewrite_dynamic_result(const char *symbol, void **target) {
    uintptr_t replacement = blocker_for(symbol);
    if (replacement != 0 && target != NULL) {
        *target = (void *)replacement;
        emit_pair("DYNAMIC_REWRITE", symbol);
    }
}

static CUresult audited_cu_get_proc_address(
    const char *symbol,
    void **target,
    int cuda_version,
    cuuint64_t flags
) {
    cu_get_proc_address_fn real = (cu_get_proc_address_fn)(uintptr_t)
        atomic_load(&real_cu_get_proc_address);
    if (real == NULL) {
        block_auditor_failure();
    }
    CUresult result = real(symbol, target, cuda_version, flags);
    if (result == 0) {
        rewrite_dynamic_result(symbol, target);
    }
    return result;
}

static CUresult audited_cu_get_proc_address_v2(
    const char *symbol,
    void **target,
    int cuda_version,
    cuuint64_t flags,
    void *status
) {
    cu_get_proc_address_v2_fn real = (cu_get_proc_address_v2_fn)(uintptr_t)
        atomic_load(&real_cu_get_proc_address_v2);
    if (real == NULL) {
        block_auditor_failure();
    }
    CUresult result = real(symbol, target, cuda_version, flags, status);
    if (result == 0) {
        rewrite_dynamic_result(symbol, target);
    }
    return result;
}

static cudaError_t audited_cuda_get_driver_entry_point(
    const char *symbol,
    void **target,
    cuuint64_t flags,
    void *status
) {
    cuda_get_driver_entry_point_fn real =
        (cuda_get_driver_entry_point_fn)(uintptr_t)
        atomic_load(&real_cuda_get_driver_entry_point);
    if (real == NULL) {
        block_auditor_failure();
    }
    cudaError_t result = real(symbol, target, flags, status);
    if (result == 0) {
        rewrite_dynamic_result(symbol, target);
    }
    return result;
}

static cudaError_t audited_cuda_get_driver_entry_point_by_version(
    const char *symbol,
    void **target,
    int cuda_version,
    cuuint64_t flags,
    void *status
) {
    cuda_get_driver_entry_point_by_version_fn real =
        (cuda_get_driver_entry_point_by_version_fn)(uintptr_t)
        atomic_load(&real_cuda_get_driver_entry_point_by_version);
    if (real == NULL) {
        block_auditor_failure();
    }
    cudaError_t result = real(symbol, target, cuda_version, flags, status);
    if (result == 0) {
        rewrite_dynamic_result(symbol, target);
    }
    return result;
}

static cudaError_t audited_cuda_get_driver_entry_point_ptsz(
    const char *symbol,
    void **target,
    cuuint64_t flags,
    void *status
) {
    cuda_get_driver_entry_point_fn real =
        (cuda_get_driver_entry_point_fn)(uintptr_t)
        atomic_load(&real_cuda_get_driver_entry_point_ptsz);
    if (real == NULL) {
        block_auditor_failure();
    }
    cudaError_t result = real(symbol, target, flags, status);
    if (result == 0) {
        rewrite_dynamic_result(symbol, target);
    }
    return result;
}

static cudaError_t audited_cuda_get_driver_entry_point_by_version_ptsz(
    const char *symbol,
    void **target,
    int cuda_version,
    cuuint64_t flags,
    void *status
) {
    cuda_get_driver_entry_point_by_version_fn real =
        (cuda_get_driver_entry_point_by_version_fn)(uintptr_t)
        atomic_load(&real_cuda_get_driver_entry_point_by_version_ptsz);
    if (real == NULL) {
        block_auditor_failure();
    }
    cudaError_t result = real(symbol, target, cuda_version, flags, status);
    if (result == 0) {
        rewrite_dynamic_result(symbol, target);
    }
    return result;
}

unsigned int la_version(unsigned int version) {
    const char *path = getenv("KERNEL_OPT_ZERO_DEVICE_LOG");
    (void)version;
    if (path != NULL && path[0] != '\0') {
        audit_fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
    }
    emit_pair("AUDITOR", "READY");
    return LAV_CURRENT;
}

unsigned int la_objopen(
    struct link_map *map,
    Lmid_t lmid,
    uintptr_t *cookie
) {
    (void)lmid;
    (void)cookie;
    if (map != NULL && map->l_name != NULL && map->l_name[0] != '\0') {
        emit_pair("OBJECT", map->l_name);
    }
    return LA_FLG_BINDTO | LA_FLG_BINDFROM;
}

uintptr_t la_symbind64(
    Elf64_Sym *symbol,
    unsigned int index,
    uintptr_t *reference_cookie,
    uintptr_t *definition_cookie,
    unsigned int *flags,
    const char *name
) {
    uintptr_t original = (uintptr_t)symbol->st_value;
    uintptr_t replacement;
    (void)index;
    (void)reference_cookie;
    (void)definition_cookie;
    (void)flags;

    if (strcmp(name, "cuGetProcAddress") == 0) {
        atomic_store(&real_cu_get_proc_address, original);
        return (uintptr_t)&audited_cu_get_proc_address;
    }
    if (strcmp(name, "cuGetProcAddress_v2") == 0) {
        atomic_store(&real_cu_get_proc_address_v2, original);
        return (uintptr_t)&audited_cu_get_proc_address_v2;
    }
    if (strcmp(name, "cudaGetDriverEntryPoint") == 0) {
        atomic_store(&real_cuda_get_driver_entry_point, original);
        return (uintptr_t)&audited_cuda_get_driver_entry_point;
    }
    if (strcmp(name, "cudaGetDriverEntryPointByVersion") == 0) {
        atomic_store(&real_cuda_get_driver_entry_point_by_version, original);
        return (uintptr_t)&audited_cuda_get_driver_entry_point_by_version;
    }
    if (strcmp(name, "cudaGetDriverEntryPoint_ptsz") == 0) {
        atomic_store(&real_cuda_get_driver_entry_point_ptsz, original);
        return (uintptr_t)&audited_cuda_get_driver_entry_point_ptsz;
    }
    if (strcmp(name, "cudaGetDriverEntryPointByVersion_ptsz") == 0) {
        atomic_store(
            &real_cuda_get_driver_entry_point_by_version_ptsz, original
        );
        return (
            (uintptr_t)&audited_cuda_get_driver_entry_point_by_version_ptsz
        );
    }

    replacement = blocker_for(name);
    if (replacement != 0) {
        emit_pair("BIND", name);
        return replacement;
    }
    return original;
}

void la_preinit(uintptr_t *cookie) {
    (void)cookie;
    emit_pair("AUDITOR", "PREINIT");
}
