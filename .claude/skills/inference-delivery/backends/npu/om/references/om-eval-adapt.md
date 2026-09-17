---
name: om-eval-adapt
description: |
  适配评估脚本从 CUDA/PTH 路径到 OM（昇腾离线推理）路径。
  当用户说"适配评估脚本"、"加 OM 路径"、"evaluation 加 om"、"is_om_model 分支"时使用。
  也适用于审查已有 OM 适配代码的正确性。
---

# OM 评估路径适配检查清单

将评估脚本从 PTH（PyTorch + CUDA/NPU）路径适配到 OM（昇腾离线模型推理）路径时，按以下清单逐项检查。

## 核心原则

**OM 路径的数据流是固定的：**

```
numpy (OM session 输入)
  → OM session 推理
  → numpy (OM session 输出)
  → CPU torch.tensor (聚合/排序/四元数运算)
  → numpy (保存/精度评估)
```

**关键：OM 路径外部代码尽量用 CPU。** OM session 内部自行管理 NPU（CPU numpy → NPU 计算 → CPU numpy）。外部代码用 NPU 会造成数据搬运开销，且清理时容易 context 混乱导致 "stream not in current context" 报错甚至 segfault。如果确实需要用 NPU，要在开头和结尾管理好 AscendCL context 生命周期。

---

## 检查清单

### 1. 设备放置 (Device Placement)

- [ ] **OM 路径的聚合操作用 CPU tensor**
  ```python
  # 正确：OM 路径转 CPU tensor
  score_pred_results = torch.from_numpy(score_pred_results)  # 默认 CPU

  # 错误：OM 路径不需要 .to(cfg.device)
  score_pred_results = torch.from_numpy(score_pred_results).to(cfg.device)  # ❌
  ```

- [ ] **`torch.zeros` / `torch.zeros_like` 等初始化**
  ```python
  # 正确：按路径区分
  device = cfg.device if not is_om_model else 'cpu'
  pose = torch.zeros(length, pose_dim, device=device)
  ```

- [ ] **`prev_pose` 初始化**
  ```python
  # 正确：OM 路径用 CPU
  prev_pose = torch.zeros_like(
      prev_pose,
      device=cfg.device if not is_om_model else 'cpu'
  )
  ```

### 2. 数据类型 (Data Types)

- [ ] **OM 路径的中间数据用 numpy**
  - OM session 的输入输出是 numpy，如果后续计算链路（如 ODE 求解器）也是 numpy 原生的，就不要中间转 tensor 再转回来
  - 确认完整调用链后再决定数据类型，不要想当然
  - numpy 用 `.reshape()` 而非 `.view()`（numpy 没有 view）

- [ ] **不要在 OM 路径保留不必要的 tensor 转换**
  ```python
  # 错误：OM 路径不需要 tensor
  pts_feat_repeated = torch.from_numpy(pts_feat).view(...)  # ❌
  # 正确：直接用 numpy
  pts_feat_repeated = pts_feat.reshape(...)  # ✅
  ```

### 3. Import 位置

- [ ] **`torch_npu` 只在 PTH 路径导入**
  ```python
  # 正确：放在 if not is_om_model: 分支内
  if not is_om_model:
      import torch_npu
      ...
  ```

- [ ] **OM wrapper 的 import 不依赖 torch_npu**

### 4. DataLoader 与批次处理

- [ ] **DataLoader collate 会把 bool 变成 tensor**
  - `__getitem__` 返回的 Python bool 经过 DataLoader collate 后会变成 `tensor([False, False, True, ...])`
  - 检查时必须用 `.any()` / `.all()` / `.item()`，不能直接 `if batch['flag']`，否则报 "Boolean value of Tensor is ambiguous"

- [ ] **跳过异常数据不能导致主循环提前退出**
  - 如果在主循环中跳过某帧/某 batch 后集合变空，需要区分"全部处理完"和"这轮全部被跳过"
  - 跳过后检查是否还有未处理的数据，有则 `continue` 而非 `break`

---

## OM 接回核心规则

### 输出保真

不要伪造会参与后续计算的模型输出。若存在未导出或占位输出，必须证明它不参与后续计算；否则接回阶段不算完成。

### Context 隔离

OM session 与 `torch_npu` / 自定义 NPU kernel 同进程混合运行时，必须管理 runtime context，否则会出现 `LaunchAscendKernel ret 107003`、`stream not in current ctx`、自定义算子输出全错等问题。

关键约束（踩坑总结）：

- **save 必须在 `torch.npu.set_device()` 之后**：`import torch_npu` 是 lazy init，不调 `set_device` 直接 `get_context` 拿到的是 null。
- **save 必须在第一个 `InferSession(...)` 之前**：第一个 InferSession 创建后 current context 就被改变了，再 get 拿到的不是 PTA 的。
- **restore 必须在每次 `infer()` 之后**：每次 infer 都会切走 context，只 restore 一次不够。

完整模式、OMRunner 封装、自定义 NPU 算子场景、排查 checklist → Read [CONTEXT_MANAGEMENT.md](CONTEXT_MANAGEMENT.md)。

最小示例：

```python
import acl
import torch_npu
from ais_bench.infer.interface import InferSession

torch.npu.set_device("npu:0")              # 1. 强制创建 PTA context
pta_ctx, _ = acl.rt.get_context()          # 2. 在任何 InferSession 之前 save
session = InferSession(0, model_path)      # 3. 创建 InferSession

# 推理循环
result = session.infer([inputs])
acl.rt.set_context(pta_ctx)                # 4. 每次 infer 之后 restore
tensor = torch.from_numpy(result).to("npu:0")  # torch_npu op 能正常跑
```

OM 输出回到 `torch_npu` 流程前，先恢复 PTA context，再构造目标 device tensor。

### 接回原则

- 优先替换原始代码中的模型推理部分，尽量不改原始前处理、后处理、状态管理和调度逻辑
- 桥接代码只允许做输入整理、输出回填、dtype/shape/device 对齐、runtime context 恢复和调度接线
- 不允许顺手改业务语义

---

## 源码分析速查命令

### 查真实推理入口

优先查用户真正调用的入口，而不是只看 `model.forward()`：

```bash
rg -n "main\(|infer|predict|serve|session|start|update|finalize|track|pipeline|runner"
```

如果是服务式或多阶段工程，再看：

```bash
rg -n "grpc|fastapi|flask|stream|chunk|request|response|worker|handler"
```

### 查状态对象和跨步缓存

重点看跨帧、跨页、跨 token、跨 chunk 的缓存和会话对象：

```bash
rg -n "state|cache|memory|history|session|context|kv_cache|tracker|buffer|prev|past"
```

要确认：
- 状态是在 Python 控制面维护，还是在模块内部维护
- 哪些状态会进入候选子图
- 哪些状态只参与调度或聚合，应保留原始实现

### 查候选子图输入来源

```bash
rg -n "backbone|encoder|decoder|head|fusion|prompt|embed|memory|sampler|neck"
rg -n "\.forward\(|model\(|module\(|predictor\("
```

对候选子图至少要确认：
- 输入清单、输入来源、输入含义
- 可选输入
- 进入子图前已经做过哪些处理

### 查进入子图前的处理

```bash
rg -n "resize|interpolate|pad|padding|bucket|crop|normalize|tokenize|embedding|mask|bbox|point|prompt"
```

---

## OM 推理与精度比对

### ATC 导出 → 推理 mode 映射

| ATC 导出侧 | 推理 mode |
| --- | --- |
| `--dynamic_batch_size` | `dymbatch` |
| `--dynamic_image_size` | `dymhw` |
| `--dynamic_dims` | `dymdims` |
| 含 `-1` 的 `--input_shape`，无 `dynamic_*` | `dymshape` |

推理时 mode 必须与 ATC 导出策略一致。

### 精度比对原则

- 优先用真实业务输入，不要长期依赖随机输入
- 多输入模型保证每个输入来自同一条真实样本
- 先看契约（数量/shape/dtype/layout/mode），再看数值
- 子图级通过不等价于最终业务精度结论
- 检测/排序敏感任务不能只凭子图级对比下结论

### 端到端验证指标

以原始实现在相同输入上的输出为基准：

- **检测/分割**：mAP 下降 < 1pp，mIoU 下降 < 0.5pp
- **分类/检索**：accuracy 下降 < 0.5pp
- **OCR/语音/生成**：WER/CER/BLEU 下降 < 1pp
- **无法量化**：至少 3 组代表性输入做定性对比

---

## 性能验证清单

- 必须实测，不要仅靠子图级推理时间推算端到端性能
- 子图级 OM 推理时间与端到端业务延迟是两回事
- 接回后要测完整业务链路的吞吐和延迟
- 若同一进程内多个 `.om` session，注意 context 切换开销

