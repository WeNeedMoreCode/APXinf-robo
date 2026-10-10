// dyn_gear_probe2.c — 动态分档 spike v2：生产图关键模式取证（goal ① 施工前置）
// v1 已证：编译/权重零重复/档位分发/数值/零税。v2 补真图才有的四类模式：
//   P1 Reshape shape Const 含 -1（rank 桥 shp_q3/shp_kall 等的生产等价物——
//      Const 全档共享（multibatch 根图单份），内容只能 gear 不变；-1 若被
//      分支推理支持则单图通吃所有档（GE 符号推理层有此语义，经典 FE 待证）
//   P2 GatherV2D 索引 = Data（rope swap：Const 化则长度钉死一档；Data[-1]
//      逐档特化 desc、内容 = r^1 前缀截断表）
//   P3 多动态输入（x/idx/cos 三路）单次 aclmdlSetInputDynamicDims(index=0)
//   P4 TileD 静态 multiples + BatchMatMulV2/SoftmaxV2 动态方阵（[-1,-1]）
// 图：x[-1,2048]→mm→h[-1,2048]→Reshape[-1,1024]→Gather(r^1)→Mul(cos[-1,1024])
//     →Reshape[-1,2048](bk)→{Reshape[1,-1,2048]→TileD[2,-1,2048]→BMM→SoftmaxV2}
//                                     └→mm2→out[-1,2048]
// 输出 = [out, sm, hf]，CPU f64 参考（hf/out 采样行 + sm 行和≈1）
// 档：650/660/712（p=512+L 谱系），dynamicDims="650,1300,1300;660,1320,1320;712,1424,1424"
// 编译/运行同 v1 配方（见文件头注记）。
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

static int (*p_geb_init)(const char *);
static int64_t (*p_geb_model_begin)(const char *);
static int (*p_geb_set_option)(const char *, const char *);
static int (*p_geb_add_data)(const char *, int64_t, const int64_t *, int32_t, const char *);
static int (*p_geb_add_const_raw)(const char *, const int64_t *, int32_t, const char *, const uint8_t *, int64_t);
static int (*p_geb_add_const_i32)(const char *, const int32_t *, int32_t);
static int (*p_geb_add_op)(const char *, const char *);
static int (*p_geb_set_input_desc)(const char *, const char *, const int64_t *, int32_t, const char *);
static int (*p_geb_set_output_desc)(const char *, const char *, const int64_t *, int32_t, const char *);
static int (*p_geb_set_attr_bool)(const char *, const char *, int32_t);
static int (*p_geb_set_attr_int)(const char *, const char *, int64_t);
static int (*p_geb_set_attr_int_list)(const char *, const char *, const int64_t *, int32_t);
static int (*p_geb_link)(const char *, const char *, const char *);
static int (*p_geb_graph_inputs)(const char *const *, int32_t);
static int (*p_geb_graph_outputs)(const char *const *, int32_t);
static int (*p_geb_model_build)(int64_t);
static int (*p_geb_model_save)(int64_t, const char *);
static int (*p_geb_fini)(void);

#define CK(expr, msg)                                   \
    do {                                                \
        int _r = (expr);                                \
        if (_r != 0) {                                  \
            printf("[probe] FAIL %s rc=%d\n", msg, _r); \
            return 1;                                   \
        }                                               \
        printf("[probe] ok %s\n", msg);                 \
    } while (0)

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

#define K 2048
#define H 1024  // reshape 后半宽
#define P2 2    // tile 头数
#define NGEAR 3
static const int64_t GEARS[NGEAR] = {650, 660, 712};
#define PMAX (GEARS[NGEAR - 1])

static uint16_t *g_w, *g_w2;          // [K,K] fp16（transpose_x2 布局）
static int32_t *g_idx;                // [PMAX*2] r^1 前缀可截断
static uint16_t *g_cos;               // [PMAX*2, H] 行内容只依赖 (i,j)

static void make_static(void) {
    g_w = malloc(sizeof(uint16_t) * (size_t)K * K);
    g_w2 = malloc(sizeof(uint16_t) * (size_t)K * K);
    for (int64_t i = 0; i < K * K; i++) {
        int64_t n = i / K, k = i % K;
        g_w[i] = f32_to_f16(0.25f + (float)(((n * 11 + k * 3) % 19) - 9) * 0.005f);
        g_w2[i] = f32_to_f16(0.2f + (float)(((n * 7 + k * 5) % 23) - 11) * 0.004f);
    }
    g_idx = malloc(sizeof(int32_t) * (size_t)(PMAX * 2));
    for (int64_t r = 0; r < PMAX * 2; r++) g_idx[r] = (int32_t)(r ^ 1);
    g_cos = malloc(sizeof(uint16_t) * (size_t)(PMAX * 2) * H);
    for (int64_t i = 0; i < PMAX * 2; i++)
        for (int64_t j = 0; j < H; j++)
            g_cos[i * H + j] = f32_to_f16(0.5f + (float)(((i * 13 + j * 7) % 17) - 8) * 0.01f);
}

static uint16_t *make_x(int64_t p) {
    uint16_t *x = malloc(sizeof(uint16_t) * (size_t)p * K);
    for (int64_t i = 0; i < p * K; i++) {
        int64_t r = i / K, c = i % K;
        float v = 0.5f + (float)(((r * 7 + c * 13) % 17) - 8) * 0.01f;
        x[i] = f32_to_f16(v);
    }
    return x;
}

// CPU f64 参考（f16 入 f64 算）：out = reshape(gather(reshape(x·wᵀ))·cos)·w2ᵀ
// 返回采样行 out 参考；nr 行（rows 给出 out 的行号）
static double *ref_out_rows(const uint16_t *x, int64_t p, const int64_t *rows, int nr) {
    // h = x·wᵀ（只算需要的行：reshape/gather/mul 全是行内操作，
    // out 行 r 依赖 bk 行 r ← m 行 r ← sw 行 r ← hf 行 r（r<p*2 时）……
    // 但 hf 行 2r/2r+1 都来自 h 行 r；sw 行 i = hf 行 (i^1)；m/sw 同行；
    // bk 行 r 的两半 = m 行 2r / 2r+1 —— bk 行 r 依赖 h 行 r 全列
    double *out = malloc(sizeof(double) * nr * K);
    for (int q = 0; q < nr; q++) {
        int64_t r = rows[q];
        // h[r][:] → 两段（hf 行 2r / 2r+1）→ swap（行 2r↔2r+1）→ ×cos → bk[r]
        double bk[K];
        for (int half = 0; half < 2; half++) {
            int64_t hf_row = r * 2 + half;        // 目标行号（bk 的 half 段 ← m 行 hf_row）
            int64_t src_seg = (hf_row ^ 1) % 2;   // gather swap：m 行内容来自 h 行 r 的对侧段
            for (int64_t j = 0; j < H; j++) {
                double hv = 0.0;
                const uint16_t *xr = x + r * K;
                const uint16_t *wr = g_w + (src_seg * H + j) * K;
                for (int64_t k = 0; k < K; k++) hv += (double)f16_to_f32(xr[k]) * (double)f16_to_f32(wr[k]);
                bk[half * H + j] = hv * (double)f16_to_f32(g_cos[hf_row * H + j]);  // cos 行=输出行号
            }
        }
        // out[r][:] = bk · w2ᵀ
        for (int64_t n = 0; n < K; n++) {
            double s = 0.0;
            const uint16_t *wr = g_w2 + n * K;
            for (int64_t k = 0; k < K; k++) s += bk[k] * (double)f16_to_f32(wr[k]);
            out[(int64_t)q * K + n] = s;
        }
    }
    return out;
}
// hf 采样行参考（独立验 reshape 链）：hf[i][:] = h[i/H][i%H ...]（行主序展开）
static double *ref_hf_rows(const uint16_t *x, int64_t p, const int64_t *rows, int nr) {
    double *out = malloc(sizeof(double) * nr * H);
    for (int q = 0; q < nr; q++) {
        int64_t i = rows[q];
        int64_t hr = i / H, c0 = (i % H);  // i % H*2? 行主序：flat = i*H；h flat 行主 = hr' = i/H, 列段 = (i%H)... 直接按 flat 索引
        for (int64_t j = 0; j < H; j++) {
            int64_t flat = i * H + j;
            int64_t hrow = flat / K, hcol = flat % K;
            double s = 0.0;
            const uint16_t *xr = x + hrow * K;
            const uint16_t *wr = g_w + hcol * K;
            for (int64_t k = 0; k < K; k++) s += (double)f16_to_f32(xr[k]) * (double)f16_to_f32(wr[k]);
            out[(int64_t)q * H + j] = s;
        }
        (void)p; (void)hr; (void)c0;
    }
    return out;
}

static int build_dyn(const char *save_path) {
    int64_t g = p_geb_model_begin("dyn_gear2");
    int64_t xd[2] = {-1, K}, wd[2] = {K, K}, hfd[2] = {-1, H}, idm[1] = {-1};
    int64_t r3d[3] = {1, -1, K}, t3d[3] = {P2, -1, K}, sqd[3] = {P2, -1, -1};
    int64_t l64[1] = {-1};
    CK(p_geb_add_data("x", 0, xd, 2, "fp16"), "data x");
    CK(p_geb_add_data("idx", 1, idm, 1, "int32"), "data idx");
    CK(p_geb_add_data("cos", 2, hfd, 2, "fp16"), "data cos");
    CK(p_geb_add_const_raw("w", wd, 2, "fp16", (const uint8_t *)g_w, (int64_t)K * K * 2), "const w");
    CK(p_geb_add_const_raw("w2", wd, 2, "fp16", (const uint8_t *)g_w2, (int64_t)K * K * 2), "const w2");
    // P1：Reshape shape Const 含 -1（gear 不变内容）
    int32_t shp_flat[2] = {-1, H}, shp_back[2] = {-1, K}, shp3[3] = {1, -1, K};
    CK(p_geb_add_const_i32("shp_flat", shp_flat, 2), "const shp_flat");
    CK(p_geb_add_const_i32("shp_back", shp_back, 2), "const shp_back");
    CK(p_geb_add_const_i32("shp3", shp3, 3), "const shp3");
    // h = x·wᵀ
    CK(p_geb_add_op("h", "MatMulV2"), "op h");
    CK(p_geb_set_input_desc("h", "x1", xd, 2, "fp16"), "h x1");
    CK(p_geb_set_input_desc("h", "x2", wd, 2, "fp16"), "h x2");
    CK(p_geb_set_output_desc("h", "y", xd, 2, "fp16"), "h y");
    CK(p_geb_set_attr_bool("h", "transpose_x1", 0), "h t1");
    CK(p_geb_set_attr_bool("h", "transpose_x2", 1), "h t2");
    CK(p_geb_link("h", "x1", "x"), "h x");
    CK(p_geb_link("h", "x2", "w"), "h w");
    // hf = Reshape(h, [-1, H])
    CK(p_geb_add_op("hf", "Reshape"), "op hf");
    CK(p_geb_set_input_desc("hf", "x", xd, 2, "fp16"), "hf x");
    CK(p_geb_set_input_desc("hf", "shape", &(int64_t){2}, 1, "int32"), "hf shape desc");
    CK(p_geb_set_output_desc("hf", "y", hfd, 2, "fp16"), "hf y");
    CK(p_geb_link("hf", "x", "h"), "hf x");
    CK(p_geb_link("hf", "shape", "shp_flat"), "hf shp");
    // P2：sw = GatherV2D(hf, idx(Data), axis=0)
    CK(p_geb_add_op("sw", "GatherV2D"), "op sw");
    CK(p_geb_set_input_desc("sw", "x", hfd, 2, "fp16"), "sw x");
    CK(p_geb_set_input_desc("sw", "indices", idm, 1, "int32"), "sw idx");
    CK(p_geb_set_output_desc("sw", "y", hfd, 2, "fp16"), "sw y");
    CK(p_geb_set_attr_int("sw", "axis", 0), "sw axis");
    CK(p_geb_link("sw", "x", "hf"), "sw x");
    CK(p_geb_link("sw", "indices", "idx"), "sw idx");
    // m = sw × cos
    CK(p_geb_add_op("m", "Mul"), "op m");
    CK(p_geb_set_input_desc("m", "x1", hfd, 2, "fp16"), "m x1");
    CK(p_geb_set_input_desc("m", "x2", hfd, 2, "fp16"), "m x2");
    CK(p_geb_set_output_desc("m", "y", hfd, 2, "fp16"), "m y");
    CK(p_geb_link("m", "x1", "sw"), "m a");
    CK(p_geb_link("m", "x2", "cos"), "m b");
    // bk = Reshape(m, [-1, K])
    CK(p_geb_add_op("bk", "Reshape"), "op bk");
    CK(p_geb_set_input_desc("bk", "x", hfd, 2, "fp16"), "bk x");
    CK(p_geb_set_input_desc("bk", "shape", &(int64_t){2}, 1, "int32"), "bk shape desc");
    CK(p_geb_set_output_desc("bk", "y", xd, 2, "fp16"), "bk y");
    CK(p_geb_link("bk", "x", "m"), "bk x");
    CK(p_geb_link("bk", "shape", "shp_back"), "bk shp");
    // r3 = Reshape(bk, [1,-1,K]) → t = TileD(r3, [P2,1,1])
    CK(p_geb_add_op("r3", "Reshape"), "op r3");
    CK(p_geb_set_input_desc("r3", "x", xd, 2, "fp16"), "r3 x");
    CK(p_geb_set_input_desc("r3", "shape", &(int64_t){3}, 1, "int32"), "r3 shape desc");
    CK(p_geb_set_output_desc("r3", "y", r3d, 3, "fp16"), "r3 y");
    CK(p_geb_link("r3", "x", "bk"), "r3 x");
    CK(p_geb_link("r3", "shape", "shp3"), "r3 shp");
    int64_t mult[3] = {P2, 1, 1};
    CK(p_geb_add_op("t", "TileD"), "op t");
    CK(p_geb_set_input_desc("t", "x", r3d, 3, "fp16"), "t x");
    CK(p_geb_set_output_desc("t", "y", t3d, 3, "fp16"), "t y");
    CK(p_geb_set_attr_int_list("t", "multiples", mult, 3), "t mult");
    CK(p_geb_link("t", "x", "r3"), "t x");
    // P4：sc = BMM(t·tᵀ) → sm = SoftmaxV2
    CK(p_geb_add_op("sc", "BatchMatMulV2"), "op sc");
    CK(p_geb_set_input_desc("sc", "x1", t3d, 3, "fp16"), "sc x1");
    CK(p_geb_set_input_desc("sc", "x2", t3d, 3, "fp16"), "sc x2");
    CK(p_geb_set_output_desc("sc", "y", sqd, 3, "fp16"), "sc y");
    CK(p_geb_set_attr_bool("sc", "adj_x1", 0), "sc a1");
    CK(p_geb_set_attr_bool("sc", "adj_x2", 1), "sc a2");
    CK(p_geb_link("sc", "x1", "t"), "sc b");
    CK(p_geb_link("sc", "x2", "t"), "sc c");
    CK(p_geb_add_op("sm", "SoftmaxV2"), "op sm");
    CK(p_geb_set_input_desc("sm", "x", sqd, 3, "fp16"), "sm x");
    CK(p_geb_set_output_desc("sm", "y", sqd, 3, "fp16"), "sm y");
    CK(p_geb_set_attr_int_list("sm", "axes", l64, 1), "sm axes");
    CK(p_geb_set_attr_bool("sm", "half_to_float", 0), "sm h2f");
    CK(p_geb_link("sm", "x", "sc"), "sm x");
    // out = bk·w2ᵀ
    CK(p_geb_add_op("out", "MatMulV2"), "op out");
    CK(p_geb_set_input_desc("out", "x1", xd, 2, "fp16"), "out x1");
    CK(p_geb_set_input_desc("out", "x2", wd, 2, "fp16"), "out x2");
    CK(p_geb_set_output_desc("out", "y", xd, 2, "fp16"), "out y");
    CK(p_geb_set_attr_bool("out", "transpose_x1", 0), "out t1");
    CK(p_geb_set_attr_bool("out", "transpose_x2", 1), "out t2");
    CK(p_geb_link("out", "x1", "bk"), "out b");
    CK(p_geb_link("out", "x2", "w2"), "out w");
    const char *ins[3] = {"x", "idx", "cos"};
    CK(p_geb_graph_inputs(ins, 3), "graph inputs");
    const char *outs[3] = {"out", "sm", "hf"};
    CK(p_geb_graph_outputs(outs, 3), "graph outputs");
    CK(p_geb_set_option("input_shape", "x:-1,2048;idx:-1;cos:-1,1024"), "opt input_shape");
    CK(p_geb_set_option("ge.dynamicDims", "650,1300,1300;660,1320,1320;712,1424,1424"), "opt dynamicDims");
    CK(p_geb_set_option("input_format", "ND"), "opt input_format");
    CK(p_geb_model_build(g), "model build");
    CK(p_geb_model_save(g, save_path), "model save");
    return 0;
}

static long fsize(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 ? (long)st.st_size : -1L;
}

static int run_phase(const char *om_path) {
    uint32_t mid = 0;
    if (aclmdlLoadFromFile(om_path, &mid) != ACL_SUCCESS) {
        printf("[run] load FAIL\n");
        return 1;
    }
    aclmdlDesc *desc = aclmdlCreateDesc();
    aclmdlGetDesc(desc, mid);
    size_t nin = aclmdlGetNumInputs(desc);
    printf("[run] n_in=%zu（3 真输入 + gear-info）\n", nin);
    size_t gear_cnt = 0;
    aclmdlGetInputDynamicGearCount(desc, (size_t)-1, &gear_cnt);
    printf("[run] gearCount=%zu\n", gear_cnt);
    if (gear_cnt != NGEAR) {
        printf("[run] VERDICT: GEAR_COUNT_MISMATCH\n");
        return 1;
    }
    aclmdlIODims gd[NGEAR];
    aclmdlGetInputDynamicDims(desc, (size_t)-1, gd, NGEAR);
    for (size_t i = 0; i < NGEAR; i++)
        printf("[run] gear[%zu]: dimCount=%zu dims=%lld,%lld,%lld\n", i, gd[i].dimCount,
               (long long)gd[i].dims[0], (long long)gd[i].dims[1],
               gd[i].dimCount > 2 ? (long long)gd[i].dims[2] : -1LL);
    // buffers：按模型报告 size（= max 档）分配，全部输入入 dataset
    void **dev = calloc(nin, sizeof(void *));
    size_t *szs = calloc(nin, sizeof(size_t));
    aclmdlDataset *ids = aclmdlCreateDataset();
    for (size_t i = 0; i < nin; i++) {
        szs[i] = aclmdlGetInputSizeByIndex(desc, i);
        aclrtMalloc(&dev[i], szs[i], ACL_MEM_MALLOC_HUGE_FIRST);
        aclmdlAddDatasetBuffer(ids, aclCreateDataBuffer(dev[i], szs[i]));
    }
    size_t no = aclmdlGetNumOutputs(desc);
    void **odev = calloc(no, sizeof(void *));
    size_t *osz = calloc(no, sizeof(size_t));
    aclmdlDataset *ods = aclmdlCreateDataset();
    for (size_t i = 0; i < no; i++) {
        osz[i] = aclmdlGetOutputSizeByIndex(desc, i);
        aclrtMalloc(&odev[i], osz[i], ACL_MEM_MALLOC_HUGE_FIRST);
        aclmdlAddDatasetBuffer(ods, aclCreateDataBuffer(odev[i], osz[i]));
    }
    aclrtStream stream;
    aclrtCreateStream(&stream);
    // 静态内容上流（idx/cos = PMAX 内容，逐档前缀截断语义）
    aclrtMemcpy(dev[1], szs[1], g_idx, (size_t)PMAX * 2 * 4, ACL_MEMCPY_HOST_TO_DEVICE);
    aclrtMemcpy(dev[2], szs[2], g_cos, (size_t)PMAX * 2 * H * 2, ACL_MEMCPY_HOST_TO_DEVICE);

    int all_ok = 1;
    for (int gi = 0; gi < NGEAR; gi++) {
        int64_t p = GEARS[gi];
        uint16_t *x = make_x(p);
        aclrtMemcpy(dev[0], szs[0], x, (size_t)p * K * 2, ACL_MEMCPY_HOST_TO_DEVICE);
        // P3：多动态输入的 SetDims 策略探测（v1 单输入 index=0 可行；此处 145012）
        // S1 逐输入各调一次 / S2 index=0 拼 5 维 / S3 对 gear 输入(最后一路) 给 3 动态维
        aclError rc = 1;
        int strat = 0;
        for (int s = 1; s <= 3 && rc != ACL_SUCCESS; s++) {
            aclmdlIODims want;
            memset(&want, 0, sizeof(want));
            if (s == 1) {
                aclmdlIODims w0, w1, w2;
                memset(&w0, 0, sizeof(w0)); memset(&w1, 0, sizeof(w1)); memset(&w2, 0, sizeof(w2));
                w0.dimCount = 2; w0.dims[0] = p; w0.dims[1] = K;
                w1.dimCount = 1; w1.dims[0] = p * 2;
                w2.dimCount = 2; w2.dims[0] = p * 2; w2.dims[1] = H;
                aclError r0 = aclmdlSetInputDynamicDims(mid, ids, 0, &w0);
                aclError r1 = aclmdlSetInputDynamicDims(mid, ids, 1, &w1);
                aclError r2 = aclmdlSetInputDynamicDims(mid, ids, 2, &w2);
                rc = (r0 == ACL_SUCCESS && r1 == ACL_SUCCESS && r2 == ACL_SUCCESS) ? ACL_SUCCESS : (r0 ? r0 : (r1 ? r1 : r2));
            } else if (s == 2) {
                want.dimCount = 5;
                want.dims[0] = p; want.dims[1] = K;
                want.dims[2] = p * 2;
                want.dims[3] = p * 2; want.dims[4] = H;
                rc = aclmdlSetInputDynamicDims(mid, ids, 0, &want);
            } else {
                want.dimCount = 3;
                want.dims[0] = p; want.dims[1] = p * 2; want.dims[2] = p * 2;
                rc = aclmdlSetInputDynamicDims(mid, ids, nin - 1, &want);
            }
            strat = s;
        }
        printf("[run] gear %lld SetDims strategy S%d rc=%d\n", (long long)gi, strat, (int)rc);
        if (rc != ACL_SUCCESS) {
            all_ok = 0;
            free(x);
            continue;
        }
        rc = aclmdlExecuteAsync(mid, ids, ods, stream);
        if (rc != ACL_SUCCESS || aclrtSynchronizeStream(stream) != ACL_SUCCESS) {
            printf("[run] gear %lld execute FAIL rc=%d\n", (long long)gi, (int)rc);
            all_ok = 0;
            free(x);
            continue;
        }
        printf("[run] gear %lld execute ok\n", (long long)gi);
        // out（idx0）数值：首 2 行 + 尾 2 行
        uint16_t *y = malloc(osz[0]);
        aclrtMemcpy(y, osz[0], odev[0], osz[0], ACL_MEMCPY_DEVICE_TO_HOST);
        int64_t rows[4];
        rows[0] = 0; rows[1] = 1; rows[2] = p - 2; rows[3] = p - 1;
        double *yr = ref_out_rows(x, p, rows, 4);
        double ma = 0, mr = 1e-9;
        for (int r = 0; r < 4; r++)
            for (int64_t n = 0; n < K; n++) {
                double d = fabs((double)f16_to_f32(y[rows[r] * K + n]) - yr[r * K + n]);
                if (d > ma) ma = d;
                if (fabs(yr[r * K + n]) > mr) mr = fabs(yr[r * K + n]);
            }
        printf("[run] gear %lld OUT rel=%.4f%% %s\n", (long long)gi, 100.0 * ma / mr,
               ma / mr < 0.03 ? "PASS" : "FAIL");
        if (ma / mr >= 0.03) all_ok = 0;
        // hf（idx2，Reshape 链独立验）：行 0/1 与尾
        uint16_t *yf = malloc(osz[2]);
        aclrtMemcpy(yf, osz[2], odev[2], osz[2], ACL_MEMCPY_DEVICE_TO_HOST);
        int64_t frows[4] = {0, 1, p * 2 - 2, p * 2 - 1};
        double *fr = ref_hf_rows(x, p, frows, 4);
        double ma2 = 0, mr2 = 1e-9;
        for (int r = 0; r < 4; r++)
            for (int64_t j = 0; j < H; j++) {
                double d = fabs((double)f16_to_f32(yf[frows[r] * H + j]) - fr[r * H + j]);
                if (d > ma2) ma2 = d;
                if (fabs(fr[r * H + j]) > mr2) mr2 = fabs(fr[r * H + j]);
            }
        printf("[run] gear %lld HF(reshape) rel=%.4f%% %s\n", (long long)gi, 100.0 * ma2 / mr2,
               ma2 / mr2 < 0.03 ? "PASS" : "FAIL");
        if (ma2 / mr2 >= 0.03) all_ok = 0;
        // sm（idx1，TileD/BMM/Softmax 链）：行和 ≈1
        uint16_t *sm = malloc(osz[1]);
        aclrtMemcpy(sm, osz[1], odev[1], osz[1], ACL_MEMCPY_DEVICE_TO_HOST);
        double worst = 0;
        for (int64_t b = 0; b < P2; b++)
            for (int64_t r = 0; r < p; r += (p / 4 + 1)) {
                double s = 0;
                for (int64_t c = 0; c < p; c++) s += (double)f16_to_f32(sm[((b * p) + r) * p + c]);
                double d = fabs(s - 1.0);
                if (d > worst) worst = d;
            }
        // 布局判别：非末维动态的输出按最大档 stride（PMAX 行距）重读行和
        double worst_s = 0;
        for (int64_t b = 0; b < P2; b++)
            for (int64_t r = 0; r < p; r += (p / 4 + 1)) {
                double s = 0;
                for (int64_t c = 0; c < p; c++) s += (double)f16_to_f32(sm[((b * PMAX) + r) * PMAX + c]);
                double d = fabs(s - 1.0);
                if (d > worst_s) worst_s = d;
            }
        printf("[run] gear %lld SM stride=%lld read worst=%.5f（packed=%.5f）\n", (long long)gi, (long long)PMAX,
               worst_s, worst);
        if (worst_s < 1e-2) worst = worst_s;  // stride 读法成立则以 stride 判
        // 诊断：行 0 首 8 值（同行内容跨档一致——可直接对比）+ nan/inf 计数
        {
            int ninf = 0, nnan = 0;
            for (int64_t i = 0; i < (int64_t)osz[1] / 2; i++) {
                float v = f16_to_f32(sm[i]);
                if (isnan(v)) nnan++;
                else if (isinf(v)) ninf++;
            }
            double s0 = 0;
            for (int64_t c = 0; c < p; c++) s0 += (double)f16_to_f32(sm[c]);
            printf("[run] gear %lld SMdiag row0: v0..7=%g,%g,%g,%g,%g,%g,%g,%g sum=%.5f nan=%d inf=%d\n",
                   (long long)gi, (double)f16_to_f32(sm[0]), (double)f16_to_f32(sm[1]), (double)f16_to_f32(sm[2]),
                   (double)f16_to_f32(sm[3]), (double)f16_to_f32(sm[4]), (double)f16_to_f32(sm[5]),
                   (double)f16_to_f32(sm[6]), (double)f16_to_f32(sm[7]), s0, nnan, ninf);
        }
        printf("[run] gear %lld SM rowsum worst |Σ-1|=%.5f %s\n", (long long)gi, worst, worst < 1e-2 ? "PASS" : "FAIL");
        if (worst >= 1e-2) all_ok = 0;
        // CurOutputDims 验档位分发
        aclmdlIODims cur;
        memset(&cur, 0, sizeof(cur));
        aclmdlGetCurOutputDims(desc, 0, &cur);
        printf("[run] gear %lld CurOut dims0=%lld（want %lld）%s\n", (long long)gi,
               cur.dimCount > 0 ? (long long)cur.dims[0] : -1LL, (long long)p,
               cur.dimCount > 0 && cur.dims[0] == p ? "PASS" : "FAIL");
        if (!(cur.dimCount > 0 && cur.dims[0] == p)) all_ok = 0;
        free(x); free(y); free(yr); free(yf); free(fr); free(sm);
    }
    printf("[run] VERDICT: %s\n", all_ok ? "RUN_OK" : "RUN_FAIL");
    return all_ok ? 0 : 1;
}

int main(void) {
    const char *so = "/data/apxinf/ascendc/ge_builder/build/libge_builder.so";
    void *h = dlopen(so, RTLD_NOW);
    if (!h) {
        printf("[probe] dlopen fail: %s\n", dlerror());
        return 1;
    }
#define RES(sym, name)                          \
    sym = dlsym(h, name);                       \
    if (!sym) {                                 \
        printf("[probe] dlsym %s fail\n", name);\
        return 1;                               \
    }
    RES(p_geb_init, "geb_init");
    RES(p_geb_model_begin, "geb_model_begin");
    RES(p_geb_set_option, "geb_set_option");
    RES(p_geb_add_data, "geb_add_data");
    RES(p_geb_add_const_raw, "geb_add_const_raw");
    RES(p_geb_add_const_i32, "geb_add_const_i32");
    RES(p_geb_add_op, "geb_add_op");
    RES(p_geb_set_input_desc, "geb_set_input_desc");
    RES(p_geb_set_output_desc, "geb_set_output_desc");
    RES(p_geb_set_attr_bool, "geb_set_attr_bool");
    RES(p_geb_set_attr_int, "geb_set_attr_int");
    RES(p_geb_set_attr_int_list, "geb_set_attr_int_list");
    RES(p_geb_link, "geb_link");
    RES(p_geb_graph_inputs, "geb_graph_inputs");
    RES(p_geb_graph_outputs, "geb_graph_outputs");
    RES(p_geb_model_build, "geb_model_build");
    RES(p_geb_model_save, "geb_model_save");
    RES(p_geb_fini, "geb_fini");
    printf("[probe] ge_builder.so loaded\n");
    if (aclInit(NULL) != ACL_SUCCESS) printf("[probe] aclInit non-zero（可能已初始化，继续）\n");
    CK((int)aclrtSetDevice(0), "set device");
    aclrtContext ctx;
    CK((int)aclrtCreateContext(&ctx, 0), "create context");
    make_static();
    CK(p_geb_init("Ascend310P3"), "geb_init");
    const char *path = "/data/apxinf/probe_dyn/gear2v2.om";
    if (build_dyn(path) != 0) return 1;
    printf("[probe] OM size: %ld bytes（w+w2 Const=%d）\n", fsize(path), 2 * K * K * 2);
    p_geb_fini();
    return run_phase(path);
}
