#include <acl/acl_base.h>
#include <acl/acl_mdl.h>
#include <acl/acl_rt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/data/apxinf/om_cache/tl_dyn/prefix_real.om";
    setbuf(stdout, NULL);
    if (aclInit(NULL) != ACL_SUCCESS) {}
    aclrtSetDevice(0);
    aclrtContext c; aclrtCreateContext(&c, 0);
    uint32_t m = 0;
    if (aclmdlLoadFromFile(path, &m) != ACL_SUCCESS) { printf("load fail\n"); return 1; }
    aclmdlDesc *d = aclmdlCreateDesc();
    aclmdlGetDesc(d, m);
    size_t nin = aclmdlGetNumInputs(d);
    printf("n_in=%zu\n", nin);
    for (size_t i = 0; i < nin && i < 20; i++) {
        aclmdlIODims dm; memset(&dm, 0, sizeof(dm));
        aclmdlGetInputDims(d, i, &dm);
        printf("in[%zu] dimCount=%zu dims=", i, dm.dimCount);
        for (size_t k = 0; k < dm.dimCount; k++) printf("%lld,", (long long)dm.dims[k]);
        printf("\n");
    }
    for (size_t i = nin - 3; i < nin; i++) {
        aclmdlIODims dm; memset(&dm, 0, sizeof(dm));
        aclmdlGetInputDims(d, i, &dm);
        printf("in[%zu] dimCount=%zu dims[0]=%lld\n", i, dm.dimCount, (long long)dm.dims[0]);
    }
    // 假设试验：A) SetDims index=gear 输入位（262）+ 14 动态值；
    // B) 直写 gear buffer 14 值 + 裸 execute → GetCurOutputDims 判分支
    if (argc > 2) {
        int64_t vals[128];
        size_t nv = 0;
        FILE *df = fopen(argv[2], "r");
        while (nv < 128 && fscanf(df, "%lld,", &vals[nv]) == 1) nv++;
        fclose(df);
        void **db = calloc(nin, sizeof(void *));
        aclmdlDataset *ds = aclmdlCreateDataset();
        size_t *szs = calloc(nin, sizeof(size_t));
        for (size_t i = 0; i < nin; i++) {
            szs[i] = aclmdlGetInputSizeByIndex(d, i);
            aclrtMalloc(&db[i], szs[i], ACL_MEM_MALLOC_HUGE_FIRST);
            aclmdlAddDatasetBuffer(ds, aclCreateDataBuffer(db[i], szs[i]));
        }
        size_t nout = aclmdlGetNumOutputs(d);
        void **ob = calloc(nout, sizeof(void *));
        aclmdlDataset *ods = aclmdlCreateDataset();
        for (size_t i = 0; i < nout; i++) {
            size_t sz = aclmdlGetOutputSizeByIndex(d, i);
            aclrtMalloc(&ob[i], sz, ACL_MEM_MALLOC_HUGE_FIRST);
            aclmdlAddDatasetBuffer(ods, aclCreateDataBuffer(ob[i], sz));
        }
        aclmdlIODims want;
        memset(&want, 0, sizeof(want));
        want.dimCount = nv;
        for (size_t i = 0; i < nv; i++) want.dims[i] = (size_t)vals[i];
        // tryB1：直写 gear buffer int32 动态维值（spike gear 输入 12B=3×int32
        // ⇒ 元素类型 int32；值 = 动态维值表）+ 裸 execute
        printf("[tryB] gear input size=%zu\n", szs[nin - 1]);
        int *gb = (int *)db[nin - 1];
        for (size_t i = 0; i < nv && (i + 1) * 4 <= szs[nin - 1]; i++) gb[i] = (int)vals[i];
        aclError re2 = aclmdlExecute(m, ds, ods);
        aclmdlIODims cur2; memset(&cur2, 0, sizeof(cur2));
        aclmdlGetCurOutputDims(d, 0, &cur2);
        printf("[tryB1] direct-buffer(int32 dims) execute rc=%d curOut0=%lld\n", (int)re2,
               cur2.dimCount > 0 ? (long long)cur2.dims[0] : -1LL);
        if (re2 != ACL_SUCCESS) {
            // tryB2：值不灵 → 试档下标（0 起）
            for (size_t i = 0; i * 4 < szs[nin - 1]; i++) gb[i] = 0;
            aclError re3 = aclmdlExecute(m, ds, ods);
            aclmdlIODims cur3; memset(&cur3, 0, sizeof(cur3));
            aclmdlGetCurOutputDims(d, 0, &cur3);
            printf("[tryB2] direct-buffer(int32 idx=0) execute rc=%d curOut0=%lld\n", (int)re3,
                   cur3.dimCount > 0 ? (long long)cur3.dims[0] : -1LL);
        }
    }
    return 0;
}
