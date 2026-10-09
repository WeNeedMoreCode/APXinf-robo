// dyn_gear_probe.c — 310P 动态分档（dynamic gear / dynamic_dims）可行性 spike（goal ① 调研）
// 生死三题：
//   Q1 ge_builder 路径（aclgrphBuildModel）+ input_shape 带单维 -1 + ge.dynamicDims 能否编译过
//   Q2 OM 尺寸：双档版 vs 静态版（权重在 N 档子图里是否重复——GE 源码判根图单份，实验定案）
//   Q3 aclmdlSetInputDynamicDims + execute 两档各自数值 vs CPU f64 参考（采样行）+ 粗计时
// 图形态镜像生产：MatMulV2 transpose_x2=true，权重 [n,k] Const 32MB（K=2048,N=8192），
// x 动态维 = P（= 512+L，档位 650/712 = L138/L200）。
// 编译（apxinf_rust 容器）：
//   gcc -O2 -o /tmp/dyn_gear_probe /data/apxinf/probe_dyn/dyn_gear_probe.c \
//     -I/usr/local/Ascend/ascend-toolkit/latest/include \
//     -L/usr/local/Ascend/ascend-toolkit/latest/lib64 -lascendcl -ldl -lm
// 运行：LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/lib64 \
//       ASCEND_RT_VISIBLE_DEVICES=<空芯> /tmp/dyn_gear_probe
#include <acl/acl_base.h>
#include <acl/acl_mdl.h>
#include <acl/acl_rt.h>
#include <dlfcn.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

// ---- ge_builder FFI（dlopen）----
static int (*p_geb_init)(const char *);
static int (*p_geb_fini)(void);
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

#define CK(expr, msg)                                   \
    do {                                                \
        int _r = (expr);                                \
        if (_r != 0) {                                  \
            printf("[probe] FAIL %s rc=%d\n", msg, _r); \
            return 1;                                   \
        }                                               \
        printf("[probe] ok %s\n", msg);                 \
    } while (0)

// ---- fp16 转换（round-to-nearest-even，经典位操作；probe 值域小够用）----
static uint16_t f32_to_f16(float x) {
    uint32_t b;
    memcpy(&b, &x, 4);
    uint32_t sign = (b >> 16) & 0x8000u;
    int32_t exp = (int32_t)((b >> 23) & 0xffu) - 127 + 15;
    uint32_t man = b & 0x7fffffu;
    if (exp >= 31) exp = 30;
    if (exp < 0) return (uint16_t)sign;
    uint32_t m = man >> 13;
    uint32_t rem = man & 0x1fffu;
    if (rem > 0x1000u || (rem == 0x1000u && (m & 1u))) m++;
    return (uint16_t)(sign | ((uint32_t)exp << 10) | (m & 0x3ffu));
}
static float f16_to_f32(uint16_t h) {
    uint32_t sign = (uint32_t)(h & 0x8000u) << 16;
    int32_t exp = (int32_t)((h >> 10) & 0x1fu) - 15 + 127;
    uint32_t man = (uint32_t)(h & 0x3ffu) << 13;
    uint32_t b = sign | ((uint32_t)exp << 23) | man;
    float f;
    memcpy(&f, &b, 4);
    return f;
}

#define KD 2048
#define ND 8192
#define NGEAR 2
static const int64_t GEARS[NGEAR] = {650, 712};

static uint16_t *g_w;  // [N,K] fp16（transpose_x2 布局，镜像生产）

static uint16_t *make_x(int64_t p) {  // [p,K] 确定性 + 均值偏移（输出 ~256 量级，避免对消小分母）
    uint16_t *x = malloc(sizeof(uint16_t) * (size_t)(p * KD));
    for (int64_t i = 0; i < p * KD; i++) {
        int64_t r = i / KD, c = i % KD;
        float v = 0.5f + (float)(((r * 7 + c * 13) % 17) - 8) * 0.01f;
        x[i] = f32_to_f16(v);
    }
    return x;
}

// 采样行参考：rows[] 共 nr 行，y_ref[row][n] = Σ_k x[row][k]*w[n][k]（f64）
static void ref_rows(const uint16_t *x, int64_t p, const int64_t *rows, int nr, double *yref) {
    for (int r = 0; r < nr; r++) {
        int64_t row = rows[r];
        (void)p;
        for (int64_t n = 0; n < ND; n++) {
            double s = 0.0;
            const uint16_t *xr = x + row * KD;
            const uint16_t *wr = g_w + n * KD;
            for (int64_t k = 0; k < KD; k++) s += (double)f16_to_f32(xr[k]) * (double)f16_to_f32(wr[k]);
            yref[(int64_t)r * ND + n] = s;
        }
    }
}

static long fsize(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 ? (long)st.st_size : -1L;
}

static int build_graph(int dyn, const char *save_path) {
    int64_t g = p_geb_model_begin(dyn ? "dyn_gear" : "static_ctrl");
    int64_t xd[2] = {dyn ? -1 : GEARS[0], KD};
    int64_t wd[2] = {ND, KD};
    int64_t od[2] = {dyn ? -1 : GEARS[0], ND};
    CK(p_geb_add_data("x", 0, xd, 2, "fp16"), "add_data x");
    CK(p_geb_add_const_raw("w", wd, 2, "fp16", (const uint8_t *)g_w, (int64_t)ND * KD * 2), "add_const w");
    CK(p_geb_add_op("mm", "MatMulV2"), "add_op mm");
    CK(p_geb_set_input_desc("mm", "x1", xd, 2, "fp16"), "mm x1 desc");
    CK(p_geb_set_input_desc("mm", "x2", wd, 2, "fp16"), "mm x2 desc");
    CK(p_geb_set_output_desc("mm", "y", od, 2, "fp16"), "mm y desc");
    CK(p_geb_set_attr_bool("mm", "transpose_x1", 0), "transpose_x1=false");
    CK(p_geb_set_attr_bool("mm", "transpose_x2", 1), "transpose_x2=true");
    CK(p_geb_link("mm", "x1", "x"), "link x->mm.x1");
    CK(p_geb_link("mm", "x2", "w"), "link w->mm.x2");
    const char *ins[1] = {"x"};
    CK(p_geb_graph_inputs(ins, 1), "graph inputs");
    const char *outs[1] = {"mm"};
    CK(p_geb_graph_outputs(outs, 1), "graph outputs");
    if (dyn) {
        CK(p_geb_set_option("input_shape", "x:-1,2048"), "opt input_shape dyn");
        CK(p_geb_set_option("ge.dynamicDims", "650;712"), "opt ge.dynamicDims");
    } else {
        CK(p_geb_set_option("input_shape", "x:650,2048"), "opt input_shape static");
    }
    CK(p_geb_set_option("input_format", "ND"), "opt input_format");
    CK(p_geb_model_build(g), "model build");
    CK(p_geb_model_save(g, save_path), "model save");
    return 0;
}

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

static int run_phase(const char *om_path) {
    uint32_t mid = 0;
    if (aclmdlLoadFromFile(om_path, &mid) != ACL_SUCCESS) {
        printf("[run] load FAIL %s\n", om_path);
        return 1;
    }
    printf("[run] loaded %s (model_id=%u)\n", om_path, mid);
    aclmdlDesc *desc = aclmdlCreateDesc();
    if (aclmdlGetDesc(desc, mid) != ACL_SUCCESS) {
        printf("[run] get desc FAIL\n");
        return 1;
    }
    size_t nin = aclmdlGetNumInputs(desc), nout = aclmdlGetNumOutputs(desc);
    size_t in_sz = aclmdlGetInputSizeByIndex(desc, 0), out_sz = aclmdlGetOutputSizeByIndex(desc, 0);
    aclmdlIODims idims;
    memset(&idims, 0, sizeof(idims));
    aclmdlGetInputDims(desc, 0, &idims);
    printf("[run] n_in=%zu n_out=%zu in_size=%zu out_size=%zu in_dims0=%lld\n", nin, nout, in_sz, out_sz,
           (long long)idims.dims[0]);
    for (size_t i = 1; i < nin; i++) {
        aclmdlIODims d2;
        memset(&d2, 0, sizeof(d2));
        aclmdlGetInputDims(desc, i, &d2);
        printf("[run] extra in[%zu]: size=%zu dimCount=%zu dims0=%lld\n", i, aclmdlGetInputSizeByIndex(desc, i),
               d2.dimCount, (long long)d2.dims[0]);
    }
    size_t gear_cnt = 0;
    aclError ge_rc = aclmdlGetInputDynamicGearCount(desc, (size_t)-1, &gear_cnt);
    printf("[run] gearCount rc=%d count=%zu\n", (int)ge_rc, gear_cnt);
    aclmdlIODims gd[8];
    if (gear_cnt > 0 && gear_cnt <= 8) {
        aclmdlGetInputDynamicDims(desc, (size_t)-1, gd, gear_cnt);
        for (size_t i = 0; i < gear_cnt; i++) {
            printf("[run] gear[%zu]: dimCount=%zu dims=%lld\n", i, gd[i].dimCount, (long long)gd[i].dims[0]);
        }
    }
    void *dev_in = NULL, *dev_out = NULL;
    aclrtMalloc(&dev_in, in_sz, ACL_MEM_MALLOC_HUGE_FIRST);
    aclrtMalloc(&dev_out, out_sz, ACL_MEM_MALLOC_HUGE_FIRST);
    aclDataBuffer *ib = aclCreateDataBuffer(dev_in, in_sz);
    aclDataBuffer *ob = aclCreateDataBuffer(dev_out, out_sz);
    aclmdlDataset *ids = aclmdlCreateDataset();
    aclmdlAddDatasetBuffer(ids, ib);
    // 动态分档 OM 会多出 gear-info 输入（mbatch_shape_data）：dataset 必须覆盖全部输入，
    // aclmdlSetInputDynamicDims 由 GE 侧往对应 buffer 写档位值
    void **extra = calloc(nin, sizeof(void *));
    for (size_t i = 1; i < nin; i++) {
        size_t sz = aclmdlGetInputSizeByIndex(desc, i);
        aclrtMalloc(&extra[i], sz, ACL_MEM_MALLOC_HUGE_FIRST);
        aclDataBuffer *eb = aclCreateDataBuffer(extra[i], sz);
        aclmdlAddDatasetBuffer(ids, eb);
    }
    aclmdlDataset *ods = aclmdlCreateDataset();
    aclmdlAddDatasetBuffer(ods, ob);
    aclrtStream stream;
    aclrtCreateStream(&stream);

    int all_ok = 1;
    for (int gi = 0; gi < NGEAR; gi++) {
        int64_t p = GEARS[gi];
        uint16_t *x = make_x(p);
        aclrtMemcpy(dev_in, in_sz, x, (size_t)p * KD * 2, ACL_MEMCPY_HOST_TO_DEVICE);
        aclmdlIODims want;
        memset(&want, 0, sizeof(want));
        want.dimCount = 2;
        want.dims[0] = p;
        want.dims[1] = KD;
        aclError rc = aclmdlSetInputDynamicDims(mid, ids, 0, &want);
        printf("[run] gear %lld (p=%lld): SetInputDynamicDims rc=%d\n", (long long)gi, (long long)p, (int)rc);
        if (rc != ACL_SUCCESS) {
            all_ok = 0;
            free(x);
            continue;
        }
        rc = aclmdlExecute(mid, ids, ods);
        if (rc != ACL_SUCCESS) {
            printf("[run] gear %lld execute FAIL rc=%d\n", (long long)gi, (int)rc);
            all_ok = 0;
            free(x);
            continue;
        }
        aclrtSynchronizeStream(stream);
        uint16_t *y = malloc(out_sz);
        aclrtMemcpy(y, out_sz, dev_out, out_sz, ACL_MEMCPY_DEVICE_TO_HOST);
        // 采样行数值对拍：首 4 行 + 尾 4 行
        int64_t rows[8];
        int nr = 0;
        for (int i = 0; i < 4; i++) rows[nr++] = i;
        for (int i = 0; i < 4; i++) rows[nr++] = p - 4 + i;
        double *yref = malloc(sizeof(double) * nr * ND);
        ref_rows(x, p, rows, nr, yref);
        double max_abs = 0.0, max_ref = 1e-9;
        for (int r = 0; r < nr; r++) {
            for (int64_t n = 0; n < ND; n++) {
                double got = (double)f16_to_f32(y[(int64_t)rows[r] * ND + n]);
                double ref = yref[(int64_t)r * ND + n];
                double d = fabs(got - ref);
                if (d > max_abs) max_abs = d;
                if (fabs(ref) > max_ref) max_ref = fabs(ref);
            }
        }
        printf("[run] gear %lld NUMERIC: max_abs=%.5f max_ref=%.5f rel=%.4f%% -> %s\n", (long long)gi, max_abs,
               max_ref, 100.0 * max_abs / max_ref, (max_abs / max_ref < 0.03) ? "PASS" : "FAIL");
        if (max_abs / max_ref >= 0.03) all_ok = 0;
        aclmdlIODims cur;
        memset(&cur, 0, sizeof(cur));
        aclError orc = aclmdlGetCurOutputDims(desc, 0, &cur);
        printf("[run] gear %lld GetCurOutputDims rc=%d dimCount=%zu dims0=%lld\n", (long long)gi, (int)orc,
               cur.dimCount, cur.dimCount > 0 ? (long long)cur.dims[0] : -1LL);
        // 粗计时 ×20
        double t0 = now_ms();
        for (int it = 0; it < 20; it++) {
            aclmdlSetInputDynamicDims(mid, ids, 0, &want);
            aclmdlExecute(mid, ids, ods);
            aclrtSynchronizeStream(stream);
        }
        printf("[run] gear %lld timing: %.3f ms/iter (含 SetDims+sync)\n", (long long)gi,
               (now_ms() - t0) / 20.0);
        free(x);
        free(y);
        free(yref);
    }
    printf("[run] VERDICT: %s\n", all_ok ? "RUN_OK" : "RUN_FAIL");
    // 静态对照计时（同 shape 单档 OM，无 SetDims 开销）
    {
        uint32_t smid = 0;
        if (aclmdlLoadFromFile("/data/apxinf/probe_dyn/static650.om", &smid) == ACL_SUCCESS) {
            aclmdlDesc *sd = aclmdlCreateDesc();
            aclmdlGetDesc(sd, smid);
            size_t si = aclmdlGetInputSizeByIndex(sd, 0), so = aclmdlGetOutputSizeByIndex(sd, 0);
            void *di = NULL, *doo = NULL;
            aclrtMalloc(&di, si, ACL_MEM_MALLOC_HUGE_FIRST);
            aclrtMalloc(&doo, so, ACL_MEM_MALLOC_HUGE_FIRST);
            aclDataBuffer *sib = aclCreateDataBuffer(di, si);
            aclDataBuffer *sob = aclCreateDataBuffer(doo, so);
            aclmdlDataset *sds = aclmdlCreateDataset();
            aclmdlAddDatasetBuffer(sds, sib);
            aclmdlDataset *sos = aclmdlCreateDataset();
            aclmdlAddDatasetBuffer(sos, sob);
            uint16_t *x = make_x(GEARS[0]);
            aclrtMemcpy(di, si, x, (size_t)GEARS[0] * KD * 2, ACL_MEMCPY_HOST_TO_DEVICE);
            double t0 = now_ms();
            for (int it = 0; it < 20; it++) {
                aclmdlExecute(smid, sds, sos);
                aclrtSynchronizeStream(stream);
            }
            printf("[run] static650 timing: %.3f ms/iter（对照：dyn gear0 含 SetDims）\n", (now_ms() - t0) / 20.0);
        }
    }
    return all_ok ? 0 : 1;
}

int main(void) {
    const char *so = "/data/apxinf/ascendc/ge_builder/build/libge_builder.so";
    void *h = dlopen(so, RTLD_NOW);
    if (!h) {
        printf("[probe] dlopen fail: %s\n", dlerror());
        return 1;
    }
#define RES(sym, name)                       \
    sym = dlsym(h, name);                    \
    if (!sym) {                              \
        printf("[probe] dlsym %s fail\n", name); \
        return 1;                            \
    }
    RES(p_geb_init, "geb_init");
    RES(p_geb_fini, "geb_fini");
    RES(p_geb_model_begin, "geb_model_begin");
    RES(p_geb_set_option, "geb_set_option");
    RES(p_geb_add_data, "geb_add_data");
    RES(p_geb_add_const_raw, "geb_add_const_raw");
    RES(p_geb_add_op, "geb_add_op");
    RES(p_geb_set_input_desc, "geb_set_input_desc");
    RES(p_geb_set_output_desc, "geb_set_output_desc");
    RES(p_geb_set_attr_bool, "geb_set_attr_bool");
    RES(p_geb_link, "geb_link");
    RES(p_geb_graph_inputs, "geb_graph_inputs");
    RES(p_geb_graph_outputs, "geb_graph_outputs");
    RES(p_geb_model_build, "geb_model_build");
    RES(p_geb_model_save, "geb_model_save");
    printf("[probe] ge_builder.so loaded\n");

    // ACL runtime 先行（build 内部 aclmdlLoadFromMem 需设备）
    if (aclInit(NULL) != ACL_SUCCESS) printf("[probe] aclInit non-zero（可能已初始化，继续）\n");
    CK((int)aclrtSetDevice(0), "aclrtSetDevice(0)");
    aclrtContext ctx;
    CK((int)aclrtCreateContext(&ctx, 0), "create context");

    g_w = malloc(sizeof(uint16_t) * (size_t)ND * KD);
    for (int64_t i = 0; i < ND * KD; i++) {
        int64_t n = i / KD, k = i % KD;
        float v = 0.25f + (float)(((n * 11 + k * 3) % 19) - 9) * 0.005f;
        g_w[i] = f32_to_f16(v);
    }

    CK(p_geb_init("Ascend310P3"), "geb_init");

    const char *dyn_path = "/data/apxinf/probe_dyn/gear2.om";
    const char *sta_path = "/data/apxinf/probe_dyn/static650.om";
    if (build_graph(0, sta_path) != 0) return 1;
    if (build_graph(1, dyn_path) != 0) return 1;
    long sz_sta = fsize(sta_path), sz_dyn = fsize(dyn_path);
    printf("[probe] OM SIZE: static650=%ld bytes, gear2=%ld bytes, delta=%ld (weight Const=%d bytes)\n", sz_sta,
           sz_dyn, sz_dyn - sz_sta, ND * KD * 2);
    printf("[probe] Q2 verdict: %s\n",
           (sz_dyn - sz_sta < ND * KD * 2) ? "WEIGHT_NOT_DUPLICATED" : "WEIGHT_DUPLICATED");
    p_geb_fini();  // 释放 geb 侧已加载模型，run 阶段走纯 ACL 文件加载

    return run_phase(dyn_path);
}
