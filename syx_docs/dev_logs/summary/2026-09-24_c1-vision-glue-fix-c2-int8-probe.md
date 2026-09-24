# C1 vision glue 修复（0.682×→0.654×）+ C2 int8 单算 probe 全过（QuantMatmulDequant 2.41×）

日期：2026-09-24（本地 11:55-12:40，handoff 定稿规划的"性能第二波"① C1+C2 连打完成）

## 一句话

**C1：vision "65-68ms 回归" 三实验定罪 = 纯 host glue（设备侧 56.26ms 与 C2 收官 55.86 一致，双口径互证）——真凶 d2h 3.4ms + f16 解码 5.1ms；零拷贝字节视图 + 三段全挂流修复后 vision 66→59.4ms，sum 246 = 376 基线的 0.654×，bit 恒等 + task0 行为 1.0。C2：QuantMatmulDequant 在 310P GE 图内单算三连全过（编译/数值 0.564%/性能 2.41×）；真权重 L1/L2 判决——朴素 per-token W8A8 被 Gemma 激活 outlier 打爆（12.7%），smoothquant 修复成立（0.831%，性能零代价）——int8 全链立项条件满足（须带 smooth 校准）。**

## C1：vision serve 段 glue 判决链与修复

### 判决实验（chip2/3，tl144 桶，修复版 cdylib）

| # | 实验 | 口径 | 结果 |
|---|---|---|---|
| E1 | check.py（serve 路径） | h2d+run+sync+d2h(idx0) | vision **65.9-66.5** / prefix 106 / flow 80.3，sum 252.9，parity 0.0244 ✓ |
| E2 | ge_model_probe vision bench（GEB_ROUNDS=30 median） | run×10+sync（无传输） | **56.26ms**——与 C2 收官 55.86（+0.7% 跨日噪声）一致 ⇒ **设备侧无回归** |
| E4 | GEB_SERVE_TIMING 分步插桩（子模块 731ef5a） | conv/h2d/run/sync/d2h/dlconv 六分 | **conv 0.24 / h2d 0.4 / run(enq) 0.3 / sync 55.7 / d2h 3.4 / dlconv 5.1** |

定罪：~10ms glue = d2h 3.4（3.1MB 同步 memcpy）+ dlconv 5.1（1.57M 元素 chunks_exact 逐元素 f16 解码）；**111 输出 dataset 重建（0.3ms）与 run enqueue 均洗清**。

### 修复（子模块 ada176d，bit 恒等论证 + 冒烟验证）

- `context.rs`：+`copy_h2d_async`/`copy_d2h_async`（aclrtMemcpyAsync 上流，照 d2d 版）
- `VisionMech::one_frame`：f16 字节视图零拷贝 reinterpret（`wbuf_t` 同款）+ h2d→run→d2h 三段全挂流 + **单次 sync**；d2h 直写预分配 `Vec<f16>` 字节视图（解码消失）
- `PrefixMech::one_frame_dev` / `FlowMech::one_frame_fast`：x0/noise 零拷贝 + h2d 上流

字节流路径不变、单 stream FIFO 序不变 ⇒ 数值恒等；E5 冒烟：**max_diff=0.0244 三连逐位同** + vision **59.3-59.5**（-6.6ms）+ **sum 246.1-246.3 = 0.654×**（376 基线；hit handoff 预估的 0.65×）。

### 行为回归

task0 闭环 eval（supervisor fast + 流水化 serve）：**success 1.0（162 步健康，33 calls）**。model_ms P50 264.0（spool 口径；直调 246 + spool ~18ms，见遗留）。

### 机制发现（顺手）

`aclmdlExecuteAsync` 实际语义 = **host 阻塞到接近设备完成**（E5: wait=0.01 / run+d2h_enq=58.9 与 E4: run=0.3 / sync=55.7 互补视角）——它内部同步于流内先前工作。bench 循环（per×10 背靠背）里这被流水掩盖，serve 单发调用则全额暴露——**跨口径比性能数字时须记住这一不对称**。

## C2：int8/w8a8 单算 probe——全过

### 注册表勘察（310P opp，零编译取证）

量化 matmul 三家族在册：`QuantMatmulDequant`（x f16 / w int8 / scale f32 → y f16，2-D mm = prefix 主战场）、`WeightQuantBatchMatmulV2`（batch 形态）、`QuantBatchMatmulV3`（全 A8W8）。`quant_matmul_dequant` 有预编译 kernel（ops_legacy 2 变体）。**aclnn 头文件**（aclnnop/aclnn_quant_matmul_dequant.h）与 **torch_npu GE 原生封装**（auto_generated_ge_raw_ops.py）给出权威 IR 契约：`ATTR(x_quant_mode, String, "pertoken")`、`ATTR(transpose_weight, Bool, true)`。

### probe（GEB_OPTEST=qmd，m=832 k=2048 n=8192，chip3）

| 判决 | 结果 |
|---|---|
| 编译 | ✓（GE 图内 **ND int8 权重直接接受**——注册表 FRACTAL_NZ 提示不拦裸 Data 喂入；v1 拒因 = attr 契约缺失：不设 `x_quant_mode` + transpose_weight 布局错 → task_distribute rc=-7 且 plog 无细节） |
| 数值 | Q-vs-F（量化 vs f16 执行）rel=0.564%；host 双参考 **W8A8 0.0156 ≪ W8A16 0.2774 ⇒ 内部 = per-token 激活量化兑现**（x_quant_mode="pertoken"），误差 ~0.019% 量级 |
| 性能 | **0.737 vs 1.790ms（生产转置布局）= 2.41×；vs 无转置 2.281 = 3.10×**（37.9 vs 15.5 TFLOPS） |

### 坑（已回填代码注释）

1. GE 编译拒的 attr 契约：x_quant_mode 必须显式（默认值不自动生效于裸 op 构图）；transpose_weight=true 是 linear 风格 [n,k]。
2. f16 基线链 `transpose_x2=true + desc[n,k]` 需要 **wt() 转置管线字节**，裸 [n,k] row-major 读错（饱和 ±65504）；probe 用无转置形态（transpose_x2=false + [k,n] 转置存储）自证。
3. `rand_f16` 第三参是**除数**（值域 U(±100/div)）——div=1 时 y 必然饱和 65504（C1 探针数据教训重演第三次）。
4. `pkill -f ge_model_probe` 会自匹配自杀（命令行含模式串）。

## C2 续：真权重 L1/L2 判决（同日 13:00-13:15，子模块 7e8cced）

### L1 权重量化误差谱（纯 host，`int8_weight_errspec.py`，per-output-row int8）

| 权重组（用途） | rel_rms 中位 | 最差矩阵 | worst_row max |
|---|---|---|---|
| gemma_expert（flow） | **0.76-0.80%** | 1.20% | ≤2.6% |
| paligemma 主干（prefix） | 0.87-1.04% | 2.03%（L00） | **11.2%**（down_proj 个别行，L00/01/05/07/08 集中） |

对照：理论均匀量化 0.454%、f16 表示噪声 0.028%。真权重 ≈ 合成的 2 倍——权重侧无障碍，outlier 集中在 paligemma 主干 down_proj 的个别行（缓解：per-group / 混合精度）。

### L2 真权重+真激活执行差（`GEB_OPTEST=qmd GEB_QMD_REAL=1`：x = golden res0 [712,2048]（std=10.8，**|max|=559** = Gemma 激活 outlier 实锤）× w = L07 mlp.gate [2048,16384]）

| 形态 | Q-vs-F 执行差 | W8A8 数学自检 |
|---|---|---|
| 朴素 per-token W8A8 | **12.693%**（合成的 0.564% 恶化 22×） | 0.0298（精确） |
| **smoothquant**（`GEB_QMD_SMOOTH=1`，α=0.5，s_k∈[1.3,138.8] host 预折叠，数学恒等） | **0.831%** | 0.0241（精确） |

判决：**朴素 W8A8 不可用**（per-token scale 被 outlier 拉爆，host 双参考定位误差全在激活量化侧——W8A16 ref 27.7）；**smoothquant 修复成立**（0.831% = f16 执行差同量级，性能零代价 1.364ms 不变）。生产化路径 = s_k 折进 int8 权重 + 算子原生 `smooth_scale` 输入（x 原样进图，零额外算子）。m=712 n=16384 形态 int8/f16 = 1.56×（大 N 下 f16 效率更高所致）。

### 泛化性验证（`GEB_QMD_MATRIX` 旋钮，子模块 5d6d406，同 golden 激活 × 4 权重矩阵）

| 矩阵 | n | s_k 范围 | smooth 后执行差 | int8 加速 |
|---|---|---|---|---|
| p7gate | 16384 | [1.3, 138.8] | 0.831% | 1.56× |
| p0gate（L1 worst 层） | 16384 | [1.0, **831**] | **0.678%** | 1.56× |
| p17gate | 16384 | [0.9, 24.3] | 0.655% | 1.54× |
| a7gate（expert = flow 侧） | 2048 | [3.2, 67.8] | 1.424% | 1.49× |

全部矩阵 smooth 后 0.66-1.42%——f16 执行差同量级，泛化成立（expert 侧略高：权重 std 0.038 更小 → 相对量化噪声大 + n=2048 小矩阵）。**性能实数修正：生产 gate_up 形态 [712×2048×16384] int8 = 1.49-1.56×（合成 m832/n8192 的 2.41× 是形状效应）——立项收益预期按 prefix matmul 1.5-1.6× 重估，全链 ~200ms = 0.53× 量级**。

### 立项终审（更新）

- 数值面：smoothquant 后 0.66-1.42%/层（4 矩阵泛化验证）——与 f16 累加序差同量级，**行为风险从"致命"降为"须 LIBERO 实测"**
- 校准面：s_k 需要每层每投影一组 per-input-channel 因子（静态校准——golden 帧或小样本集的激活 per-channel max；单帧已 work，多样本求 max 更稳）
- 工程面：prefix OM 重烤（int8 权重 Data/Const + smooth_scale 输入）；flow 同构但 10 步欧拉放大待判
- **收益实数**：生产形态 int8 = 1.5-1.6×（非 2.41×）→ prefix matmul 70ms 级 → ~45ms，全链 ~200ms = 0.53× 量级


### 立项外推（下轮决策输入）

prefix 102ms 设备时间里 matmul 若占 60-75ms → int8 后 ~20-31ms → prefix ~52-62ms；flow 76.7ms 同构可吃同红利（**10 步欧拉的量化误差放大是行为风险，golden/LIBERO 判**）。全链 sum 246 → **~165-206ms = 0.44×-0.55× 量级**。量化校准面：per-channel scale host 可精确计算（probe 已验证数学）；Gemma outlier 的实际误差谱要真权重 probe（下轮第一动作）。

## 遗留与下一步

- ~~spool 口径疑点~~ **销案（同日 13:28-13:38 三连）**：task0 model_ms P50 = 264.0 / 258.0 / **262.5**（第三次 = asm 缓存版新二进制，success 1.0）——跨次波动 ±3%（芯片分配/桶 warmup 噪声），无真回归；**教训：spool 单 task0 口径分辨不了 <3ms 的改进，小改进用直调 check.py 口径判**（asm 缓存直调 246.1→245.5 可见）
- ~~prefix asm 2.5ms~~ **已修（同日 13:30，子模块 1bf4201）**：token 查表缓存（prompt 跨 replan 恒定）→ asm 2.5→1.5ms，sum 稳态 245.5，bit 恒等 0.0244。⚠ supervisor 桶进程要用新二进制须重启（本轮 eval 用的旧 inode）
- C2 立项内容（若做）：smooth 因子静态校准（多样本）→ s_k 折权重 + smooth_scale 输入 → prefix OM int8 重烤 → golden parity → LIBERO 行为 → 全量回归
- B 动态 L 定形 / M2 eager 补 gate / A3 inproc 可选——handoff 原序不变

## 交付物

- 子模块 `731ef5a`（GEB_SERVE_TIMING 分步插桩）/ `ada176d`（零拷贝+流水化修复）/ `3b5d54f`（qmd probe + Dtype::Int8 + data_i8），fork/ascend-port 已推
- 服务器：`/data/apxinf/pyo3_check/e{1,2,4,5}_*.log`（判决链证据）、`/data/apxinf/serve/eval_c1pipe_t0_*`（task0 行为）
- 新锚点：**fast 全链直调 sum 246.1-246.3 = 0.654×**（vision 59.4 / prefix 105.7 / flow 81.0）
