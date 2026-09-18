# Handoff（2026-09-19 性能阶段第一波后，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**性能验收线**（全深度 bench：≤378ms 进 M3 / 差 30%+ 决策会谈）；**性能阶段战果与数据**（全深度单图捕获 906.9 → 680.8ms：scratch 池共享语义修复 + rope 平铺重写；msprof 双边分解：torch_npu 397ms 构成与我们 680.8ms 构成、kernel 间隙 ~289ms 是最大单项；**310P3 算子可用性判决**：Addcmul 可用但无收益、GeGlu 挂死不可用、npu_apply_rotary_pos_emb 只支持 64/128）；ACLGraph 关键事实（RELAXED 必须、窗口内 sync 禁忌、arena 机制、**拆图前提已证伪**——2000 上限是图实例数预算非单图节点上限，全深度单图直接成功）；msprof 双边 profiling 方法（torch_npu.profiler + ai_core_op_summary.db 的 ge_summary⋈task_time，duration 单位 ns；Rust 侧 msprof --application 挂 wrapper）；服务器三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；异步生命期纪律；子模块双仓两步提交（**push 用 fork remote 非 origin**）。丢弃：本波逐轮试错过程（roadmap + summary 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

APXinf 昇腾 NPU 性能阶段已到**用户决策点**（验收线判定触发，子模块 a7cdde5）：全深度单图 replay 679.8ms（对拍 0.019）vs torch_npu 378ms，验收线 491ms 不可达——空隙取证闭环：**81% 链内空隙是 MatMulV2 task 启动税（334µs × 970 次/链）**，换 matmul 入口三档同分判死，aclnn+ACLGraph 架构内封顶 ~590ms（qkv 融合后）。**等待用户从 roadmap ⭐⭐ 节三选项决策**：A 接受 ~590ms 进 M3（部署形态优先）/ B 310P3 定位验证芯片、性能目标移下一代硬件 / C 追 GE 原生 OM 图路线（torch_npu 零启动税的本质，工程量数周）。决策前不要自行开工新优化。

## ②附：AscendC kernel 工程速查（98aabfc 建成）

## ②附：AscendC kernel 工程速查（98aabfc 建成）

- 源码 `apxinf/crates/apxinf-ascend/ascendc/ada_rms_norm/`（kernel + host wrapper + cmake）；服务器编译目录 `/data/apxinf/ascendc/ada_rms_norm`（`bash run.sh -r npu`，产物 out/lib 需补拷 build/lib/libascendc_kernels_npu.so）
- Rust 接入 `apxinf-ascend/src/ada_rms.rs`（dlopen，libloading）+ `adaptive_rms` fused 分支（available() 自动切换，无 .so 时回落 aclnn 组合）
- probe：`examples/ada_rms_probe.rs`（ADA_RMS_DIAG=1 跑 tiling diag 模式 1-6）
- 310P3 判决：硬件 ReduceSum/RmsNorm arch 门控不可用（树归约是唯一路径）、GeGlu 挂死、Addcmul 无收益、aclrtlaunch 可进 RELAXED 捕获窗口、跨行流水线需 GetValue 双 pin

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_perf-wave.md（新文件：拆图证伪 + rope 平铺 + 双边 msprof + 算子判决）
