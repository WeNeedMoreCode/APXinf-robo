# Kernel 开发

**何时读此文件**：你在写或调试 AscendC kernel（API 用法、多核、buffer、tiling、项目搭建）。

## 核心原则

**在 AscendC 里，你看到的不一定是你得到的。** API 签名看起来合理不代表行为正确。GetValue(GlobalTensor) 有返回值但不一定返回正确的值。pipe_barrier(PIPE_V) 不会等 DMA。SyncAll() 无参版在 310P3 上无效。这些坑只有实测才能发现，文档不会告诉你。

## 算子开发工作流

### 1. 分析来源

如果 PyTorch 实现源自 CUDA 版，应先看 CUDA 原版实现。CUDA 原版展示了真正的算法意图和并行策略，PyTorch 适配版往往为了框架兼容做了额外转换（如 `expand + torch.gather`），这些转换在 NPU 上反而有框架调度开销。

如果 PyTorch 实现不是源自 CUDA（或没有对应的 CUDA 实现），则直接基于原始实现分析优化即可。AscendC 实现应对标原始逻辑，而不是 PyTorch 的框架适配逻辑。

### 2. 先做单算子 benchmark，再集成整网

```
1. 实现 kernel + host wrapper + Python wrapper
2. 写 benchmark 脚本（正确性 + 多 shape + 多 batch 性能）
3. 确认正确性 PASS、性能达标
4. 再集成到整网评估脚本的 monkey-patch 开关
```

### 3. 正确性验证方法

```python
# benchmark 中对比 PyTorch 版和 AscendC 版
pt_out = pytorch_op(input_data)
ac_out = ascendc_kernel(input_data)
match = torch.allclose(pt_out, ac_out, atol=1e-5)
max_diff = (pt_out - ac_out).abs().max().item()
```

### 4. Monkey-patch 集成模式

替换 `pointnet2_utils` 中的算子函数。注意：
- idx 可能是 int64，AscendC kernel 需要 int32，在 wrapper 中做转换
- patch 在 `_timed_op` 包装之前执行，确保计时测量的是 AscendC 版本
- 用全局标志防止重复 patch

## 两种多核算子模式

### 串行依赖型（如 FPS）

每步依赖上一步结果，必须跨核同步。结构复杂，需要 SyncAll、共享 GM buffer、host 清零 sync buffer。

特征：算法本身是串行的（FPS 每步选一个最远点），多核只是加速单步内的并行计算。

### Embarrassingly Parallel 型

每个输出元素独立计算，无跨核同步。多核只是分配 workload。**不需要 SyncAll、不需要 sync buffer**。

```cpp
// 每核独立处理分配的 work items
int32_t myStart = coreId * itemsPerCore;
int32_t myEnd = min(myStart + itemsPerCore, totalItems);
for (int32_t p = myStart; p < myEnd; p++) {
    // 独立处理，不需要任何同步
}
```

**Host wrapper 极简**：只需 tiling buffer，无需 sync buffer：
```cpp
extern "C" int kernel_run_dynamic(...) {
    // 1. 上传 tiling 数据
    aclrtMemcpy(g_tiling_buf, ..., &tiling, ..., ACL_MEMCPY_HOST_TO_DEVICE);
    // 2. 启动多核 kernel（无需清零任何 buffer）
    aclrtlaunch_kernel_dynamic(num_cores, stream, ...);
    // 3. 不需要 synchronize — 依赖 torch.npu stream 管理
    return 0;
}
```

**设计决策**：新算子开发前，先判断是否属于 embarrassingly parallel 类型。如果是，可以大幅简化实现，跳过 SyncAll 相关的所有复杂性。

## 不规则索引访问（Gather/Scatter）

### AscendC 没有向量化 gather 指令

**实测 + 官方 sample 确认**：AscendC 不提供 `out[i] = input[index[i]]` 的向量化 API。

官方唯一的不规则索引 sample（`3_libraries/0_scatter_kernellaunch/scatter_custom.cpp`）使用标量循环：

```cpp
for (uint32_t i = 0; i < mElementCount; ++i) {
    auto offset = yLocal.GetValue(i) / sizeof(T);
    auto srcValue = xLocal.GetValue(i);
    zLocal.SetValue(offset, srcValue);
}
```

`GatherMask`（`0_introduction/16_unaligned_abs_kernellaunch/AbsGatherMaskKernelInvocation`）基于固定 pattern+mask，不支持任意索引。

`2_features` 下无对等实现——全部是偏移可计算的访问模式（`base + blockIdx * stride`），不是数据依赖的不规则索引。

### 最优策略：DataCopy 整行到 UB + 标量循环

```
对于 out[b,c,pt,s] = input[b, c, idx[b,pt,s]] 这类操作：

1. DataCopy(GM→UB): 读 input[b, c, 0:N] 整行到 UB
2. DataCopy(GM→UB): 读 idx 块到 UB
3. for each (pt, s):
     idxVal = idxUB.GetValue(pt*nsample + s)   // UB 内标量读
     val = inputUB.GetValue(idxVal)             // UB 内标量读（on-chip）
     outUB.SetValue(pt*nsample + s, val)        // UB 内标量写
4. DataCopy(UB→GM): 写输出块
```

**关键优化**：整行读入 UB 后，不规则索引读取发生在 UB 内部（on-chip），避免了对 GM 的随机访问。

### 性能特征（310P3 实测，B=16 DataLoader）

| 配置 | vs PyTorch | 原因 |
|------|-----------|------|
| AscendC 1-core | 1.4x | 标量循环慢，但无框架调度开销 |
| AscendC 8-core B=1 | 0.5-0.9x | 标量循环 + 多核并行度不足，PyTorch 向量化 gather 更快 |
| AscendC 8-core B≥8 | **11x** | 多核并行 + 无框架开销 |
| AscendC 8-core B=32 | **11x** | 同上，达到平台天花板 |

**结论**：B≥8 时 AscendC 标量循环 + 多核并行的吞吐远超 PyTorch。B=1 时 PyTorch 的向量化 gather 更快。这是架构性差异，非实现问题——AscendC 没有向量化 gather，官方也是标量循环。

## 官方 Sample 位置

`D:\compass\modelzoo\samples\operator\ascendc`

关键 sample：
- `0_introduction/16_unaligned_abs_kernellaunch` — SyncAll 3 参数版
- `0_introduction/21_vectoradd_kernellaunch` — 多核 kernellaunch 模板
- `3_libraries/0_scatter_kernellaunch` — 不规则索引（标量 GetValue/SetValue 循环）
- `2_features/16_group_barrier` — GroupBarrier 跨核同步
- `4_best_practices/6_group_matmul` — CrossCoreSetFlag 核内同步

## 新项目搭建

从一个新目录开始做 AscendC 多核算子开发，最省事的方式是拷贝官方 kernellaunch sample 作为脚手架：

**推荐模板**：`0_introduction/21_vectoradd_kernellaunch/VectorAddMultiCoreWithTiling/`

**从 skill assets 拷贝（已验证的稳定版本）**：

| 文件 | 用途 | 来源 |
|------|------|------|
| `assets/cmake/` 目录 | CMake 构建模块（`cpu_lib.cmake`、`npu_lib.cmake`） | 拷贝自官方 sample |
| `assets/run.sh` | 编译脚本（`bash run.sh -r npu`） | 修改自官方 sample，去掉了 sample 专有测试逻辑 |
| `assets/main.cpp` | （可选）CPU 仿真/NPU 直连冒烟测试入口 | 拷贝自官方 sample |
| `assets/data_utils.h` | （可选）`main.cpp` 配套工具库（`CHECK_ACL`、文件读写等） | 拷贝自官方 sample |

**从官仓 sample 拷贝（需要根据自己项目修改）**：

| 文件 | 用途 |
|------|------|
| `CMakeLists.txt` | 构建配置，修改 kernel 文件列表和 host wrapper 列表 |

**自己写的内容**：

| 文件 | 说明 |
|------|------|
| `xxx_dynamic.cpp` | AscendC kernel 实现（多核版） |
| `xxx_dynamic.h` | TilingData 结构体 |
| `xxx_host_dynamic.cpp` | Host wrapper（参数解析、tiling 上传、kernel launch） |
| `xxx_ascendc.py` | Python ctypes 封装 |

**CMakeLists.txt 需要改的地方**：
1. `file(GLOB KERNEL_FILES ...)` — 改成你的 kernel 源文件列表
2. NPU 分支内的 `add_library` / `install` 块 — 改成你的 host wrapper

`cmake/` 目录是标准构建基础设施，所有项目共用同一份，不需要理解内容。

## 完整开发范例

根据算子类型选择对应参考文件：

- **[串行依赖型范例](examples/serial_dependency_example.md)** — 算法每步依赖上一步结果，需 SyncAll 跨核同步。以 FPS 为例。
- **[Embarrassingly Parallel 型范例](examples/embarrassingly_parallel_example.md)** — 每个输出元素独立计算，无跨核同步。以 GroupPoints 为例。
- **[向量化循环型范例](examples/nms_vectorized_loop_example.md)** — 多核各跑一个串行循环，循环内用向量化加速。含算法优化（预排序消除 argmax）、数据布局优化（转置输入消除标量 deinterleave）、多核并发写入修复。以 NMS 为例。

## 子主题导航

| 要查什么 | 读 |
|----------|-----|
| API 哪些可靠哪些坑（GetValue/DataCopy/SyncAll）+ GM 读写 + 管线同步 | [api_reliability.md](api_reliability.md) |
| 多核 dispatch + 跨核同步（SyncAll/GroupBarrier） | [multicore.md](multicore.md) |
| Buffer 管理（TBuf/TQue/DMA 陷阱/对齐） | [buffers.md](buffers.md) |
| Host wrapper + 动态 Shape Tiling + 调试方法 | [host_and_debug.md](host_and_debug.md) |
