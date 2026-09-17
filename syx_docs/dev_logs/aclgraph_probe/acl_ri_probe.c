/* ACLGraph ground-truth probe: drive aclmdlRI* capture directly over C.
 *
 * Answers, step by step with aclError codes printed:
 *   1. can this host (driver 26.0.rc1 + CANN 8.5.1 + 310P3) capture at all
 *   2. does a captured H2D memcpy replay as a graph
 *   3. does async execute work
 *
 * Build & run (container):
 *   gcc acl_ri_probe.c -o acl_ri_probe -I/usr/local/Ascend/ascend-toolkit/latest/include \
 *       -L/usr/local/Ascend/ascend-toolkit/latest/lib64 -lascendcl
 *   ASCEND_RT_VISIBLE_DEVICES=5 LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/lib64 \
 *       ./acl_ri_probe
 */
#include <stdio.h>
#include <string.h>
#include "acl/acl.h"
#include "acl/acl_rt.h"

static int step(const char *name, aclError code) {
    printf("step %-28s ret=%d\n", name, (int)code);
    return code != 0;
}

int main() {
    aclrtStream stream = NULL;
    aclmdlRI ri = NULL;
    aclmdlRICaptureStatus status = ACL_MODEL_RI_CAPTURE_STATUS_NONE;

    if (step("aclInit", aclInit(NULL))) return 1;
    if (step("aclrtSetDevice", aclrtSetDevice(0))) return 1;
    if (step("aclrtCreateStream", aclrtCreateStream(&stream))) return 1;

    // Device memory + one H2D copy as the captured workload.
    void *dev = NULL;
    if (step("aclrtMalloc", aclrtMalloc(&dev, 1024, ACL_MEM_MALLOC_HUGE_FIRST))) return 1;
    char host[1024];
    memset(host, 0xAB, sizeof(host));

    // Warm the copy once (capture usually needs a primed path).
    if (step("warm memcpy", aclrtMemcpy(dev, 1024, host, 1024, ACL_MEMCPY_HOST_TO_DEVICE))) return 1;
    if (step("sync", aclrtSynchronizeStream(stream))) return 1;

    // ---- capture ----
    if (step("aclmdlRICaptureBegin(THREAD_LOCAL)",
             aclmdlRICaptureBegin(stream, ACL_MODEL_RI_CAPTURE_MODE_THREAD_LOCAL))) goto abort;
    if (step("captured memcpy", aclrtMemcpy(dev, 1024, host, 1024, ACL_MEMCPY_HOST_TO_DEVICE))) goto abort;
    if (step("aclmdlRICaptureEnd", aclmdlRICaptureEnd(stream, &ri))) goto abort;
    printf("modelRI handle: %p\n", ri);

    if (step("aclmdlRICaptureGetInfo", aclmdlRICaptureGetInfo(stream, &status, &ri)))
        goto abort;
    printf("post-capture status=%d (0=NONE 1=ACTIVE 2=INVALIDATED)\n", (int)status);

    // ---- replay: mutate host, re-copy old pattern, replay, read back ----
    memset(host, 0xCD, sizeof(host));
    if (step("aclmdlRIExecuteAsync", aclmdlRIExecuteAsync(ri, stream))) goto abort;
    if (step("sync after replay", aclrtSynchronizeStream(stream))) goto abort;

    char back[1024];
    if (step("d2h", aclrtMemcpy(back, 1024, dev, 1024, ACL_MEMCPY_DEVICE_TO_HOST))) goto abort;
    int mism = memcmp(host, back, 1024) != 0;
    printf("replayed copy matches post-mutation host pattern: %s\n", mism ? "NO" : "YES");

    step("aclmdlRIDestroy", aclmdlRIDestroy(ri));
    step("aclrtFree", aclrtFree(dev));
    step("aclrtDestroyStream", aclrtDestroyStream(stream));
    step("aclrtResetDevice", aclrtResetDevice(0));
    step("aclFinalize", aclFinalize());
    printf(mism ? "PROBE_PARTIAL (capture ok, replay semantics unclear)\n" : "PROBE_OK\n");
    return 0;

abort:
    aclmdlRIAbort(stream);
    printf("PROBE_ABORTED\n");
    return 1;
}
