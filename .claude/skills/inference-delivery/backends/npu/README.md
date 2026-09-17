# NPU 后端（CUDA → NPU 迁移）

> inference-delivery 的 NPU 设备后端。三条推理路径：OM 离线 / TorchAir 图模式 / 纯 torch_npu，
> 可组合使用：先用 torch_npu 跑通 → TorchAir 加速 → 最终 OM 部署。设备无关的优化模式见
> [../../optimization/README.md](../../optimization/README.md)。

## 路径选择

```
用户要迁移模型到昇腾 NPU
│
├─ 追求极致性能、离线部署、生产环境？
│  └─ OM 离线路径 → Read [om/README.md](om/README.md)
│
├─ 想在 PyTorch 内获得图模式加速，不想导出 ONNX？
│  └─ TorchAir 路径 → Read [torchair/README.md](torchair/README.md)
│
└─ 快速迁移、调试开发、模型验证？
   └─ 纯 torch_npu 路径 → Read [torch_npu/README.md](torch_npu/README.md)
```

### 路径对比

| | OM 离线推理 | TorchAir 图模式 | 纯 torch_npu |
|---|---|---|---|
| **原理** | PyTorch → ONNX → ATC → .om → ACL 推理 | torch.compile(torchair) → NPU 图模式 | torch.cuda → torch.npu 直接替换 |
| **性能** | 最高（算子融合、内存优化） | 高（图优化） | 最低（eager mode） |
| **迁移成本** | 高（导出、ATC、接回） | 中（适配图模式约束） | 低（API 替换） |
| **适用阶段** | 生产部署 | 训练/推理加速 | 开发调试 |

### 快速读取表

| 用户要做什么 | 读取 |
|---|---|
| 快速跑通 NPU | 本文件通用步骤 + [torch_npu/README.md](torch_npu/README.md) |
| 部署到 OM | 本文件通用步骤 + [om/README.md](om/README.md) |
| TorchAir 加速 | 本文件通用步骤 + [torchair/README.md](torchair/README.md) |
| 排查 NPU 报错 | 本文件排查优先级 + [torch_npu/README.md](torch_npu/README.md) |
| 图化后端到端仍慢 / 图外小算子串 / 跨板性能差异归因（launch 邮费） | [references/LAUNCH_OVERHEAD.md](references/LAUNCH_OVERHEAD.md)（跨路径：OM/torchair/torch_npu 通用） |
| 跑通后整体提速（CPU 前后处理 / 采样循环等设备无关优化） | [../../optimization/README.md](../../optimization/README.md)（同 skill 通用层） |
| ONNX 导出问题 | [onnx-debug/README.md](onnx-debug/README.md)（同后端，om 的前置环节） |
| 自定义算子 | [../../../AscendC-ops-dev/SKILL.md](../../../AscendC-ops-dev/SKILL.md)（独立 skill） |

---

## 通用迁移步骤

无论走哪条路径，以下步骤都要先做：

### 1. 环境准备

基础环境（Docker 镜像选择、容器创建、conda 环境、pip 依赖、宿主机容器协作）→ Read [references/environment.md](references/environment.md)

### 2. 设备字符串替换

```python
'cuda' / 'cuda:0'  →  'npu' / 'npu:0'
torch.cuda.is_available()  →  torch.npu.is_available()
tensor.cuda()  →  tensor.to(device)
torch.cuda.FloatTensor  →  torch.empty(..., device=device)
```

不要硬编码 `'npu:0'`，设备号由配置参数控制。

### 3. 数据类型

部分昇腾芯片上 `torch.randn` 等可能默认 float64。所有 tensor 创建显式指定 `dtype=torch.float32`。

排查：全局搜索 `torch.randn`、`torch.rand`、`torch.randn_like`、`torch.zeros`。

### 4. CUDA 自定义算子

`.cu` 文件 NPU 无法运行，需要：
- 纯 PyTorch 重写
- 或 AscendC 写 NPU 自定义算子 → Read [../../../AscendC-ops-dev/SKILL.md](../../../AscendC-ops-dev/SKILL.md)

### 5. 随机种子

```python
random.seed(42)
np.random.seed(42)
torch.manual_seed(42)
```

---

## 排查优先级

遇到 NPU 适配问题，按以下顺序排查：

1. **数据类型**：tensor 创建是否显式 float32
2. **设备字符串**：是否残留 `.cuda()`、`torch.cuda`
3. **算子兼容性**：NPU 不支持的算子（`torch.cross`、`F.max_pool2d` 等）
4. **自定义 CUDA 算子**：需要纯 PyTorch 或 AscendC 重写
5. **算子逻辑差异**：tie-breaking、遍历顺序等隐含行为差异
6. **数据加载**：DataLoader 配置、随机种子

对比方法：逐层打印中间结果，找到第一个差异位置，集中排查。
