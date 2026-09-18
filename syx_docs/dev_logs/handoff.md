# Handoff（2026-09-19 性能阶段第一波后，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**性能验收线**（全深度 bench：≤378ms 进 M3 / 差 30%+ 决策会谈）；**性能阶段战果与数据**（全深度单图捕获 906.9 → 680.8ms：scratch 池共享语义修复 + rope 平铺重写；msprof 双边分解：torch_npu 397ms 构成与我们 680.8ms 构成、kernel 间隙 ~289ms 是最大单项；**310P3 算子可用性判决**：Addcmul 可用但无收益、GeGlu 挂死不可用、npu_apply_rotary_pos_emb 只支持 64/128）；ACLGraph 关键事实（RELAXED 必须、窗口内 sync 禁忌、arena 机制、**拆图前提已证伪**——2000 上限是图实例数预算非单图节点上限，全深度单图直接成功）；msprof 双边 profiling 方法（torch_npu.profiler + ai_core_op_summary.db 的 ge_summary⋈task_time，duration 单位 ns；Rust 侧 msprof --application 挂 wrapper）；服务器三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；异步生命期纪律；子模块双仓两步提交（**push 用 fork remote 非 origin**）。丢弃：本波逐轮试错过程（roadmap + summary 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径**性能阶段终局取证：~290ms kernel 间空隙的来源**（全深度单图 replay 679.8ms vs torch_npu 378ms，验收线 491ms=378×1.3；子模块 98aabfc）。背景：三次实验（广播缓存/addcmul/AscendC fused ada-norm）证明图内 kernel 数不是成本——空隙（680 墙钟 - 392 kernel 执行）不随 op 数下降。第一动作：用 msprof 的 step_trace.db / hwts 时间线分析 kernel 间空隙形态（固定 per-task 开销还是集中在特定 op 类型），服务器上已有 /data/apxinf/rust_prof 的 PROF 数据（Rust 全深度捕获进程）。判定：**空隙可归因可消除 → 定向优化后跑全深度 checkpoint bench；不可消除 → 680ms 是此架构上限，按「性能验收线」与用户决策会谈**（选项见 roadmap ⭐节：接受略慢换部署形态 / 310P3 定位验证芯片性能目标移下一代）。注意：ada_rms kernel .so 在 /data/apxinf/ascendc/ada_rms_norm/out/lib（运行需 LD_LIBRARY_PATH 包含它）；APXINF_ADA_RMS_LIB 可覆盖路径。

## ②附：AscendC kernel 工程速查（98aabfc 建成）

- 源码 `apxinf/crates/apxinf-ascend/ascendc/ada_rms_norm/`（kernel + host wrapper + cmake）；服务器编译目录 `/data/apxinf/ascendc/ada_rms_norm`（`bash run.sh -r npu`，产物 out/lib 需补拷 build/lib/libascendc_kernels_npu.so）
- Rust 接入 `apxinf-ascend/src/ada_rms.rs`（dlopen，libloading）+ `adaptive_rms` fused 分支（available() 自动切换，无 .so 时回落 aclnn 组合）
- probe：`examples/ada_rms_probe.rs`（ADA_RMS_DIAG=1 跑 tiling diag 模式 1-6）
- 310P3 判决：硬件 ReduceSum/RmsNorm arch 门控不可用（树归约是唯一路径）、GeGlu 挂死、Addcmul 无收益、aclrtlaunch 可进 RELAXED 捕获窗口、跨行流水线需 GetValue 双 pin

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_perf-wave.md（新文件：拆图证伪 + rope 平铺 + 双边 msprof + 算子判决）
