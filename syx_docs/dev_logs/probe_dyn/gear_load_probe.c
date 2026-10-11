// gear_load_probe.c — 动态档 OM 装载路径对拍：aclmdlLoadFromFile vs
// aclmdlLoadFromMem（serve 的 geb_model_load 走 FromMem，装载后
// GetInputDynamicGearCount=0——档位信息疑似只在文件装载路径存活）
#include <acl/acl_base.h>
#include <acl/acl_mdl.h>
#include <acl/acl_rt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/data/apxinf/om_cache/tl_dyn/prefix_real.om";
    if (aclInit(NULL) != ACL_SUCCESS) printf("[probe] aclInit nonzero (continue)\n");
    if (aclrtSetDevice(0) != ACL_SUCCESS) { printf("setdev fail\n"); return 1; }
    aclrtContext ctx;
    aclrtCreateContext(&ctx, 0);

    // SetDims 全维匹配试验（S2 同式：index=0 + 全部动态输入完整维拼接。
    // dims[]/n 由 argv[2] 指定文件读（逗号分隔）——档表就是构图期自算值）
    uint32_t smid = 0;
    if (aclmdlLoadFromFile(path, &smid) == ACL_SUCCESS) {
        aclmdlDesc *sd = aclmdlCreateDesc();
        aclmdlGetDesc(sd, smid);
        size_t sg = 0;
        aclmdlGetInputDynamicGearCount(sd, (size_t)-1, &sg);
        printf("[probe] SetDims 试验载体: gears=%zu n_in=%zu\n", sg, aclmdlGetNumInputs(sd));
        if (argc > 2) {
            FILE *df = fopen(argv[2], "r");
            if (df) {
                int64_t vals[128];
                size_t nv = 0;
                while (nv < 128 && fscanf(df, "%lld,", &vals[nv]) == 1) nv++;
                fclose(df);
                // dataset 全输入 buffer（含 gear-info 尾输入）
                size_t nin = aclmdlGetNumInputs(sd);
                void **db = calloc(nin, sizeof(void *));
                aclmdlDataset *ds = aclmdlCreateDataset();
                for (size_t i = 0; i < nin; i++) {
                    size_t sz = aclmdlGetInputSizeByIndex(sd, i);
                    aclrtMalloc(&db[i], sz, ACL_MEM_MALLOC_HUGE_FIRST);
                    aclmdlAddDatasetBuffer(ds, aclCreateDataBuffer(db[i], sz));
                }
                aclmdlIODims want;
                memset(&want, 0, sizeof(want));
                want.dimCount = nv;
                for (size_t i = 0; i < nv; i++) want.dims[i] = (size_t)vals[i];
                aclError rc = aclmdlSetInputDynamicDims(smid, ds, 0, &want);
                printf("[probe] SetDims(%zu vals): rc=%d\n", nv, (int)rc);
                for (size_t i = 0; i < nin; i++) {
                    aclDestroyDataBuffer(aclmdlGetDatasetBuffer(ds, i));
                    aclrtFree(db[i]);
                }
                aclmdlDestroyDataset(ds);
            }
        }
        aclmdlDestroyDesc(sd);
        aclmdlUnload(smid);
    }

    uint32_t mid1 = 0;
    if (aclmdlLoadFromFile(path, &mid1) == ACL_SUCCESS) {
        aclmdlDesc *d = aclmdlCreateDesc();
        aclmdlGetDesc(d, mid1);
        size_t g = 0;
        aclError rc = aclmdlGetInputDynamicGearCount(d, (size_t)-1, &g);
        printf("[probe] LoadFromFile: gears=%zu rc=%d n_in=%zu\n", g, (int)rc, aclmdlGetNumInputs(d));
        if (g > 0 && g <= 128) {
            aclmdlIODims gd[128];
            aclError r2 = aclmdlGetInputDynamicDims(d, (size_t)-1, gd, g);
            printf("[probe] DynamicDims(-1): rc=%d dimCount=%zu d0=%lld\n", (int)r2,
                   r2 == 0 ? gd[0].dimCount : (size_t)0,
                   r2 == 0 && gd[0].dimCount > 0 ? (long long)gd[0].dims[0] : -1LL);
            // 逐输入 index 变体（-1 失败时的 fallback 取证）
            if (r2 != 0) {
                for (size_t idx = 0; idx < 4 && idx < aclmdlGetNumInputs(d); idx++) {
                    aclmdlIODims gd2[128];
                    aclError r3 = aclmdlGetInputDynamicDims(d, idx, gd2, g);
                    printf("[probe] DynamicDims(idx=%zu): rc=%d dimCount=%zu\n", idx, (int)r3,
                           r3 == 0 ? gd2[0].dimCount : (size_t)0);
                }
            }
        }
        aclmdlDestroyDesc(d);
        aclmdlUnload(mid1);
    } else {
        printf("[probe] LoadFromFile FAIL\n");
    }

    FILE *f = fopen(path, "rb");
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *bytes = malloc(sz);
    fread(bytes, 1, sz, f);
    fclose(f);
    uint32_t mid2 = 0;
    if (aclmdlLoadFromMem(bytes, sz, &mid2) == ACL_SUCCESS) {
        aclmdlDesc *d = aclmdlCreateDesc();
        aclmdlGetDesc(d, mid2);
        size_t g = 0;
        aclError rc = aclmdlGetInputDynamicGearCount(d, (size_t)-1, &g);
        printf("[probe] LoadFromMem:   gears=%zu rc=%d n_in=%zu\n", g, (int)rc, aclmdlGetNumInputs(d));
        aclmdlDestroyDesc(d);
        aclmdlUnload(mid2);
    } else {
        printf("[probe] LoadFromMem FAIL\n");
    }
    return 0;
}
