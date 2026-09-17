# ONNX 导出调试（PyTorch → ONNX，om 路径的前置环节）

> inference-delivery NPU 后端的 ONNX 阶段：导出失败调试、逐层剥离定位、wrapper 绕过。
> 产出 ONNX 之后的 ATC 编译/参数在 [../om/README.md](../om/README.md)；
> CANN 环境速查在 [../references/cann_env.md](../references/cann_env.md)。

## 总体思路

ONNX 导出失败的调试是**逐层剥离**的过程：不要一上来就试图修复整个模型，而是从最小的组件开始，逐步定位问题。

```
完整模型导出失败
  → 拆分子模块，逐个导出
  → 找到具体失败的算子/层
  → 写最小复现脚本
  → 修复或写 wrapper 绕过
  → 验证修复后子模块输出一致
  → 重新组装完整模型导出
```

---

## 步骤 1：隔离失败位置

### 1.1 从错误信息定位

ONNX 导出报错通常会指出具体算子：
```
RuntimeError: Failed to export an ONNX attribute 'onnx::Gather'
```

但错误位置不一定准确（图优化可能改变节点顺序），需要进一步确认。

### 1.2 逐模块拆分导出

将模型拆成独立子模块，分别导出：

```python
# 例：PointNet2 的结构
# PointNet2SAFlow → 包含多个 PointNet2SAModule
# PointNet2SAModule → 包含 SharedMLP + Ball Query + Grouping

# 先试导出最底层的 SharedMLP
class SharedMLPWrapper(nn.Module):
    def __init__(self, mlp):
        super().__init__()
        self.mlp = mlp

    def forward(self, x):
        return self.mlp(x)
```

### 1.3 创建最小复现

为每个子模块写独立测试脚本：

```python
import torch
import torch.nn as nn

# 最小模型定义
class TestModule(nn.Module):
    def __init__(self):
        super().__init__()
        # 只包含疑似有问题的操作
        ...

    def forward(self, x):
        # 只执行疑似有问题的计算
        ...
        return result

model = TestModule()
dummy = torch.randn(1, 16, 3)

torch.onnx.export(model, (dummy,), "test.onnx",
                  opset_version=17, verbose=True)
```

**脚本命名建议**：`test_<组件名>_onnx.py`，放在调试记录目录中。

---

## 步骤 2：对比 PyTorch vs ONNX 输出

导出成功不代表正确。用 ONNX Runtime 验证数值一致性：

```python
import onnxruntime as ort
import numpy as np

# PyTorch 推理
model.eval()
with torch.no_grad():
    pt_output = model(dummy_input).numpy()

# ONNX Runtime 推理
sess = ort.InferenceSession("test.onnx")
ort_output = sess.run(None, {
    sess.get_inputs()[0].name: dummy_input.numpy()
})[0]

# 对比
max_diff = np.max(np.abs(pt_output - ort_output))
mean_diff = np.mean(np.abs(pt_output - ort_output))
print(f"max_diff: {max_diff}, mean_diff: {mean_diff}")

# 允许的误差范围（浮点精度）
assert max_diff < 1e-5, f"数值差异过大: {max_diff}"
```

---

## 步骤 3：常见问题与解决方案

### 3.1 不支持的算子

**症状**：`Unsupported ONNX opset version` 或 `Cannot export operator XXX`

**解法**：
- 升高 `opset_version`（推荐 17+）
- 如果是自定义 CUDA 算子（如 PointNet2 的 FPS、Ball Query），需要用纯 PyTorch 重写
- 对于复杂的内置算子，用更基本的算子组合替代

### 3.2 `.copy_()` 操作（常见但报错信息误导）

**报错信息**：
```
RuntimeError: Argument passed to at() was not in the map.
at _C._jit_pass_onnx_remove_inplace_ops_for_onnx

# 或更直接的：
UnsupportedOperatorError: Exporting the operator 'aten::copy'
```

**根因**：`tensor.copy_(other)` 产生 `aten::copy` 算子，ONNX 不支持。

**典型场景**：PyTorch wrapper 函数中为了传出结果而使用 `.copy_()`：
```python
# 问题代码
def some_wrapper(input_tensor, output_buffer):
    result = internal_fn(input_tensor)
    output_buffer.copy_(result)  # ← aten::copy，ONNX 不支持
    return 1
```

**解法**：改为直接返回结果，不要用 `.copy_()` 写入预分配 buffer：
```python
# 修复后
def some_wrapper(input_tensor):
    result = internal_fn(input_tensor)
    return result  # 直接返回
```

> **经验教训**：这个报错信息指向 "inplace ops"，容易让人误以为是 `ReLU(inplace=True)` 之类的问题。但经过完整排查，`ReLU(inplace=True)`、`y -= 0.5` 等常见 inplace 操作在单独测试中都能正常导出。真正的问题是 `.copy_()`。排查时不要被报错信息误导。

### 3.3 ODE / 动态循环无法导出

**症状**：包含 ODE 求解器（如 `scipy.integrate.solve_ivp`）的模型无法整体导出为 ONNX

**原因**：ODE 求解器的循环次数是动态的（由求解器内部根据误差容忍度决定），不是固定常量。ONNX trace 无法处理这种运行时才确定循环次数的结构。即使将 ODE 与模型解耦，单独尝试导出包含 ODE 循环的整体仍然失败。

**解法**：将模型拆分为"单步网络"和"外部循环"两部分：
- **单步网络**（如 ScoreNet 的单次 forward）：导出为 ONNX
- **外部循环**（ODE 求解器）：留在 Python 中，每步调用 ONNX/OM 推理

```python
# 原始：ScoreNet + ODE 耦合，无法导出
class PoseScoreNet:
    def forward(self, data, mode='ode_sample'):
        # 内部循环调用 solve_ivp → 每步调用自身 forward → 动态循环
        ...

# 拆分后：ScoreNet 只做单次推理，ODE 循环在外部
# ScoreNetWrapper → 导出 ONNX
# ODESamplerExternal → Python 中用 scipy solve_ivp，每步调用 OM session
```

---

## 步骤 4：ONNX → OM 转换问题

### 4.1 batch_size 不匹配

**报错信息**：
```
[ERROR] check i:0 name:roi_rgb in size:2408448 needsize:4816896 not match
```

**根因**：OM 模型的 batch_size 在 ATC 转换时固定，运行时不能改变。但评估时 DataLoader 的 batch_size 是动态的（如 `batch_size=dataset.num_valid`，每个视频不同），实际数据 batch 可能小于 OM 模型期望的 batch。

另外，ONNX 导出时的 batch_size 必须与 ATC 转换时一致。PointNet2 ONNX 虽然设了 `dynamic_axes`，但内部 Reshape 节点的 target shape 是导出时根据 batch_size 固化的常量，ATC 转换用不同 batch_size 会报错：
```
[Node:/SA_modules.0/Reshape_4] Check shape failed
```

**常见解法**（按优先级）：

1. **推理时严格对齐 OM batch_size**：丢掉最后一个 batch（size 比前面少），或调整数据组织方式确保每次推理的 batch_size 恰好等于 OM 模型的 batch_size
2. **ATC 转换时用 dynamic_batch_size**：OM 支持多个 batch_size 值。但复杂模型可能导致导出模型过大或内存超限
3. **Padding**：对输入 padding 到 OM batch_size 的整数倍，推理后截取有效部分。注意如果模型中有 LayerNorm，padding 可能引入精度问题，需要实测验证

---

## 步骤 5：验证与回归

修复后，确保：
1. 单个子模块的 ONNX 输出与 PyTorch 输出数值一致（diff < 1e-5）
2. 完整模型导出无报错
3. 完整模型 ONNX 推理输出与 PyTorch 推理输出一致
4. （如有）OM 转换成功，OM 推理结果正确

---

## 调试脚本模板

```python
"""
调试 ONNX 导出问题的最小复现脚本。
用法：python test_<组件>_onnx.py
"""
import torch
import torch.nn as nn
import numpy as np

class TestModel(nn.Module):
    def __init__(self):
        super().__init__()
        # TODO: 填入疑似有问题的模块
        pass

    def forward(self, x):
        # TODO: 填入疑似有问题的前向传播
        return x

def main():
    device = 'cpu'
    model = TestModel().to(device).eval()

    # 构造输入
    dummy_input = torch.randn(1, 16, 3, device=device)

    # 1. PyTorch 推理
    with torch.no_grad():
        pt_output = model(dummy_input)

    # 2. 导出 ONNX
    onnx_path = "test_output.onnx"
    torch.onnx.export(
        model, (dummy_input,), onnx_path,
        opset_version=17,
        input_names=['input'],
        output_names=['output'],
        verbose=True
    )
    print(f"Exported to {onnx_path}")

    # 3. ONNX Runtime 验证
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path)
    ort_output = sess.run(None, {
        'input': dummy_input.numpy()
    })[0]

    # 4. 对比
    diff = np.max(np.abs(pt_output.numpy() - ort_output))
    print(f"PyTorch output shape: {pt_output.shape}")
    print(f"ONNX Runtime output shape: {ort_output.shape}")
    print(f"Max difference: {diff}")
    print(f"Result: {'PASS' if diff < 1e-5 else 'FAIL'}")

if __name__ == '__main__':
    main()
```

---

## 步骤 6：ONNX 优化与 ATC 常见陷阱

### 6.1 优化产物可能改写输入签名

ONNX 优化步骤（onnxslim / auto_optimizer）可能改变图签名：
- 可选输入被折叠
- 某些输出被清理或改名
- graph output 仍保留动态符号
- 输入已固定，但输出 shape 标注没有同步固定

优化后重新检查输入输出数量、名称、shape：

```python
import onnx
model = onnx.load('model.onnx')
for inp in model.graph.input:
    print(f'Input: {inp.name}')
for out in model.graph.output:
    print(f'Output: {out.name}')
```

### 6.2 onnxslim 产物 graph output 可能悬空

某些多输出模型，原图是 `vision_features -> Identity -> backbone_fpn_2`。onnxslim 后图里只剩 `backbone_fpn_2`，但 `graph.output` 还保留 `vision_features`。这不是"动态 shape 没推出来"，而是 graph output 已经失效。应先修复输出别名或剔除该候选。

### 6.3 ATC 失败后不要直接放弃

至少先完成以下检查：

1. 输入形态是否选错
2. ONNX 输入输出契约是否被优化步骤改写
3. graph output 是否残留不合理动态 shape
4. 是否是局部实现不友好（而不是整张图都不能转）
5. 当前部署边界是否过大或过碎

### 6.4 导出时使用 legacy exporter

`torch.onnx.export` 如果支持 `dynamo` 参数，必须默认设 `dynamo=False`，避免新 exporter 引入 `onnxscript` 依赖或改变图行为。只有在 legacy exporter 无法覆盖且已明确记录新增依赖时，才开启 dynamo。

---

## 步骤 7：精度验证标准

### 7.1 子图级精度门控（ONNX vs OM）

先做契约门控（输入输出数量、shape、dtype 是否一致），再看数值门控：

| 指标 | 通过 | 需复查 | 不通过 |
| --- | --- | --- | --- |
| cosine_similarity | >= 0.9999 | [0.999, 0.9999) | < 0.999 |
| max_abs_diff (FP32) | < 1e-4 | [1e-4, 1e-3) | >= 1e-3 |
| max_abs_diff (FP16) | < 1e-2 | [1e-2, 5e-2) | >= 5e-2 |

- "需复查"：可继续推进但端到端验证中重点关注
- "不通过"且契约不一致：必须回修契约
- "不通过"但契约一致：按偏差诊断流程处理

### 7.2 端到端验证指标

以原始实现在相同输入上的输出为基准：

- **检测/分割**：mAP 下降 < 1pp，mIoU 下降 < 0.5pp
- **分类/检索**：accuracy 下降 < 0.5pp
- **OCR/语音/生成**：WER/CER/BLEU 下降 < 1pp
- **无法量化**：至少 3 组代表性输入做定性对比

### 7.3 子图数值不通过后的诊断流程

1. 复核比较条件：同一输入、同一预处理、同一 dtype/layout、同一推理 mode/profile、同一 ONNX 候选
2. 分析偏差来源：FP16 舍入、并行归约顺序、低置信度输出、NMS/top-K 排序扰动、padding/mask 区域差异
3. 若偏差只影响低置信度/未消费/被后处理丢弃的结果，可先接回做端到端验证
4. 若偏差影响高置信度主结果/类别/状态缓存，必须先修复

### 7.4 ATC 导出参数 → 推理 mode 映射

| ATC 导出侧 | 推理 mode |
| --- | --- |
| `--dynamic_batch_size` | `dymbatch` |
| `--dynamic_image_size` | `dymhw` |
| `--dynamic_dims` | `dymdims` |
| 仅含 `-1` 的 `--input_shape`，无 `dynamic_*` | `dymshape` |

推理时 mode 必须与 ATC 导出策略一致。

### 7.5 精度比对原则

- 优先用真实业务输入，不要长期依赖随机输入
- 多输入模型保证每个输入来自同一条真实样本
- 先看契约（数量/shape/dtype/layout/mode），再看数值
- 子图级通过不等价于最终业务精度结论
- 检测/排序敏感任务不能只凭子图级对比下结论

---

## 步骤 8：常见偏差来源清单

ONNX 与 OM 输出不一致时的常见原因：

1. 输入预处理与原始代码不一致
2. 输入 dtype 或 layout 不一致
3. 不同候选 ONNX 的输入输出签名不一致
4. graph output shape 标注有误
5. 优化候选无效（graph output 悬空或 ORT 无法加载）
6. 接回主链时张量顺序或含义接错
7. OM 推理 mode 与 ATC 导出策略不一致
8. FP16 / 混合精度、并行归约或算子融合导致低位误差
9. NMS、top-K、argmax、排序或分数接近阈值导致输出顺序扰动
10. padding、mask、cache 尾部或未消费辅助输出存在差异
11. 量化、clip、round、resize、interpolate 等数值敏感算子策略不同

---

## ATC 参数与动态策略速查

详见 [../om/references/PARAMETERS.md](../om/references/PARAMETERS.md) 和 [../om/references/ATC_DYNAMIC_STRATEGIES.md](../om/references/ATC_DYNAMIC_STRATEGIES.md)。
