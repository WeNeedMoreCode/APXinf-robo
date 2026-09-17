/* ACLGraph probe v2: try ALL capture modes, async memcpy, full WARN output.
 *
 * Splits the two candidate blockers apart when run under different CANN
 * containers on the same host driver:
 *   - CANN 8.5.1 container  (apxinf_npu)          -> symbol present, docs say 9.0+
 *   - CANN 9.0.1 container  (cann:9.0.1-310p-...) -> documented ACL Graph support
 * If 9.0.1 captures and 8.5.1 does not: CANN version is the gate, host driver
 * is fine (container-level fix, no downtime). If both fail: host driver.
 */
#include <stdio.h>
#include <string.h>
#include "acl/acl.h"
#include "acl/acl_rt.h"

static const char *mode_name(aclmdlRICaptureMode m) {
    switch (m) {
        case ACL_MODEL_RI_CAPTURE_MODE_GLOBAL: return "GLOBAL";
        case ACL_MODEL_RI_CAPTURE_MODE_THREAD_LOCAL: return "THREAD_LOCAL";
        case ACL_MODEL_RI_CAPTURE_MODE_RELAXED: return "RELAXED";
    }
    return "?";
}

static int try_mode(aclmdlRICaptureMode mode, void *dev, char *host) {
    aclrtStream s = NULL;
    aclmdlRI ri = NULL;
    char back[1024];
    int ok = 0;

    printf("\n---- capture mode %s ----\n", mode_name(mode));
    if (aclrtCreateStream(&s) != 0) { printf("  create stream failed\n"); return 0; }
    // warm the async path on this stream (outside capture)
    if (aclrtMemcpyAsync(dev, 1024, host, 1024, ACL_MEMCPY_HOST_TO_DEVICE, s) != 0 ||
        aclrtSynchronizeStream(s) != 0) { printf("  warm failed\n"); goto out; }

    aclError b = aclmdlRICaptureBegin(s, mode);
    printf("  CaptureBegin ret=%d\n", (int)b);
    if (b != 0) goto out;

    if (aclrtMemcpyAsync(dev, 1024, host, 1024, ACL_MEMCPY_HOST_TO_DEVICE, s) != 0) {
        printf("  captured memcpyAsync failed\n");
        aclmdlRIAbort(s);
        goto out;
    }
    if (aclmdlRICaptureEnd(s, &ri) != 0) { printf("  CaptureEnd failed\n"); goto out; }
    printf("  CaptureEnd ok, modelRI=%p\n", ri);

    memset(host, 0xCD, 1024);
    if (aclmdlRIExecuteAsync(ri, s) != 0 || aclrtSynchronizeStream(s) != 0) {
        printf("  ExecuteAsync failed\n");
        goto out;
    }
    if (aclrtMemcpy(back, 1024, dev, 1024, ACL_MEMCPY_DEVICE_TO_HOST) != 0) {
        printf("  d2h failed\n");
        goto out;
    }
    ok = memcmp(host, back, 1024) == 0;
    printf("  replay re-captured 0xCD pattern: %s\n", ok ? "YES" : "NO");
    aclmdlRIDestroy(ri);
    ri = NULL;
out:
    if (ri) aclmdlRIDestroy(ri);
    aclrtDestroyStream(s);
    return ok;
}

int main() {
    void *dev = NULL;
    char host[1024];
    memset(host, 0xAB, sizeof(host));

    printf("== acl_ri_probe_v2 ==\n");
    if (aclInit(NULL) != 0) return 1;
    if (aclrtSetDevice(0) != 0) return 1;
    if (aclrtMalloc(&dev, 1024, ACL_MEM_MALLOC_HUGE_FIRST) != 0) return 1;

    int g = try_mode(ACL_MODEL_RI_CAPTURE_MODE_GLOBAL, dev, host);
    int t = try_mode(ACL_MODEL_RI_CAPTURE_MODE_THREAD_LOCAL, dev, host);
    int r = try_mode(ACL_MODEL_RI_CAPTURE_MODE_RELAXED, dev, host);
    printf("\nRESULT: GLOBAL=%d THREAD_LOCAL=%d RELAXED=%d\n", g, t, r);
    printf((g || t || r) ? "ACLGRAPH_AVAILABLE\n" : "ACLGRAPH_UNAVAILABLE\n");

    aclrtFree(dev);
    aclrtResetDevice(0);
    aclFinalize();
    return 0;
}
