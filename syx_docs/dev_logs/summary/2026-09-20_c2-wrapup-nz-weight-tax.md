# C2 收尾：prefix 漂移销案 + NZ 权重税根因 + WCONST 三段 → 全模型 263ms（378 线 0.70×）

日期：2026-09-20 凌晨　chip6（全数字同芯背靠背）　代码：ge_model_probe.rs + ge_builder（C++/Rust FFI）

## 结论一览

| 项 | 结果 |
|---|---|
| prefix 25.1% 漂移 | **销案（probe 侧）**：深度曲线平滑次线性无跳变 + layer0 逐位一致 → fp16 大 K 累加序差坐实，M3 e2e 判定 |
| flow 每层 ~1ms 开销 | 分解 = 0.06ms 固定 + **0.975ms/层全在图内**；其中 **~0.53ms/层是 NZ 权重税** |
| NZ 权重税根因 | GE 对每个 ND Data 权重输入**每执行**插设备侧 ND→FRACTAL_NZ TransData（54% 总时长；torch_npu TransData 100ms 同源） |
| 单算裁决（wgt） | Const 入图 **0.3945→0.2945 ms/mm（−25%）、OM 烤入权重 8.4MB**；NZ desc 直入编译崩 |
| GEB_WCONST 三段 | vision **68.06→55.89** / prefix **187.75→128.44** / flow **17.51→7.90 ms/步（−55%）** |
| **全模型** | **~431 → 263.3ms = 378ms 验收线的 0.70×；累计 2182→263 = 8.3×** |
| 验收线判定 | **C 路线达标（比 torch_npu 378ms 快 31%），进 M3（LIBERO 对标）** |

## ① prefix 漂移深度扫描（handoff 第一动作）

`GEB_SEG=prefix GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_DEPTH=2/4/8 GEB_ROUNDS=3 GEB_PER=1`（depth18=25.1% 已知）：

| depth | worst rel | 增量/层 |
|---|---|---|
| 2 | 6.0% | — |
| 4 | 10.9% | ~2.5pp |
| 8 | 15.6% | ~1.2pp |
| 18 | 25.1% | ~0.95pp |

- **平滑单调、增速递减（次线性），无跳变**；√d 拟合系数 4.3-5.9 稳定 → 随机游走式累积。
- 决定性细节：depth2 输出里 **layer0 的 k/v max_diff=0.00000（逐位一致）**——输入相同 → qkv+rope 逐位同；分岔出现在**第一个完整 transformer block 之后**（5.6%），即首个大 K matmul（down proj K=16384）重排累加序之时。fp16 累加序指纹。
- handoff 旧记录"depth2 已知 8.5%"与本次 6.0% 不符（出处不明的旧配置数据），以本次同二进制背靠背曲线为准。
- **销案判据达成**：probe 侧结案，归 M3 e2e（LIBERO 成功率）判定。跨段宽度单调（INTER 4304→0.1% / 4096→1.6% / 16384→25%）自洽。

## ② flow 尾巴分解

DEPTH=1/2/4 bench（ROUNDS=5 PER=3）：1.0366 / 2.0128 / 3.9613 ms → **ms(d) = 0.06 + 0.975·d**（两段斜率 0.976/0.974，线性完美；外推 d18=17.6 ✓ 对上 17.51）。per-execute 开销仅 ~0.06ms（264 输入绑定免费），成本全在图内每层。

## ③ NZ 权重税（本轮核心发现）

msprof flow 全深（DEPTH=18 ROUNDS=5 PER=1，导出成功日）op 统计（÷9 迭代）：

- **TransData 497/迭代 ≈ 27.6/层，10.3ms/迭代（54% 总时长）**；MatMulV2 7.9/层仅 31%。
- op_summary shape 签名钉死大户：`[4096,1024] → [64,256,16,16] [ND→FRACTAL_NZ]`（8MB 权重 ~130µs @~63GB/s）、`[1024,4096] → [256,64,16,16]` 同族 + [1024,1024] 2MB 档小户 —— **每个 MatMulV2 的 b 权重（Data 输入）每执行一次设备侧 ND→NZ 转换**，不做跨执行缓存。
- 每层 8 个 mm 权重（qkv3 3 + proj 1 + gate/up/down 3 + ainwt 1）≈ 531µs/层，与 0.975ms/层的 55% 吻合。
- 同源现象：M2 期双边 profiling 里 torch_npu 的 TransData+Transpose 100ms（397ms 的 25%）就是同一笔税；TorchAir 378ms 靠**权重入图**（编译期转换）逃掉。
- 顺带发现：GE 编译器已自动融合 matmul+add / matmul+mul（`te_fused_op_mat_mul_add/mul`，AutomaticBufferFusionOp）——bias 链无需手工处理。
- 外推三段税额：flow 9.5ms/步（×10=95ms）、vision ~17ms、prefix ~66ms ≈ 全模型 ~178ms。

## ④ 单算裁决 GEB_OPTEST=wgt

新增 FFI：`geb_add_const_raw`（任意 dtype Const）/ `geb_add_data_fmt` + `geb_set_input_desc_fmt`（ND/FRACTAL_NZ desc）。同 mm（[832,1024]×[4096,1024]ᵀ）三权重形态：

| 变体 | ms/mm | OM | 对拍 |
|---|---|---|---|
| nd（Data 现状） | 0.3945 | 67 KB | 0.00000 |
| **cst（Const）** | **0.2945** | **8.4MB（权重烤入）** | 0.00000 |
| nz（NZ desc 直入） | — | TBE task_distribute 编译崩 | — |

**Const 权重编译期折叠 NZ 转换实证**：省的 100µs ≈ 8MB 转换成本；OM 大小即证据。nz desc 直入在 310P 未走通（MatMulV2 对 rank-4 NZ x2 desc 编译拒），记开放项——它是"OM 保持 checkpoint 无关"的替代路线（host_nz_reorder 语义已与 GE transdata 输出签名核对一致：[k/16,n/16,16,16] W-major 块序）。

## ⑤ GEB_WCONST 三段推广

设计（防 flow 索引 bug 前科重演）：
- `Seg.wt()`：权重注册分流——GEB_WCONST 时 Const 入图，**binds 仍全量持上传副本**（eager 权重库/层基址索引两模式恒同），另立 `data_inputs: Vec<usize>` 映射 + `ins()` 装配真图输入。
- 16 个权重注册点全部 `data_buf(wbuf_t(...))` → `wt(...)`（vision 6/层 + patch_wt/projwt；prefix 6/层；flow 8 项含段级 ainwt/aoutwt）。LN/bias/rope 表/msc/msh/pk/pv 留 Data（无 NZ 税或每执行变化）。
- 验证：flow depth2 parity **worst=0.00293 与 Data 模式逐位相同**（Const 与 Data 喂同字节 → 同 kernel 同结果；索引镜像正确性的直接证据）。

全深度（ROUNDS=30 PER=10 median）：

| 段 | round-2 | WCONST | OM |
|---|---|---|---|
| vision 27 层 | 68.06（0.1%） | **55.89**（0.1%） | 834MB / n_in 277 |
| prefix 18 层 | 187.75（25.1%） | **128.44**（25.1%，worst 0.237→0.361 同档微移） | 3.76GB / n_in 138 |
| flow 18 层/步 | 17.51（1.6%） | **7.90**（1.6%） | 628MB / n_in 216 |
| **全模型** | ~431 | **263.3** | 5.2GB |

- prefix worst 微移：NZ 折叠后权重字节布局不同 → mm kernel 变体累加序又换一档，rel% 量级不变——与 fp16 累加序假设自洽。
- 产物：`/data/apxinf/om_cache/{vision,prefix,flow}_r3.om`；**GEB_LOAD 加载路径验证通过**（flow 8.25ms 一致）。
- **架构代价（ADR-002 更新）**：OM 变 per-checkpoint（权重烤入），缓存 key 需含权重版本；构建期多付一次 host NZ 折叠（分钟级一次性）。这正是 TorchAir 的模型。

## 验收线判定（⭐）

**263.3ms ≤ 378ms 线（0.70×）——C 路线（GE 原生 OM）全面达标：部署形态（纯 Rust 引擎 + 静态 OM）+ 延迟双赢（比 torch_npu/ModelZoo 基线快 31%）。进 M3：真 checkpoint 三段接入 + LIBERO 对标。**

## 顺手修复

- bench 边缘 case：`skip = rounds.min(3)` 在 ROUNDS=3 时吃光全部轮次 → `ts` 空仓 panic（ge_model_probe bench 段）。改 `saturating_sub(1).min(3)`。

## 遗留 / 下一步

1. **M3 起跑**：真 checkpoint 权重接入三段（host 权重解析 → wt() Const 路径）→ e2e 延迟 + LIBERO 成功率（同时判定 prefix 25.1% 漂移的实际影响）。
2. nz desc 直入（OM 保持 checkpoint 无关的替代路线）：310P MatMulV2 编译拒 rank-4 NZ x2，未深挖（origin shape 语义/其它 op 组合待试）。
3. 非 NZ 税常量输入 Const 化（rope cos/sin 表、swap 索引、LN gamma/beta）：无税但省输入槽/带宽，后置小收益。
4. prefix MLP busy ~120ms 是算力下限（[832,2048]×[2048,16384]×3 @23.5 TFLOPS）；再往下是 INT8/量化领域。
