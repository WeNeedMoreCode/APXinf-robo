# 纯 torch_npu 路径踩坑清单

基于 GenPose2 项目实际踩过的坑。每个条目都是真实遇到并花费大量时间排查的问题。

---

## 进一步阅读：运行时陷阱

下面这些问题按章节独立整理在 [`references/runtime_pitfalls.md`](references/runtime_pitfalls.md)：

| 用户问题 | 跳转章节 |
|---|---|
| 想让 CPU 数据准备 hide 到 NPU 推理时间内 | 第 1 章 |
| `time.time()` 测 NPU 操作只显示几 ms，但实际几百 ms | 第 2 章 |
| 派发函数等几百 ms 才返回（应该几 ms） | 第 3 章 |
| 流水线优化没生效，代码里没 synchronize() | 第 3 章 |
| **在 310P1/RC 类设备（davinci-mini 等）上算子崩 / randn 崩 / floordiv 算错** | 第 10 章 + [`references/rc_device_toolkit.md`](references/rc_device_toolkit.md)（可抄工具集：is_rc_device / randn 分流 / floordiv 补丁 / 整段搬 CPU） |

---

## 1. 算子兼容性

### 1.1 torch.cross 不支持

NPU 不支持 `torch.cross`（叉乘）。手动实现：

```python
def manual_cross(a, b):
    return torch.stack([
        a[..., 1] * b[..., 2] - a[..., 2] * b[..., 1],
        a[..., 2] * b[..., 0] - a[..., 0] * b[..., 2],
        a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    ], dim=-1)
```

### 1.2 F.max_pool2d 不支持

`F.max_pool2d` 在某些 NPU 版本上不支持。用 `torch.amax` 替代：

```python
# 原代码
new_features = F.max_pool2d(new_features, kernel_size=[1, new_features.size(3)])
# 替代
new_features = torch.amax(new_features, dim=3, keepdim=True)
```

### 1.3 CUDA 自定义算子

PointNet2 等库使用 C++/CUDA 自定义算子（FPS、Ball Query、Grouping、Gather），NPU 无法运行。需要纯 PyTorch 重写，注意逻辑对齐。

---

## 2. 算子级逻辑差异

这是最难排查的一类问题。算子"能跑"但"结果不同"。

### 2.1 FPS（最远点采样）Tie-breaking

当存在重复点或距离相等的点时，NPU 和 CUDA 选择的索引不同。
- NPU 的 `torch.argmax` 返回第一个最大值索引
- CUDA 的分层归约在并行处理时可能选择不同的索引

修复：修改 CUDA 端的 tie-breaking 逻辑，统一为选最小索引：

```cpp
// CUDA sampling_gpu.cu 的 __update 函数
// 原来：
dists_i[idx1] = v2 > v1 ? i2 : i1;
// 改为：
if (v2 > v1 || (v2 == v1 && i2 < i1)) {
    dists_i[idx1] = i2;
    dists_i_v[idx1] = v2;
}
```

### 2.2 Ball Query 遍历顺序

NPU 版本按距离排序选点，CUDA 版本按索引顺序选点。结果完全不同。

CUDA 的正确逻辑：

```cpp
// 按索引顺序 k=0,1,2,... 遍历所有点
for (int k = 0; k < n; ++k) {
    if (distance < radius2) {
        idx[cnt] = k;
        cnt++;
        if (cnt >= nsample) break;
    }
}
// 不足 nsample 时，用找到的第一个点填充
```

重写纯 PyTorch 版本时，必须对齐 CUDA 的遍历逻辑，不要用排序。

### 2.3 配置参数差异

NPU 和 CUDA 测试用不同的 radius 等参数，导致结果不可比。对齐时必须确认参数一致。

---

## 3. 依赖清理

### 3.1 移除 CUDA 专属依赖

- CUDA 编译的扩展（`.cu` 文件）需要纯 PyTorch 或 NPU 算子替代

### 3.2 torch_npu 导入

```python
import torch
import torch_npu
```

`import torch_npu` 只是注册后端；**推理时通常紧跟一行关闭 JIT 编译**，只用预编译算子内核（无首跑编译开销、行为稳定），这是 `import torch_npu` 的标配搭档：

```python
torch.npu.set_compile_mode(jit_compile=False)
```

`jit_compile` 是**全局**设置：

| 值 | 行为 | 适用 |
|---|---|---|
| `True`（默认） | 首次执行时动态编译算子 | 开发调试，或遇到 `Op X does not has any binary` 时 |
| `False` | 只用预编译内核，无 JIT 开销 | **生产推理，追求稳定性能** |

若某个算子在 `False` 下缺预编译内核（报 `Op X does not has any binary`），可只对该模块选择性开 JIT（写法见 `torchair/README.md` 的 selective JIT），其余保持 `False`；不要图省事全局开 `True`，首跑会很慢。

如果项目同时支持 PTH 和 OM 路径，torch_npu 的导入策略见 `ascend-om-deployer` skill 的 `references/om-eval-adapt.md`。

---

## 排查方法

在 CUDA 版本和 NPU 版本中，逐层打印中间结果（前几个值即可），找到第一个出现差异的位置，然后集中排查该层。
