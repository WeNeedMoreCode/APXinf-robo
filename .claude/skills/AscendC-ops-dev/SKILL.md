---
name: AscendC-ops-dev
description: |
  AscendC 算子开发实战知识库（基于 310P3 实测）。涵盖 API 可靠性、多核 dispatch、
  跨核同步、buffer 管理、kernel launch、调试方法论等。
  触发关键词："AscendC"、"算子开发"、"多核 kernel"、"kernel launch"、"310P3"、
  "GetValue"、"DataCopy"、"SyncAll"、"TPipe"、"TBuf"、"GM"、"UB"、"kernellaunch"、
  "static OM"、"ATC"、"OM 多核崩"、"DCE"、"死代码优化"、"make binary package"、"hwts timeout"、"workspace 清零"、"te_<op>"、
  "torch.library"、"TORCH_LIBRARY"、"register_fake"、"NpuExtension"、
  "TorchAir 自定义算子注册"、"torch.compile 自定义算子"、"undefined symbol torchCheckFail"、
  以及任何涉及华为昇腾 NPU 上用 AscendC 写自定义算子的场景。
  在以下场景也应触发：用户在写或调试 AscendC kernel 代码、遇到 kernel launch 107002
  错误、多核结果不正确、GetValue/DataCopy 行为异常、跨核同步问题、
  已有 AscendC kernel 要接入 torch.compile/TorchAir 图模式（ctypes launch 不能被 dynamo trace）。
---

# AscendC 算子开发实战知识库

基于 Ascend 310P3 (AscendC C78) 多核算子开发的实测经验（FPS、GroupPoints）。所有结论均有实验数据支撑。

## 路由：你要做什么？

| 场景 | 读取 |
|------|------|
| **写 kernel**（项目搭建、工作流、模式选择、Gather/Scatter 策略） | [kernel-dev/README.md](kernel-dev/README.md) |
| **查 API 可靠性**（GetValue/DataCopy/SyncAll/pipe_barrier 哪些可靠、正确用法） | [kernel-dev/api_reliability.md](kernel-dev/api_reliability.md) |
| **多核 dispatch 或跨核同步**（ACLRT_LAUNCH_KERNEL、SyncAll、GroupBarrier） | [kernel-dev/multicore.md](kernel-dev/multicore.md) |
| **Buffer 管理**（TBuf/TQue、DMA 复用陷阱、对齐、UB 容量） | [kernel-dev/buffers.md](kernel-dev/buffers.md) |
| **Host wrapper / 动态 Shape Tiling / 调试** | [kernel-dev/host_and_debug.md](kernel-dev/host_and_debug.md) |
| **已有 kernel 接入 torch.compile/TorchAir**（ctypes launch 报 dynamic control flow / undefined symbol） | [registration/README.md](registration/README.md) |
| **已有 kernel 要 fullgraph=True 入 GE 图**（不需要 graph break，≥ CANN 9.0） | [registration/ge_fullgraph.md](registration/ge_fullgraph.md) |
| **static OM 部署 / OM 多核 SyncAll 崩 / DCE / make package** | [registration/ge_fullgraph.md](registration/ge_fullgraph.md) 坑 14-16 + [kernel-dev/multicore.md](kernel-dev/multicore.md) OM 段 |
| **排查未知行为 / 错误码** | [shared/troubleshooting.md](shared/troubleshooting.md) |

## 完整开发范例（按算子类型）

| 类型 | 文件 |
|------|------|
| 串行依赖型（如 FPS，每步依赖上一步，需 SyncAll） | [kernel-dev/examples/serial_dependency_example.md](kernel-dev/examples/serial_dependency_example.md) |
| Embarrassingly Parallel（如 GroupPoints，无跨核同步） | [kernel-dev/examples/embarrassingly_parallel_example.md](kernel-dev/examples/embarrassingly_parallel_example.md) |
| 向量化循环型（如 NMS，多核各跑串行循环 + 算法优化） | [kernel-dev/examples/nms_vectorized_loop_example.md](kernel-dev/examples/nms_vectorized_loop_example.md) |

## 核心原则

**在 AscendC 里，你看到的不一定是你得到的。** API 签名看起来合理不代表行为正确。GetValue(GlobalTensor) 有返回值但不一定返回正确的值。pipe_barrier(PIPE_V) 不会等 DMA。SyncAll() 无参版在 310P3 上无效。这些坑只有实测才能发现，文档不会告诉你。

详细的 API 可靠性矩阵和正确用法见 [kernel-dev/api_reliability.md](kernel-dev/api_reliability.md)。
