# Handoff（2026-09-19 C 路线施工前夜，compact 用）

## 状态一句话

**GE 原生 OM POC 完成（28adf78/f5d12c2 双仓已推）**：零调度税坐实（m=832 GE OM 4.745 vs aclnn+ACLGraph 5.812 ms/matmul，−18%）。下一步 = **C 路线全量施工**（三段式计划已定稿在 roadmap C 路线节：C1 垫脚石→C2 三段 OM 全量→C3 验收线判定）。当前全模型 679.8ms（ACLGraph），GE 化外推 ~370-390ms ≈ 验收线 378ms。新 skill `ge-offline-om` 已沉淀 POC 全部知识（构图五要素/陷阱表/取证工具箱 + matmul-poc-case 快照）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**C 路线施工计划与 POC 硬知识的索引**（详细计划在 roadmap C 路线节 C1/C2/C3 三段式——C1=ge_builder 泛化 FFI+transpose_x2 权重布局实验+单层 GE 化双路径对拍；C2=三段 OM+缓存落盘+全深度 bench；C3=验收线判定+M3）；**POC 五连修复**（纯 operator 流构图删 AddNodeByOp / MatMulV2 rank 门槛用经典 MatMul 绕过 / build_options 必传 input_shape+input_format / Data 幽灵 input desc 0 决定 IO dtype / python3-config 缺失杀 GE init——细节全部在 ge-offline-om skill，不必重复保留）；**ge_builder FFI 设计面**（add_data/add_op/set_desc/set_attr*/set_input/build/run/save/load，模型定义留 Rust）；预置风险（PFA 的 GE IR 注册名待验证、大图编译时长未知、ada-norm 先内置组合、ACLGraph 保留回退）；服务器三件套与 tar+touch 纪律；子模块双仓两步提交（push 用 fork）。丢弃：本轮 POC 调试逐轮过程（已归档 roadmap + skill case）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线全量施工 C1**（计划见 `syx_docs/plans/npu-port-roadmap.md` C 路线节；GE 构图知识在 ge-offline-om skill，先读 SKILL.md）。第一动作按 C1 顺序：① 把 `apxinf/crates/apxinf-ascend/ascendc/ge_poc/` 的 shim 泛化为 `ge_builder` 通用构图 FFI（add_data/add_op/set_desc/set_attr/set_input/build/run/save/load，C++ 薄层，Rust 侧后续 dlopen）；② 权重布局单点实验：MatMul transpose_x2=true + [n,k] desc（对齐 NzCache 转置管线）对拍+bench；③ 第 0 个风险实验：PFA 的 GE IR 注册名（OperatorFactory 试 PromptFlashAttention 系列名）。同步服务器（rust 容器编译记得 touch .cpp；GE 运行环境：LD_LIBRARY_PATH=build+CANN lib64、PYTHONPATH=CANN site-packages 追加、ASCEND_RT_VISIBLE_DEVICES=5——python3-config 已修）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_ge-poc-complete-and-c-route-plan.md（新文件：GE POC 五连修复收官 + 零税判定 + C 路线三段式施工计划 + ge-offline-om skill 沉淀）
