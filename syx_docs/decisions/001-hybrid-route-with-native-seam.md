# 001: 混合路线 + 预留原生接口

日期：2026-09-16　状态：已接受

## 决策

昇腾 NPU 版采用混合路线：

1. **阶段一**：Python 层实现——`apxinf_robo` API 之下接 torch_npu（ModelZoo pi05_openpi 路线）作为首个 NPU 引擎实现，快速跑通端到端
2. **原生接口预留**：Python 层定义清晰的引擎抽象（infer 契约 / metadata 契约 / 后端选择机制），torch_npu 是第一个实现；将来的 Rust `apxinf-ascend`（ACL C API）后端以 PyO3 绑定接入同一抽象，不动上层
3. **阶段二起**：技术相异点一个一个过（GEMM、attention、融合 kernel、graph capture、精度），逐步用原生实现替换

## 备选与理由

- **纯路线 A（Rust 原生 ACL 先行）**：周期太长才有第一个可跑结果；且 aclnn 在 310P3 的算子覆盖未验证，风险前置
- **纯路线 B（只做兼容层）**：被否——性能上限锁死 torch_npu 水平，且用户明确要"推理引擎"而非 API 壳
- **选 C 的关键**：阶段一同时提供精度金标准和性能基线（ModelZoo 实测 378ms），为阶段二验收兜底

## 硬件决策（同日）

目标硬件锁定 **Ascend 310P3**。精度策略：BF16→FP16，FP8 不做（硬件无支持），INT8 W8A8 后置。
