# Handoff（2026-09-19 性能阶段第一波后，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**性能验收线**（全深度 bench：≤378ms 进 M3 / 差 30%+ 决策会谈）；**性能阶段战果与数据**（全深度单图捕获 906.9 → 680.8ms：scratch 池共享语义修复 + rope 平铺重写；msprof 双边分解：torch_npu 397ms 构成与我们 680.8ms 构成、kernel 间隙 ~289ms 是最大单项；**310P3 算子可用性判决**：Addcmul 可用但无收益、GeGlu 挂死不可用、npu_apply_rotary_pos_emb 只支持 64/128）；ACLGraph 关键事实（RELAXED 必须、窗口内 sync 禁忌、arena 机制、**拆图前提已证伪**——2000 上限是图实例数预算非单图节点上限，全深度单图直接成功）；msprof 双边 profiling 方法（torch_npu.profiler + ai_core_op_summary.db 的 ge_summary⋈task_time，duration 单位 ns；Rust 侧 msprof --application 挂 wrapper）；服务器三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；异步生命期纪律；子模块双仓两步提交（**push 用 fork remote 非 origin**）。丢弃：本波逐轮试错过程（roadmap + summary 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径**性能阶段：AscendC fused ada-norm**（当前全深度单图捕获 replay 681.6ms vs torch_npu 378ms；验收线 491ms=378×1.3。子模块 494cb1b）。第一动作：调 AscendC-ops-dev skill，写 fused kernel `y = rms(x)·(1+s0)+s1`（读 x 一次 + style 行按行索引免广播 + 写 y 一次），替代当前 add_rms_norm(x,zeros)+mul+add 三 kernel 组合（~400 次调用/推理，msprof：Add 78ms + Mul 14ms + 各自 150µs kernel 间隙）。完成后跑 ascend_graph_capture_smoke（APXINF_FULL_DEPTH=1）对比 681.6ms 基线与对拍（当前 0.025）。若 fused ada-norm 落地后仍 >491ms：按「性能验收线」与用户决策会谈（选项见 roadmap）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_perf-wave.md（新文件：拆图证伪 + rope 平铺 + 双边 msprof + 算子判决）
