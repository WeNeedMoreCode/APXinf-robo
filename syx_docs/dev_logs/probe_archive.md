# 引擎探针资产档案（2026-10-19 上库清理轮删除留档）

上库清理（post-port-cleanup skill 首战）：27 个 example 探针 + 2 个 standalone
main + ge_poc poc 目录 + 库内 12 个判死实验 env 门控从引擎删除（用户拍板
「全删+逐条记录用途与详情」）。完整源码在 git 历史（fork/ascend-port）。
本文档 = 每项的用途/实验背景/结论与恢复方法——未来需要同类诊断时先查这里。

**删除 commit**：波二 = 引擎 `9b7c8ea`（探针 + 门控）；波一 catgu = `91af3e8`
（快照见 10-19 战报 §七）。

**留存的例外**：`ge_model_probe`（apxinf-model/examples/）——生产工具，
烤桶（GEB_SEG/GEB_SAVE）、golden 对拍、A/B runner 的入口，非探针。

## apxinf-ascend/examples（19 个）

### 能力 smoke 系列（适配最早期能力验证）

| 探针 | 用途 | 备注 |
|---|---|---|
| `smoke.rs` | 地面真值：context + 显存 round-trip | 第一个跑通的 NPU 程序 |
| `matmul_smoke.rs` | 首个 aclnn 计算算子：fp16 matmul vs CPU | aclnnMatmul 入口验证 |
| `ops_smoke.rs` | elementwise + fused-norm（add/silu/add_rms_norm）vs CPU | |
| `backend_smoke.rs` | Backend trait 全链：to_device → matmul/add/silu/rms_norm → to_cpu | trait seam 验证 |
| `attention_smoke.rs` | PFA V3 融合 attention（BNSD fp16）vs CPU softmax-attention | |
| `rope_probe.rs` | RoPE：aclnnApplyRotaryPosEmb legacy entry（layout=1 BSND = Gemma rotate-half 语义）、in-place 语义 | |
| `graph_smoke.rs` | ACLGraph capture/replay（CANN 9.0.1+ 容器） | 后来被 ACLGraph 路线弃用，serve 走 GE OM |
| `ops_smoke.rs` | （同上） | |

### matmul 故障取证系列（action down 故障 ~2026-09 下旬）

背景：action 专家 down matmul `[50→64, 4096] × [4096, 1024]` in-graph 崩
（MatMulV2_ND_ND_FP16_FP32_false_true kernel），独立复现全过——一组探针
做故障画像：

| 探针 | 证实的结论 |
|---|---|
| `matmul_m_probe.rs` | M 维阶梯：失败集中在 tiny-M × wide-N；生产 M 数百则安全——零填充 workaround 的依据 |
| `matmul_layout_probe.rs` | 生产形状 `[8,2048]×[2048,2560]`：触发点锁定在 mat2 descriptor 的 stride（transposed-b 路径） |
| `matmul_addr_probe.rs` | 仅 in-graph（1GB+ 活分配后）崩；buffer 低 32 位近 4GB 边界 → u32 地址回绕嫌疑（ND kernel MTE 通道） |
| `matmul_seq_probe.rs` | 精确序列复现：geglu（gelu→mul）→ mul 输出直喂 down matmul 才崩 |
| `matmul_action_down_probe.rs` | 故障几何阶梯 + 邻域形状扫描（fresh process 逐个跑） |
| `matmul_entry_probe.rs` | per-task 固定开销隔离：time = a·m + b 里的 b（无 profiler 时的 start tax） |
| `matmul_wide_n_probe.rs` | wide-N 入口 bake-off：aclnnMatmul N≥12288 崩、N∈[4096,8192] transposed 读错数据 → aclnnMm/aclnnGemm 候补 |
| `matmul_ws_probe.rs` | workspace 尺寸/分配布局：GetWorkspaceSize 截断假设 vs malloc 布局假设 |
| `gelu_probe.rs` | Gelu 状态污染二分：前一算子（add/euler/cat/pfa）谁让下一个 GeluV2 segfault |

### GE 路线验证系列（C1 阶段）

| 探针 | 用途 |
|---|---|
| `ge_poc_probe.rs` | GE 静态 OM POC：MatMulV2 对链 in-memory 编译执行 + parity + per-matmul 计时（专用 POC shim 版） |
| `ge_builder_probe.rs` | C1-①：同一链路改走泛化 ge_builder FFI，证明泛化层与专用 shim 同分——ge_builder 转正依据 |
| `ada_rms_probe.rs` | fused ada-rms-norm 自研 kernel 对拍（host f32 参考 + 生产 aclnn 组合；ADA_RMS_DIAG=1 跑 bring-up 穿透诊断） |

## apxinf-model/examples（删 8 个）

| 探针 | 用途 | 阶段 |
|---|---|---|
| `ascend_layer_smoke.rs` | 首个真权重路径：Bf16LinearWeights upload 链 + 单 language layer 前向 | M1 |
| `ascend_full_smoke.rs` | 全随机权重 π0.5 前向（depth 缩减真宽度：N=32768 gate_up、多视图 vision attention、跨长 prefix attention） | M2 |
| `ascend_random_bench.rs` | 随机权重全模型 bench（vision + prefix + 10 flow 步 per-call） | D+F |
| `ascend_graph_capture_smoke.rs` | 全推理 ACLGraph capture（单 arena 分配）+ replay diff | perf 阶段（路线后弃） |
| `ascend_registry_smoke.rs` | AutoModel 注册 "pi05-ascend" 端到端 | E |
| `ascend_checkpoint_smoke.rs` | 真 ckpt（pi05_libero_finetuned 7GB）全深推理 | M3 前身 |
| `ascend_action_smoke.rs` | action 专家微缩复现器（styles + action_in + 层 + euler over 假 prefix KV）——down-matmul 故障的自包含 reproducer | 故障定位期 |
| `ge_layer_probe.rs` | C1-④：单层 GEMMA_2B layer 全序 GE 静态 OM vs eager aclnn 同输入对拍 + 背靠背 bench（668 行） | C1 |

## poc 期产物（ascendc 目录）

| 资产 | 用途 |
|---|---|
| `ascendc/ge_poc/`（ge_matmul_poc.cpp + ge_poc_main.cpp + CMakeLists） | C1 POC：MatMulV2 对链 GE 编译执行——证明静态 OM 路线可行；后由 ge_builder 泛化复刻，使命完成 |
| `ascendc/ge_builder/ge_builder_main.cpp`（geb_main） | ge_builder standalone driver：C1-② 转置 B 变体验证（transpose_x2 + [n,k] weight descs——NzCache 布局） |

## 库内判死实验 env 门控（波二删除，均在 ascend_ge.rs）

### 结构消融三件套（2026-10-16 dyn-vs-static 消融终裁的实验开关）

背景：t4 互差 13.1% 根因定位——「怪 GE 还是怪组装」。消融方法 = 在**静态图**
里逐一复现 dyn OM 的注册差异（bias/rope·qswap/smooth 三维度），bit 级对拍。
终裁：三维度全部 **bit 级惰性**（复现与否输出逐位相同），唯一元凶 = desc -1
分档编译本身（见 summary/2026-10-16_dyn-structural-ablation-verdict.md）。

| env | 复现的差异 | 原代码位置 |
|---|---|---|
| `GEB_ABL_BIAS`（V1） | 静态模式也走 gear 式 bias 注册：行重复注册为同形 [-1,cols]（rows==1 且未消费则折叠不注册），bias 消费端免 TileD 直接 Add | `row_bcast()` 与 `bias()` 两处并联条件（`gear_mode() \|\| ABL`） |
| `GEB_BIAS_REG` | ABL_BIAS 的对照开关（=1 时禁用 gear 式注册退回 [1,cols]） | `row_bcast()` 条件第二臂 |
| `GEB_ABL_ROPE`（V2） | 静态模式 rope swap 索引走 Data[-1] 注册（dyn 的逐档特化 vs 静态缺省 Const 折叠） | prefix 段 qswap/kswap 注册的 `if gear_ll.is_some() \|\| ABL` |
| `GEB_ABL_SMCONST`（V4） | 静态模式 smooth 烤 Const（dyn 缺省 Const vs 静态缺省 Data[k]，仅 prefix/ 作用域——reg_i8 为 prefix/flow 共用，flow 是对照组不可动） | reg_i8 的 smooth 注册分支 |

### 定值动态维实验（gear 模式 Const vs Data 的取舍取证）

背景：gear（dynamicDims 分档）模式下，常量向量（smooth/norm 缩放）有两种
注册法——Const（全档共享）或 Data[-1]+`set_gear_fix`（定值动态维，逐档特化
desc）。实验结论（保留在幸存代码的注释里）：**纯静态 Data 毒化 SetDims 档位
匹配（spike v3 定罪）；定值动态维撑爆 payload 的 ACL_MAX_DIM_CNT=128**（全深
18 层×9 输入+基础 24 = 186 维）→ 缺省 Const 胜出，实验臂删除。

| env | 作用对象 | 原代码位置 |
|---|---|---|
| `GEB_SM_DYN` | int8 smooth 向量（native 走 sm、非 native 走 inv 两处） | reg_i8 smooth/inv 注册分支 |
| `GEB_G_DYN` | prefix 段 g1/g2 norm 缩放向量（int8 torch 域 gamma） | seg_prefix 层循环 g1/g2 注册 |

### 一次性取证/诊断门控

| env | 用途与结论 | 原代码位置 |
|---|---|---|
| `GEB_OUT_PAD=<bytes>` | 输出 buffer 间插 dummy 占位（不改变输出自身大小）——若 k/v 读回变干净 ⇒ 相邻算子越界写踩用户输出实锤（OOB 取证）。定位完成 | seg run 的输出 malloc 循环（pads Vec 机制） |
| `GEB_STYLES_DBG` | styles/x0 状态 checksum 与首元素调试 print（4 处：serve x0 cs、cond head、L0a_scl head、styles_cache cs）。一次性数值排查 | serve 段 + e2e styles 预计算段 |
| `GEB_E2E_PK_GOLD` | e2e 下 pk/pv 改喂 golden kvk_l{i}/kvv_l{i}——step0 残差 bisect（检验 prefix 主路 k/v 残差喂 cross-attn 的贡献）。定位完成后死 | e2e pk/pv 注册（gold_key_f16 闭包 + 循环两分支） |
| `GEB_E2E_STYLE_GOLD` | e2e cond 替入 golden cond_s{step}（styles 仍由 host 投影重算——分离 {te+mlp 链} 与 {style 投影}）。定位完成后死；**无门控的 host-vs-golden diff print 保留**（golden 键存在才打，对拍诊断仍可用） | e2e styles 预计算 |
| `N32C` / `N32CV` | ge_model_probe 的 `n32c` 子命令：NORM32 组合链逐级编译二分（lvl 1=Cast / 2 +Mul / 3 +ReduceSumD / 4 +Sqrt / 5 +RealDiv / 6 全链；N32CV 变体矩阵 = ReduceSumD/ReduceSum × axis/axes × keep_dims）——rc=-7 定位（AfterInfershape 后失败，算子逐个定罪）。定位完成后死。**n32v 子命令保留**（NORM32 生产链数值验证，NORM32 是活语义特性） | probe 子命令 match 的 "n32c" 臂 |

**恢复方法（门控）**：`git -C apxinf show 9b7c8ea^:crates/apxinf-model/src/pi05/ascend_ge.rs`
对照上表位置摘段；并联形态的门控（ABL_*）删法是去 `|| envi(...)` 臂，恢复即
加回该臂。

## 恢复方法（探针）

```bash
# 删除 commit = 9b7c8ea；探针源码在其父提交
git -C apxinf checkout 9b7c8ea^ -- crates/apxinf-ascend/examples/<name>.rs
git -C apxinf checkout 9b7c8ea^ -- crates/apxinf-model/examples/<name>.rs
# Cargo example 自动发现，放回即可 cargo run --example <name>
```
