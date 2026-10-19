# 引擎探针资产档案（2026-10-19 上库清理轮删除留档）

上库清理（post-port-cleanup skill 首战）：27 个 example 探针 + 2 个 standalone
main + ge_poc poc 目录从引擎删除（用户拍板「全删+逐个记录」）。完整源码在
git 历史（fork/ascend-port，删除 commit 之前）。本文档 = 每个探针的用途与
结论速查——未来需要同类诊断时先查这里，恢复从 git 历史 checkout。

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

## 恢复方法

```bash
git -C apxinf checkout <删除commit>^ -- crates/apxinf-ascend/examples/<name>.rs
# Cargo example 自动发现，放回即可 cargo run --example <name>
```
