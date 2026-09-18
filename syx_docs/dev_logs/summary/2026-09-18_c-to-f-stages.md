# 2026-09-18（深夜续）：C 收官 → D+F 完成 = M2 运行半

## 本段完成

1. **C 阶段收官**：`ASCEND_FULL_SMOKE_OK`——全模型随机权重前向（vision 2 层 + language 2 层 + 10 步 flow denoise）全设备执行。`ascend_runtime.rs`（`Pi05AscendRuntime`）镜像 bf16_runtime eager 路径
2. **D 阶段**：`ascend_vla.rs`——`Pi05AscendVlaRuntime` 实现 VlaRuntime trait（eager-only；patches 输入、core RNG 噪声、时间嵌入一次性构建；rgb-u8/tuning/capture 桩化）
3. **F 阶段**：`ASCEND_RANDOM_BENCH p50=197.5ms`（n=20，depth 2/2/2 真实宽度，走 prepare/run 真实接口）= **M2 运行半达成**

## 本段真 bug（全部取证定位，证据链在 roadmap）

| # | bug | 定位手段 |
|---|-----|---------|
| 1 | action 层 inter 从融合宽度算出又乘 2 → b 描述符 2×越界 | NzCache 转置形状打印 [512,16384] vs 正确 [1024,8192]，一眼定罪 |
| 2 | vision position 表硬编码 2 视图（π0.5 是 3）；attention 未按 view 分段 | 对读 cuda kernel 语义（add_position / mha tokens_per_batch） |
| 3 | gate/up 反了（gelu 加错半边） | 读 from_host_parts 拼接顺序 |
| 4 | action PFA q/kv 长度不同共用一个 tokens → q 越界读 | 审出（cross 变体修复） |
| 5 | zeros 按字节分配，两处传元素数 | tensor.rs 断言 |
| 6 | 宽 N × 非 16 倍 M aicore fault（812/820/828×N≥16384 全崩，832 全过） | M 阶梯 probe → MATMUL_M_ALIGN=16 无条件填充 |
| 7 | ada-norm 漏 shift 段（style=[w,3w]，cuda kernel: y=rms·(1+s[0:w])+s[w:2w]） | 读 normalization.cuh kernel 源码 |
| 8 | **短命 buffer 喂异步 op 后即 drop**（aclrtFree 不按 stream 排序）→ bench 连跑 sdma 0x217 | trace 定位 + 生命周期审计 → scratch 池 |
| 9 | **所有 op 中间输出同样 UAF** | 同上 → DeviceBuffer::drop 延迟释放（sync 后 flush） |

## 方法论沉淀

- **读回竞态**（同步 aclrtMemcpy 不等自定义 stream）：本轮所有"静默读错"皆源于此，probe 一律先 sync 再 d2h；生产 `host_f16_row` 补 sync
- **取证优先于试错**（用户指令）：设备日志抓 fault kernel_name + totalLen 参数、NzCache/trace 打印、读 cuda kernel 源码对语义——三者的信息密度远高于入口 bake-off
- **上下文依赖假象**：描述符越界（bug 1）是否踩到未映射页取决于分配邻接 → 表现为"tokens=828 过 layer0 崩 layer1、一切隔离复刻全过"的鬼影

## 环境增量

- `APXINF_ASCEND_TRACE=1`：executor/runtime 逐阶段 sync+打印（保留，排查利器）
- 新 examples：ascend_action_smoke（action 迷你复现器）、ascend_full_smoke、ascend_random_bench、matmul_m_probe（M 阶梯）

## 下一轮（E 阶段）

注册链：accelerator `Device::Ascend` 分派 → load（synthetic + safetensors）→ `Pi05AscendVlaRuntime` → apxinf-py 暴露 → 全深度 random bench + 真 checkpoint

---

## 追记：ACLGraph 捕获战役（同日深夜收官，28857f0）

**`ASCEND_GRAPH_CAPTURE_SMOKE_OK`：warmup → styles 预计算 → arena（1.76GB）→ RELAXED 捕获 → replay p50=88.1ms vs eager 305.1ms = 3.46×（depth 2/2/2），对拍 0.0068（fp16 噪声级）**

排查链（每步真机取证）：
1. 捕获窗口内 h2d（107030）逐个清除：ada-norm ones 行 / token 索引 / patch position 索引三处加缓存；styles 改窗外预计算（arena 下指针缓存必 miss——styles 必须复用窗外分配的张量）
2. aclnnMuls 的 host 标量在捕获下触发内部 h2d → euler 换张量常量乘（euler_consts 缓存，σ 步常数）
3. 窗口内残留 stream sync（denoise 的 mark closure + trace marks）→ 107027 且**取证工具的 sync 会扰动捕获态**（开 trace 反而跑得更远——教训：捕获调试的 mark 必须 print-only）
4. 终局根因（官方文档确认）：GLOBAL/THREAD_LOCAL 捕获模式**拒绝 aclnn 执行器内部的同步 memcpy**（标量/小参上传）→ RELAXED 模式解除，`begin_capture` 固定 RELAXED
5. arena：bump 分配 + owned=false 跳过延迟释放 + 调用方持底座 Arc（graph 烘焙地址随其存活）；depth 2/2/2 需 1.76GB（大 matmul workspace 单个 30-67MB）

**已知约束**：子图捕获上限 ~2000（建议 1800）→ 全深度 ~4600 op 需拆图接力。**性能验收线**见 roadmap——拆图 + 热点融合后 ≤378ms 进 M3，差 30%+ 与用户谈取舍。

---

## 追记二：性能阶段第一波（2026-09-19 凌晨，全深度 906.9 → 680.8ms）

1. **拆图前提证伪**：官方文档取证（MindSpore graph capture 文档原文）——"每捕获一张图消耗 1 个 stream，stream 总数上限 2000"是**图实例个数预算**（vLLM 按 batch 桶捕获几十图的场景），不是单图内节点数上限。vllm-ascend 分段的原因是 torch.compile 产物里 attention 需要运行时元数据更新。我们手工 ACL 流没有这些限制——**全深度单图捕获直接成功**（~4600 op、arena 8.3GB、对拍 0.0155、replay p50=906.9ms）。三段接力（vision/prefix/flow 各一图）也验证通过（链式对拍一致、接力开销 ~3ms），留在 smoke 里作 APXINF_SEGMENT_BENCH 分支
2. **scratch 池修复**：pop 借走无 push 归还 → 池从未命中。改"同尺寸共享一份永生"（单流顺序安全）→ mini arena 1.76GB→665MB、eager 305→187ms
3. **双边 msprof profiling（方法论落地：同一把尺子量两边）**：torch_npu 397ms = MatMul 124 + **TransData/Transpose 100（NZ 权重的设备侧搬运代价——我们 host 预转置 + stride 视图架构性避开）** + 拆开的 attention 36（我们 PFA 29 反超）。我们 = MatMul 213（prefix 大项 19-21.6 TFLOPS 已近峰值）+ Add 78 + **kernel 间隙 ~289ms**（~1900 kernel × 150µs）
4. **rope 平铺重写（-228ms）**：分桶定罪 rotate-half 的 axis=1 列 gather（language 单次 6.5ms = 带宽下限 49×）。`[rows,d]→[rows*2,d/2]` 视图上邻行交换 = axis=0 连续行 gather（µs 级）；cos 半维重复 + sin 符号折叠让表同视图复用。gathered 表/swap 索引按 (tokens,heads,offset) 常量缓存。GatherV2 族 126→3.9ms
5. **取证副产品**：vllm-ascend 310P 源码铁证——`npu_apply_rotary_pos_emb` 只支持 rotary_dim 64/128（注释原文），head_dim=256 无单算子 rope（AscendC 自研是终局方案，组合优化先行）
6. **下一波**：aclnnAddcmul（ada-norm mul+add 合一）+ aclnnGeGlu（geglu 单算子）→ 预计 ~500ms；之后 AscendC fused ada-norm 冲验收线（491ms = 378×1.3）
