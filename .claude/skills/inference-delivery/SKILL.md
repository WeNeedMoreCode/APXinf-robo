---
name: inference-delivery
description: |
  模型推理完整交付（设备中立）：迁移到加速器 + 推理性能优化。设备无关的优化核心
  （分侧计时、循环不变量外提、采样器系数预计算、常量缓存、等价性对拍）+ 可插拔的
  设备后端（当前为 NPU：torch_npu / torchair / OM 三条推理路径、图编译、ATC、
  跨板性能差异归因）。当用户说"迁移到 NPU"、"NPU 适配"、"cuda to npu"、"推理太慢"、
  "单步延迟高"、"优化推理性能"、"latency 优化"、"前后处理是瓶颈"、"闭环仿真慢"、
  "benchmark 掉速"、"NPU 报错"、"跨板性能差异"、"ONNX 导出失败"、
  "onnx export error"、"算子不支持"、"ONNX 输出不对"、"ONNX 和 PyTorch 结果不一致"、
  "ONNX 转 OM"时使用。
---

# 推理交付（迁移 + 优化，设备中立）

## 定位与边界

本 skill 管模型推理的完整交付：**跑得起来**（迁移/适配）+ **跑得快**（性能优化）。
两层结构：

- `optimization/` — **设备无关的优化核心**：任何设备（CPU/NPU/GPU）通用的定位与
  优化模式、对拍安全网
- `backends/<device>/` — **设备后端**（可插拔）：该设备特有的迁移路径、图编译、
  坑与性能特性。当前有 `npu/`；新增设备按同构放入（`backends/cuda/` 等）

## 路由

| 用户的问题形态 | 读 |
|---|---|
| 推理慢 / 单步延迟高 / 想优化性能（任何设备） | [optimization/README.md](optimization/README.md) |
| 迁移到 NPU / NPU 上跑不了 / NPU 报错 | [backends/npu/README.md](backends/npu/README.md) |
| NPU 图模式（torchair）/ OM 离线推理（ONNX→ATC） | backends/npu/README.md 的路径选择表分流 |
| 图化后端到端仍慢 / 图外小算子串 / 跨板（两块 NPU 板）性能差异归因 | [backends/npu/references/LAUNCH_OVERHEAD.md](backends/npu/references/LAUNCH_OVERHEAD.md) |
| PyTorch → ONNX 导出失败 / 算子不支持 / ONNX 与 PyTorch 输出不一致（也是 OM 前置） | [backends/npu/onnx-debug/README.md](backends/npu/onnx-debug/README.md) |
| 自定义 NPU 算子（AscendC） | [../AscendC-ops-dev/SKILL.md](../AscendC-ops-dev/SKILL.md)（独立 skill） |

**顺序原则**：还没跑通的项目先迁移（backends），跑通后再优化（optimization）——
同时面对两类问题会互相掩盖。性能定位永远从 optimization 的分侧计时开始，瓶颈
确认在设备侧（图/发射/搬运）再进 backends 深挖。

## 测量纪律（全设备通用，三条）

1. **对"没反应"先查测量，再造理论**：分步实验前确认被测代码真的生效（版本/分支/
   加载路径）；解释现象之前先怀疑测量。
2. **对账一律同口径**：固定样本集、固定并发数；小样本的"中位数的中位数"方差大，
   关键对账用大样本同口径。
3. **成本勿跨设备/板卡外推**：搬运、调度、执行的单价设备间差异大且方向未必符合
   直觉，两边的收益各自实测。

NPU 语境的展开版（含实测案例细节）见
[backends/npu/references/LAUNCH_OVERHEAD.md](backends/npu/references/LAUNCH_OVERHEAD.md)
的"测量纪律"节。
