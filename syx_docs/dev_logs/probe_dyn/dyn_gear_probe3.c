// dyn_gear_probe3.c — 动态分档 spike v3：SetInputDynamicDims 145012 触发
// 条件双分离（真 prefix OM 263 输入/14 动态/22 档全维 payload 匹配失败；
// spike v2 小图成功——定位尺度阈值）。
//   NDYN（3/6/14 动态输入，全部 [-1,2048] 直乘链）/ NGEAR（3/22）/
//   WCONST（w/w2 Const 化 → Case 参数 = 额外静态输入，模拟真图 263 输入）
// 图：h = x·wᵀ → m_i = h × t_i（逐表）→ 全链 Mul → 图输出 [-1,2048]
#include <acl/acl_base.h>
#include <acl/acl_mdl.h>
#include <acl/acl_rt.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int (*p_geb_init)(const char *);
static int64_t (*p_geb_model_begin)(const char *);
static int (*p_geb_set_option)(const char *, const char *);
static int (*p_geb_add_data)(const char *, int64_t, const int64_t *, int32_t, const char *);
static int (*p_geb_add_const_raw)(const char *, const int64_t *, int32_t, const char *, const uint8_t *, int64_t);
static int (*p_geb_add_op)(const char *, const char *);
static int (*p_geb_set_input_desc)(const char *, const char *, const int64_t *, int32_t, const char *);
static int (*p_geb_set_output_desc)(const char *, const char *, const int64_t *, int32_t, const char *);
static int (*p_geb_set_attr_bool)(const char *, const char *, int32_t);
static int (*p_geb_link)(const char *, const char *, const char *);
static int (*p_geb_graph_inputs)(const char *const *, int32_t);
static int (*p_geb_graph_outputs)(const char *const *, int32_t);
static int (*p_geb_model_build)(int64_t);
static int (*p_geb_model_save)(int64_t, const char *);
static int (*p_geb_fini)(void);

#define CK(expr, msg)                                                        \
    do {                                                                     \
        int _r = (expr);                                                     \
        if (_r != 0) {                                                       \
            printf("[probe] FAIL %s rc=%d\n", msg, _r);                      \
            return 1;                                                        \
        }                                                                    \
    } while (0)

static uint16_t f32_to_f16(float x) {
    uint32_t b; memcpy(&b, &x, 4);
    uint32_t sign = (b >> 16) & 0x8000u;
    int32_t exp = (int32_t)((b >> 23) & 0xffu) - 127 + 15;
    uint32_t man = b & 0x7fffffu;
    if (exp >= 31) exp = 30;
    if (exp < 0) return (uint16_t)sign;
    uint32_t m = man >> 13, rem = man & 0x1fffu;
    if (rem > 0x1000u || (rem == 0x1000u && (m & 1u))) m++;
    return (uint16_t)(sign | (exp << 10) | (m & 0x3ffu));
}

#define K 2048
#define PMAX 712
#define PMIN 650

static uint16_t *g_w;

// 每输入注册形态：i0 x / i1 zeros / i2.. 表（全 [-1,K]；mul 恒 1）
int main(void) {
    const char *so = "/data/apxinf/ascendc/ge_builder/build/libge_builder.so";
    void *h = dlopen(so, RTLD_NOW);
    if (!h) { printf("dlopen fail\n"); return 1; }
#define RES(s, n) s = dlsym(h, n); if (!s) { printf("dlsym %s fail\n", n); return 1; }
    RES(p_geb_init, "geb_init"); RES(p_geb_model_begin, "geb_model_begin");
    RES(p_geb_set_option, "geb_set_option"); RES(p_geb_add_data, "geb_add_data");
    RES(p_geb_add_const_raw, "geb_add_const_raw"); RES(p_geb_add_op, "geb_add_op");
    RES(p_geb_set_input_desc, "geb_set_input_desc"); RES(p_geb_set_output_desc, "geb_set_output_desc");
    RES(p_geb_set_attr_bool, "geb_set_attr_bool"); RES(p_geb_link, "geb_link");
    RES(p_geb_graph_inputs, "geb_graph_inputs"); RES(p_geb_graph_outputs, "geb_graph_outputs");
    RES(p_geb_model_build, "geb_model_build"); RES(p_geb_model_save, "geb_model_save");
    RES(p_geb_fini, "geb_fini");
    setbuf(stdout, NULL);

    int ndyn = atoi(getenv("NDYN") ? getenv("NDYN") : "3");
    int ngear = atoi(getenv("NGEAR") ? getenv("NGEAR") : "3");
    int wconst = atoi(getenv("WCONST") ? getenv("WCONST") : "0");
    int statdata = atoi(getenv("STATIC_DATA") ? getenv("STATIC_DATA") : "0");
    printf("[v3] NDYN=%d NGEAR=%d WCONST=%d STATIC_DATA=%d\n", ndyn, ngear, wconst, statdata);
    if (ndyn < 2) ndyn = 2;

    if (aclInit(NULL) != ACL_SUCCESS) {}
    CK((int)aclrtSetDevice(0), "setdev");
    aclrtContext cx; CK((int)aclrtCreateContext(&cx, 0), "ctx");

    g_w = malloc(2L * K * K);
    for (long i = 0; i < (long)K * K; i++) g_w[i] = f32_to_f16(0.25f + ((i * 7) % 13 - 6) * 0.004f);
    CK(p_geb_init("Ascend310P3"), "geb_init");

    static char iname[20][8];
    static const char *ins[24];
    int nin = 0;
    for (int i = 0; i < ndyn; i++) {
        snprintf(iname[i], 8, "i%d", i);
        ins[nin++] = iname[i];
    }
    if (!wconst) {
        ins[nin++] = "w";
    }
    if (statdata) ins[nin++] = "sb";  // 静态 [1,K] Data 夹在动态后（bias 形态）
    int64_t g = p_geb_model_begin("v3");
    int64_t dd[2] = {-1, K};
    int64_t wd[2] = {K, K};
    for (int i = 0; i < ndyn; i++) CK(p_geb_add_data(iname[i], i, dd, 2, "fp16"), "add_data");
    if (!wconst) {
        CK(p_geb_add_data("w", 90, wd, 2, "fp16"), "w data");
    } else {
        CK(p_geb_add_const_raw("w", wd, 2, "fp16", (uint8_t *)g_w, 2L * K * K), "w const");
    }
    // 静态 bias 形态：sb [1,K] → Add（broadcast 维度静态——TileD 免）
    if (statdata) {
        CK(p_geb_add_data("sb", 91, (int64_t[]){1, K}, 2, "fp16"), "sb data");
    }
    // h = i0 · wᵀ → m_i = prev × i_i（i≥1 全部动态表汇入）
    CK(p_geb_add_op("h", "MatMulV2"), "op h");
    CK(p_geb_set_input_desc("h", "x1", dd, 2, "fp16"), "h x1");
    CK(p_geb_set_input_desc("h", "x2", wd, 2, "fp16"), "h x2");
    CK(p_geb_set_output_desc("h", "y", dd, 2, "fp16"), "h y");
    CK(p_geb_set_attr_bool("h", "transpose_x1", 0), "h t1");
    CK(p_geb_set_attr_bool("h", "transpose_x2", 1), "h t2");
    CK(p_geb_link("h", "x1", "i0"), "h i0");
    CK(p_geb_link("h", "x2", "w"), "h w");
    char prev[16] = "h";
    for (int i = 1; i < ndyn; i++) {
        char mm[16]; snprintf(mm, 16, "m%d", i);
        CK(p_geb_add_op(mm, "Mul"), "op m");
        CK(p_geb_set_input_desc(mm, "x1", dd, 2, "fp16"), "m x1");
        CK(p_geb_set_input_desc(mm, "x2", dd, 2, "fp16"), "m x2");
        CK(p_geb_set_output_desc(mm, "y", dd, 2, "fp16"), "m y");
        CK(p_geb_link(mm, "x1", prev), "m a");
        CK(p_geb_link(mm, "x2", iname[i]), "m b");
        snprintf(prev, 16, "%s", mm);
    }
    if (statdata) {
        CK(p_geb_add_op("sba", "Add"), "op sba");
        CK(p_geb_set_input_desc("sba", "x1", dd, 2, "fp16"), "sba x1");
        CK(p_geb_set_input_desc("sba", "x2", (int64_t[]){1, K}, 2, "fp16"), "sba x2");
        CK(p_geb_set_output_desc("sba", "y", dd, 2, "fp16"), "sba y");
        CK(p_geb_link("sba", "x1", prev), "sba a");
        CK(p_geb_link("sba", "x2", "sb"), "sba b");
        snprintf(prev, 16, "%s", "sba");
    }
    CK(p_geb_graph_inputs(ins, nin), "gins");
    const char *outs[1] = {prev};
    CK(p_geb_graph_outputs(outs, 1), "gouts");
    // input_shape（w Data 时含静态条目）+ dynamicDims（每档全输入维）
    static char ishp[1024];
    int off = snprintf(ishp, 1024, "i0:-1,%d", K);
    for (int i = 1; i < ndyn; i++) off += snprintf(ishp + off, 32, ";i%d:-1,%d", i, K);
    if (!wconst) off += snprintf(ishp + off, 32, ";w:%d,%d", K, K);
    if (statdata) off += snprintf(ishp + off, 32, ";sb:1,%d", K);
    static char dds[8192];
    off = 0;
    int step = ngear > 1 ? (PMAX - PMIN) / (ngear - 1) : 0;
    for (int gi = 0; gi < ngear; gi++) {
        int p = (gi == ngear - 1) ? PMAX : PMIN + step * gi;
        if (gi > 0) off += snprintf(dds + off, 4, ";");
        for (int i = 0; i < ndyn; i++)
            off += snprintf(dds + off, 16, "%d%s", p, i + 1 < ndyn ? "," : "");
        if (!wconst) off += snprintf(dds + off, 24, ",%d,%d", K, K);
    }
    printf("[v3] input_shape: %s\n", ishp);
    printf("[v3] dynamicDims(head 200): %.200s\n", dds);
    CK(p_geb_set_option("input_shape", ishp), "opt shp");
    CK(p_geb_set_option("ge.dynamicDims", dds), "opt dd");
    CK(p_geb_set_option("input_format", "ND"), "opt fmt");
    CK(p_geb_model_build(g), "build");
    static char omp[128];
    snprintf(omp, 128, "/tmp/v3_%d_%d_%d.om", ndyn, ngear, wconst);
    CK(p_geb_model_save(g, omp), "save");
    printf("[v3] built+saved: %s\n", omp);
    p_geb_fini();

    uint32_t mid = 0;
    if (aclmdlLoadFromFile(omp, &mid) != ACL_SUCCESS) { printf("load fail\n"); return 1; }
    aclmdlDesc *dsc = aclmdlCreateDesc();
    aclmdlGetDesc(dsc, mid);
    size_t gear_cnt = 0;
    aclmdlGetInputDynamicGearCount(dsc, (size_t)-1, &gear_cnt);
    size_t nin2 = aclmdlGetNumInputs(dsc);
    printf("[v3] OM: gears=%zu n_in=%zu\n", gear_cnt, nin2);
    aclmdlIODims gdd[64];
    int gq = aclmdlGetInputDynamicDims(dsc, (size_t)-1, gdd, gear_cnt < 64 ? gear_cnt : 64);
    printf("[v3] gear dims query rc=%d dimCount=%zu\n", gq, gq == 0 ? gdd[0].dimCount : 0);
    if (gq == 0 && gdd[ngear - 1].dimCount > 0) {
        printf("[v3] last gear dims: ");
        for (size_t k = 0; k < gdd[ngear - 1].dimCount; k++)
            printf("%lld,", (long long)gdd[ngear - 1].dims[k]);
        printf("\n");
    }
    // 全维 payload（末档；NDYN 动态输入 + w(若 Data)）
    int64_t vals[256];
    int nv = 0;
    for (int i = 0; i < ndyn; i++) { vals[nv++] = PMAX; vals[nv++] = K; }
    if (!wconst) { vals[nv++] = K; vals[nv++] = K; }
    void **db = calloc(nin2, sizeof(void *));
    size_t *szs = calloc(nin2, sizeof(size_t));
    aclmdlDataset *ds = aclmdlCreateDataset();
    for (size_t i = 0; i < nin2; i++) {
        szs[i] = aclmdlGetInputSizeByIndex(dsc, i);
        aclrtMalloc(&db[i], szs[i], ACL_MEM_MALLOC_HUGE_FIRST);
        aclmdlAddDatasetBuffer(ds, aclCreateDataBuffer(db[i], szs[i]));
    }
    aclmdlDataset *ods = aclmdlCreateDataset();
    size_t osz = aclmdlGetOutputSizeByIndex(dsc, 0);
    void *ob = NULL; aclrtMalloc(&ob, osz, ACL_MEM_MALLOC_HUGE_FIRST);
    aclmdlAddDatasetBuffer(ods, aclCreateDataBuffer(ob, osz));
    aclmdlIODims want; memset(&want, 0, sizeof(want));
    want.dimCount = nv;
    for (int i = 0; i < nv; i++) want.dims[i] = (size_t)vals[i];
    aclError rc = aclmdlSetInputDynamicDims(mid, ds, 0, &want);
    printf("[v3] SetDims(%d vals): rc=%d\n", nv, (int)rc);
    if (rc == ACL_SUCCESS) {
        aclError re = aclmdlExecute(mid, ds, ods);
        aclmdlIODims cur; memset(&cur, 0, sizeof(cur));
        aclmdlGetCurOutputDims(dsc, 0, &cur);
        printf("[v3] execute rc=%d curOut0=%lld (want %d)\nVERDICT: %s\n", (int)re,
               cur.dimCount ? (long long)cur.dims[0] : -1L, PMAX,
               (re == ACL_SUCCESS && cur.dimCount && cur.dims[0] == PMAX) ? "OK" : "RUN_FAIL");
    } else {
        printf("VERDICT: SETDIMS_FAIL\n");
    }
    return 0;
}
