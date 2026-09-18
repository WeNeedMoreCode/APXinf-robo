# Handoff（2026-09-18 捕获收官更新，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**性能验收线**（拆图捕获 + rope/ada-norm 融合后全深度 bench：≤378ms 进 M3 / 差 30%+ 决策会谈）；ACLGraph 三段式全绿的关键事实（RELAXED 模式必须——GLOBAL/THREAD_LOCAL 拒绝 aclnn 内部同步 memcpy 107030；捕获窗口内任何 stream sync 扰动捕获态 107027——mark 全 print-only；arena 模式：enter/exit/clear + owned=false 跳过 free，调用方持底座 Arc；子图上限 ~2000/建议 1800）；服务器三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；异步生命期纪律（scratch 池 + 延迟释放）；子模块双仓两步提交。丢弃：捕获调试逐轮过程（roadmap + commit 28857f0 信息已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径**性能阶段第一步：全深度拆图捕获**（ACLGraph 三段式已在 depth 2/2/2 跑通：replay p50=88.1ms vs eager 305.1ms = 3.46×、对拍 0.0068；子模块 28857f0）。第一动作：设计拆图方案——读 roadmap「优化待办」与 vllm-ascend ACL Graph 设计文档的多图接力模式，决定按 transformer 层还是按 flow step 分段（全深度 ~4600 op vs 子图上限 1800），在 ascend_runtime.rs 加分段捕获 API（每段独立 arena + graph，段间输出张量传递），用 ascend_graph_capture_smoke 改全深度验证。完成后接热点融合（rope/ada-norm），最终按「性能验收线」判定（≤378ms 进 M3 / 差 30%+ 找用户决策）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-18_c-to-f-stages.md（续用，追加捕获战役段）
