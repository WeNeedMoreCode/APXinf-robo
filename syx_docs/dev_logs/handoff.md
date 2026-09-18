# Handoff（2026-09-19 GE POC 收官，compact 用）

## 状态一句话

**GE 原生 OM POC 完成（子模块 28adf78 已推 fork）**：verify 对拍 0.002075 + bench 零调度税坐实（m=832：GE OM 4.745 vs aclnn+ACLGraph 5.812 ms/matmul，−18% = 23.5 TFLOPS；拟合 aclnn 5.86µs/row+555µs/task vs GE 4.71µs/row 固定税消失）。**C 路线收益成立，下一阶段 = 全量施工**（ascend_executor 的 prefix/flow 段改造成 GE 图构建 → OM 缓存 → aclmdlExecuteAsync 执行），外推全模型 ~370-390ms ≈ 验收线 378ms 附近。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**C 路线全量施工的全部知识**。POC 修复链四条硬知识（纯 operator 流构图删 AddNodeByOp；MatMulV2 infershape rank 门槛用经典 MatMul 绕过；build_options 必传 input_shape+input_format；Data 幽灵 input desc 0 决定 IO dtype 不设则插 Cast 全零）；GE 构图五要素 API 形态（OperatorFactory::CreateOperator / SetInput 双侧登记 / SetInputs 物化 / SetOutputs 按名 / aclgrphBuildModel+aclmdlLoadFromMem+aclmdlExecuteAsync）；bench 数据表与结论；C 路线施工图（roadmap 有）；rust 容器 GE 环境（python3-config 已修，LD_LIBRARY_PATH+PYTHONPATH 三件套）；服务器三件套与 tar+touch 纪律；子模块双仓两步提交。丢弃：POC 调试逐轮过程（编译报错、plog 逐次 grep——结论全部已归档 roadmap C 路线节）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线全量施工**（GE 原生 OM；POC 已完成 28adf78，goal 清）。第一动作：读 `syx_docs/plans/npu-port-roadmap.md` 的 C 路线节施工图，在 `apxinf-ascend` 新建 `ge_builder.rs`（或 C++ shim 扩展）——从 ascend_executor 的 prefix 段开始：matmul_b_t→MatMul(transpose_b=true)/add→Add/gelu→GeluV2/rms 组合/PFA→PromptFlashAttention 的算子映射，先用 mini 深度（2/2/2）单层 language layer 建图编译成 OM 对拍 eager（数值容差同现有 smoke），再全深度 bench 对比 680.8ms。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_ge-poc-complete.md（新文件：GE POC 五连修复收官 + 零税判定 + C 路线立项）
