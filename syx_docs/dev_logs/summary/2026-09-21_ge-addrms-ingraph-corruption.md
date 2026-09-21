# M3 剩余漂移定罪：GE 图内 AddRmsNorm 读"在图中间量"被污染（内存计划重叠嫌疑）

日期：2026-09-21（上午班）　前置：[M3 真根因 empty_camera](2026-09-21_m3-empty-camera-mask-root-cause.md)（上轮收口推断"2.8% 产自图内 manual attention 链真实输出"——本轮**推翻**）

## 一句话

**kvk_l1 45.2% 漂移的最小复现缩到 ~13 个算子并定罪到 AddRmsNorm 读在图中间量**：attention 链（0.229%）、o_proj 消费（0.089%）、gate/up 宽 N mm（0.057%）、down K=16384 mm（0.017%）、MLP 尾组合（0.032%）、权重折叠（0.032%）、M 对齐、GQA 簇、rope、dual-role 槽、auto-bind extras 全部洗清；唯一定罪签名 = **[X(在图中间量) → AddRmsNorm] 数值错（11-13% 级），同值作 Data 输入则 0.073% 干净**（wmm4 决定性实验）。五类屏障/端口变体（mul-ones/x1x2 对调/恒等 Reshape/Add 操作数对调/恒等 mm）输出逐位不变 + 小图 [mm→addrms] 干净（wmm5）+ 图形状强敏感（net 45.2 / dbg 24.7 / M 垫充 24.66 / MIN 11.0 / RES_GOLDEN 78.6）⇒ 收敛到 **GE 静态 OM 内存计划重叠活 buffer**（确定性 per-plan；大 buffer 尺寸变化即改变结果）。生产影响面：prefix 每层 2 处 [add→addrms]（res→n2、h→n1_next）× 18 层 + flow（1.6% 残差同病小 shape）——与 kvk_l0 净（x0 是 Data）/ kvk_l1 45.2% / l17 84% / actions 323% 的传播链完全吻合。

## 定位链（当晚 16 步，全部实测）

| # | 实验 | 结果 | 裁决 |
|---|---|---|---|
| 1 | `GEB_OPTEST=attn` 最小图（真 x0_vis → [norm1→qkv3→ropeflat→headsplit→GQA→headmerge→o_proj→+res]，四件套同款） | m0sq **0.229%** / res **0.089%** | **attention 链无罪**——上轮"槽与消费值不一致"推断推翻：m0 槽是真的、norm2 2.82% 槽是假的（覆写） |
| 2 | 延伸 [L0 MLP 尾 → L1 {addrms→k mm→bias→rope}] = kvk_l1 公式 | kvk1 **45.224%**（与全净图 45.2% 六位一致） | 漂移在最小图复现；h1 槽全垃圾（≥54%） |
| 3 | fold_sim.py（f64/f16 模拟 unfolded vs folded） | 均 **0.032%**，零溢出（(1+w_post) max 12.4） | **Gemma 1+w 权重折叠无罪**（通道指纹 674/50/1870/738/604 同源但误差被图放大 1000×） |
| 4 | attnmin_scan.py（槽对号+行/通道结构） | act 槽 20.831%（视觉行 110%/文本 20.8%）；kvk1 行剖面 视觉 16-19%/文本 51-53% | 误差带行/通道结构；全行有错 ⇒ 非 M 尾部腐化 |
| 5 | GEB_ATTN_MLP_PAD=1（MLP 段 M 垫 712→720） | act 20.8→3.05%、kvk1 45.2→**24.66%**（≈dbg 图 24.7%！） | **部分有效**——M 非对齐是放大因素非根因；图形状/分配敏感首证 |
| 6 | wmm（gate 单算矩阵：M{712,720}×{cst,nd}×{全宽,拆半}+eager） | 全 **0.057%** | **宽 N=16384 mm 无罪**（Const NZ 折叠/拆半/M 全部干净） |
| 7 | wmm2（down 单算 K=16384） | 全 **0.017%** | **大 K mm 无罪** |
| 8 | wmm3（组合阶梯 A[addrms→gate]/B[+gelu]/C[+act]/D[全尾→h1]，golden res0 输入） | 全净，D_h1 **0.032%** | **MLP 尾整链组合无罪**（从 Data 出发） |
| 9 | attn 变体×5（去 norm 槽/V1 RES_GOLDEN/FAKE/MIN/去 dual-role） | 45.224→78.594/45.175/**11.041**/11.041 | V1：MLP 吃 golden res0 仍脏 ⇒ 非值传播；FAKE：GQA 簇无罪；**MIN（无 attention/qkv/rope）仍 11.041%** ⇒ 病根在 [MLP 尾→L1 接续] |
| 10 | L1 段二分：L1=mm（跳 addrms+rope） vs L1=norm（只留 addrms） | mm **0.036%** / norm **12.858%** | **AddRmsNorm 定罪**（rope 无罪）；在图 h1 tap 0.032% 干净 |
| 11 | wmm4（**golden h1_vis 作 Data 输入** → addrms → k mm） | **0.073%** | **值无罪、输入来源定罪**：同值同算子，Data 干净/在图脏 |
| 12 | wmm5（小图 [mm+bias→addrms→mm] / [+gather 拷贝]） | M 链 **0.058%** | mm/bias 输出喂 addrms 小图干净 ⇒ 非简单生产者类型规则 |
| 13 | 屏障/端口变体×5（bar=mul-ones/swap=x1x2 对调/rshp/swapadd/mbar=恒等 mm） | **全部逐位 11.041%**（max_diff 1.08594 相同） | buffer 地址/端口/操作数次序全无关——确定性值级现象 |
| 14 | addrms_hypo 离线穷举（全局 rms/eps/mean/平方饱和/bf16/f16 累加/宽 2047/4096） | 全 ~12.8% 基线级 | **非 rms 公式错误** |
| 15 | addrms_hypo2（k 是否=未归一化 h1@Wk） | 97%、712/712 行归一化更优 | "mm 读 pre-norm 张量"假设灭 |
| 16 | `ge.exec_reuseLevel=0` → 编译拒 rc=-7；libge_compiler.so strings 找到 **`ge.bufferOptimize`** | — | 下轮第一候选：`GEB_OPT_ge.bufferOptimize=off` |

## 定罪签名（复现图与旋钮）

```bash
# 最小脏图（~13 算子，11.041%）：
ASCEND_RT_VISIBLE_DEVICES=6 GEB_OPTEST=attn GEB_WCONST=1 GEB_ATTN_MIN=1 \
  GEB_CKPT=... GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3.safetensors ge_model_probe
# 0.036% 干净对照（唯一差异 = 去掉 addrms）：GEB_ATTN_L1=mm
# 0.073% 干净对照（唯一差异 = h1 换 Data 上传）：GEB_OPTEST=wmm4
# 全量变体旋钮：GEB_ATTN_MLP_PAD / RES_GOLDEN / FAKE / SWAPADD / L1=bar|swap|rshp|mbar|norm|mm
# 单算矩阵：GEB_OPTEST=wmm|wmm2|wmm3|wmm4|wmm5（dump /data/apxinf/{attnmin,wmm}/）
```

## 生产影响面（为何 e2e 是 314%→323% 的剩余大头）

- prefix 18 层 × 2 处 [add→addrms]（res→n2、层间 h→n1）：kvk_l0 0.3%（x0 是 Data 免疫）→ kvk_l1 45.2%（第一处污染后）→ kvk_l17 84%（逐层复合）
- flow 1.6% 残差 = 同病小 shape（HOR=50 行，污染幅度小）
- vision 无 AddRmsNorm（SigLIP 用 LayerNormV4）→ 0.1% 干净，佐证

## 下一轮攻坚（按优先级）

1. **`GEB_OPT_ge.bufferOptimize=off`**（选项已确认存在于 libge_compiler.so，atc 同名 --buffer_optimize）——跑 MIN 复现图
2. 若无效：libge strings 扫描全部 `ge.*` 内存相关选项逐一 A/B（方法已验证）
3. **ReduceSum/Rsqrt 分解 norm** 彻底绕开 AddRmsNorm（Mul→ReduceSumD→Add(eps)→Rsqrt→TileD→Mul，需先验 310P GE 注册表有这些算子）——最稳妥兜底，C2 带宽教训下代价 ~+3ms
4. 显式 TransData 插入（若格式错配）
5. MLP 大 buffer 布局扰动扫描（已证 M 垫充改数值——可二分重叠对）
6. 修好后：attn 图 kvk1 ≤0.1% → 生产 prefix/flow 图全 [add→addrms] 处应用 → kvk_l1 ≤5% → 全层 → e2e 终态 → LIBERO（9/10）

**顺带结案**：`GEB_OPTEST=arm` 的 GE 侧 rc=-3 根因 = addrms 的 y 绑图输出时 GE 自动补绑悬空 rstd/x_out（n_out 声明 1 模型 2+）——attn 首跑同坑。修法 = 输出按 `num_outputs()` introspection 分配（attn 模式已内置）。AddRmsNorm 无罪的部分：读 Data 输入时完美（eager/图皆然）。

## 教训（对拍方法论追加）

1. **图输出槽 ≠ 真值**（覆写已知），但**图输出数 ≠ 声明数**是新坑：绑多输出算子（AddRmsNorm/LayerNormV4 系）的 y 作图输出会触发兄弟端口自动补绑——run 时 n_out 不匹配报 rc=-3，且槽序错乱。一律按模型 introspection 分配输出、按值对号。
2. **"算子单算干净 + 组合脏"的病要往内存计划/调度层查**，不要在算子语义里穷举公式（本轮公式穷举 8 个全灭）。
3. 逐位相同的错误输出跨图变体出现 = 污染源在**未变化的图区域**（分配计划），是内存重叠类 bug 的强指纹。
