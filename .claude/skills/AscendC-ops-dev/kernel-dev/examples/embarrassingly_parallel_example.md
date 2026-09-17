# Embarrassingly Parallel 型算子开发范例

以 GroupPoints（`grouping_operation`）为例，展示从 CUDA 原版分析到整网集成的完整流程。
适用于每个输出元素独立计算、无跨核依赖的算子。

## 1. CUDA 原版分析

```cuda
// out[b,c,pt,s] = points[b, c, idx[b,pt,s]]
__global__ void group_points_kernel_fast(int b, int c, int n, int npoints, int nsample,
    const float *points, const int *idx, float *out) {
    int bs_idx = blockIdx.z;
    int c_idx = blockIdx.y;
    int index = blockIdx.x * blockDim.x + threadIdx.x;
    int pt_idx = index / nsample;
    int sample_idx = index % nsample;

    idx += bs_idx * npoints * nsample + pt_idx * nsample + sample_idx;
    int in_idx = bs_idx * c * n + c_idx * n + idx[0];
    int out_idx = bs_idx * c * npoints * nsample + c_idx * npoints * nsample + pt_idx * nsample + sample_idx;

    out[out_idx] = points[in_idx];
}

// Grid: dim3 blocks(DIVUP(npoints*nsample, THREADS), c, b)
```

**关键特征**：每个 thread 独立，无同步，纯标量 gather → Embarrassingly Parallel 型。

**注意**：应分析 CUDA 原版而非 PyTorch 适配版（`expand + torch.gather`）。PyTorch 版为框架兼容做的转换不代表最优实现。

## 2. AscendC Kernel 设计

### 多核策略

按 (b, c) pair 分配到不同核。8 核处理 B×C 个 pair。不需要 SyncAll。

### 每核处理流程

```
for each assigned (b, c):
  1. DataCopy(GM→UB): 读 points[b, c, 0:N] 整行（4KB for N=1024）
  2. for pt_chunk in range(0, npoint, PT_CHUNK):
       a. DataCopy(GM→UB): 读 idx[b, pt_chunk:pt_chunk+PT_CHUNK, 0:nsample]
       b. 标量循环: GetValue 读 idx → GetValue 读 points[idx] → SetValue 写 out
       c. DataCopy(UB→GM): 写 out[b, c, pt_chunk:..., 0:nsample]
       d. GetValue(0) 建立读取依赖（见 TBuf DMA 警告）
```

### TBuf 循环 DMA 依赖警告

TBuf 模式下，循环内 `DataCopy(UB→GM)` 后，如果下一轮迭代会覆盖同一 buffer（如 `Duplicate` 或新的 `DataCopy(GM→UB)`），编译器可能将下一轮操作提前到 DMA 完成之前。`pipe_barrier(PIPE_V)` 无法阻止此优化。

**必须在 `DataCopy(UB→GM)` 后加一行 GetValue 建立依赖**：

```cpp
AscendC::DataCopy(outGm[offset], outLocal, count);
pipe_barrier(PIPE_V);
float _dummy = outLocal.GetValue(0);
(void)_dummy;
```

**什么时候需要**：TBuf 循环中，某 buffer 在一轮作为 DMA 源，在下一轮被覆盖。
**什么时候不需要**：下一轮覆盖的是**不同的** buffer，或使用 TQue 模式（自带依赖管理）。

### 对齐 DataCopy + sub-offset 模式

当需要从非对齐 GM 地址读取数据时（如 `tensor[b, m, :]` 在 `m*3` 偏移处，`m*3` 不一定是 8 的倍数），不能直接 `DataCopy`（要求 32 字节对齐）。解决方法：

1. 从最近的 8 元素对齐边界读取（多读一些数据到 UB）
2. 用 `GetValue` 的 sub-offset 取正确位置的值

```cpp
// 要读 new_xyz[b, m, :]，偏移 = b*M*3 + m*3（可能不对齐）
int32_t rawIdx = b * M * 3 + m * 3;
int32_t alignedIdx = (rawIdx / 8) * 8;   // 向下对齐到 8
int32_t subOff = rawIdx - alignedIdx;      // 子偏移
AscendC::DataCopy(newXyzBuf, newXyzGm[alignedIdx], 16);  // 读 16 个 float
pipe_barrier(PIPE_V);
float nx = newXyzBuf.GetValue(subOff + 0);
float ny = newXyzBuf.GetValue(subOff + 1);
float nz = newXyzBuf.GetValue(subOff + 2);
```

`alignedIdx * 4` 一定是 32 的倍数，满足 DataCopy 对齐要求。多读的数据（对齐边界到实际偏移之间）被忽略。

### UB 内存预算（N=1024, PT_CHUNK=64, nsample=32）

| buffer | 大小 | 用途 |
|--------|------|------|
| pointsRow | 4KB | points 一行 |
| idxBlock | 8KB | idx 块（对齐到 8） |
| outBlock | 8KB | 输出块（对齐到 8） |
| tmpBuf | 32B | DataCopy 对齐填充 |
| **总计** | **~20KB** | 远小于 128KB UB 上限 |

### TilingData

```cpp
struct GroupPointsTilingData {
    int32_t B;
    int32_t C;
    int32_t N;
    int32_t npoint;
    int32_t nsample;
    int32_t numCores;
    int32_t pairsPerCore;    // ceil(B*C / numCores)
    int32_t ptChunk;         // PT_CHUNK (e.g., 64)
};
```

## 3. 通用文件结构

一个典型的 AscendC 算子 kernellaunch 项目包含以下文件：

| 文件 | 说明 |
|------|------|
| `<op_name>.h` | TilingData 结构体定义 |
| `<op_name>.cpp` | AscendC kernel 实现（Init + Process） |
| `<op_name>_host.cpp` | Host wrapper（C 接口，ctypes 可调） |
| `<op_name>.py` | Python ctypes 封装 + monkey-patch 函数 |
| `<op_name>_benchmark.py` | 单算子 benchmark（正确性 + 性能） |
| `CMakeLists.txt` | 添加 kernel 文件到 KERNEL_FILES，添加 host wrapper shared library |
| `cmake/npu_lib.cmake` | 编译时自动生成 `aclrtlaunch_<op_name>.h` |

## 4. Host Wrapper 关键点

```cpp
extern "C" int op_run_dynamic(
    void *input_ptr, void *output_ptr, ...,
    int32_t num_cores, void *stream_ptr)
{
    // Embarrassingly parallel 型：只需 tiling buffer，无需 sync buffer
    // 不需要 aclrtSynchronizeStream — 依赖 torch.npu stream 管理
    OpTilingData tiling;
    // ... 填充 tiling ...
    aclrtMemcpy(g_tiling_buf, ..., &tiling, ..., ACL_MEMCPY_HOST_TO_DEVICE);
    aclrtlaunch_op_dynamic(num_cores, stream, input_ptr, output_ptr, g_tiling_buf);
    return 0;
}
```

## 5. Python Wrapper 范式

```python
class OpAscendC:
    def __init__(self, num_cores=8):
        self.num_cores = num_cores
        self.lib = _load_lib("lib<op_name>_host.so")
        # 设置 restype 和 argtypes

    @torch.no_grad()
    def __call__(self, input_tensor, ...):
        # assert 输入合法性（device、dtype、dim）
        # 分配输出 tensor
        # 获取 NPU stream 指针
        # 调用 host wrapper
        # assert ret == 0
        return out
```

关键注意事项：
- `torch.npu.set_device(0)` 必须在创建 OpAscendC 实例之前调用
- `_get_npu_stream()` 遍历 stream 对象的属性获取原生指针，失败时 raise RuntimeError
- 输出 tensor 用 `torch.zeros()` 分配在 NPU 上，kernel 直接写入

## 6. Monkey-patch 集成

```python
_patched = False

def patch_op(num_cores=8):
    global _patched
    if _patched:
        return
    kernel = OpAscendC(num_cores=num_cores)

    from some_module import target_utils

    def _replacement(*args, **kwargs):
        # dtype 转换（如 int64 → int32）
        return kernel(*args, **kwargs)

    target_utils.original_function = _replacement
    _patched = True
```

## 7. Benchmark 模板

```python
WARMUP = 5
REPEATS = 50
SHAPES = [
    # 匹配实际网络中各层调用参数
]

def run_bench(name, fn, *args):
    for _ in range(WARMUP):
        fn(*args)
    torch.npu.synchronize()

    times = []
    for _ in range(REPEATS):
        torch.npu.synchronize()
        t0 = time.perf_counter()
        fn(*args)
        torch.npu.synchronize()
        times.append((time.perf_counter() - t0) * 1000)

    avg_ms = sum(times) / len(times)
    min_ms = min(times)
    print(f"  {name}: avg={avg_ms:.3f}ms, min={min_ms:.3f}ms")
    return avg_ms

# 正确性测试
pytorch_out = pytorch_op(input, idx)
ascendc_out = ascendc_kernel(input, idx)
match = torch.allclose(pytorch_out, ascendc_out, atol=1e-5)
```

## 8. 实测性能数据

数据来源：GenPose2 项目（`ACL_PyTorch/built-in/embodied_ai/GenPose2`），PointNet2 点云编码器。
网络为 GenPose++（ECCV 2024）的 6D 姿态估计模型，使用 DINOv2 + PointNet2 + Score/Energy Network 架构。
硬件：Ascend 310P3，DataLoader batch_size=16，共 128 samples。

### 单算子性能（GroupPoints，SA0 shape: B=1,C=390,N=1024,npoint=512,nsample=32）

| 配置 | vs PyTorch | 原因 |
|------|-----------|------|
| AscendC 1-core | 1.4x | 标量循环慢，但无框架调度开销 |
| AscendC 8-core B=1 | 0.5-0.9x | 多核并行度不足，PyTorch 向量化 gather 更快 |
| AscendC 8-core B≥8 | **11x** | 多核并行 + 无框架开销 |

### 整网端到端效果

GroupPoints 占 Score+Energy 阶段的 72.5%（74.3s），替换后降至 25.5%（9.9s）。

| 指标 | PyTorch | AscendC | 提升 |
|------|---------|---------|------|
| Grouping 总耗时 | 74.291s | 9.881s | **7.5x** |
| Score+Energy | 102.5s | 38.7s | **2.65x** |
| 每样本延迟 | 812.7ms | 321.3ms | **2.53x** |
