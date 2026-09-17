# Host Wrapper 与动态 Shape

**何时读此文件**：写 C++ host wrapper（参数解析、tiling 上传、kernel launch）、处理动态 shape（TilingData 参数化）、或调试 kernel 行为。

## Host Wrapper 开发

### aclrtSynchronizeStream 必要性

多核算子的 host wrapper 应在 `aclrtlaunch` 后加 `aclrtSynchronizeStream(stream)`。不加同步在部分执行模式下可能出现严重性能退化（实测 7 倍），但在其他模式表现正常。根因未确认。详见 [aclrtSynchronizeStream 实测分析](examples/aclrt_synchronize_analysis.md)。

### 设备上下文初始化

```python
import torch
import torch_npu
torch.npu.set_device(0)  # 必须调用！仅 import torch_npu 不够
```

仅 `import torch_npu` 不会创建设备上下文。`aclrtCreateStream` 等操作需要活跃的设备上下文，否则返回 107002。

### 逐步输出返回值

Host wrapper 中每一步都输出返回值，不要压缩成最终 pass/fail：

```cpp
fprintf(stderr, "[fps] Step 1: aclrtMalloc xyz...\n");
aclError ret = aclrtMalloc(&g_xyz_buf, size, ACL_MEM_MALLOC_HUGE_FIRST);
fprintf(stderr, "[fps] Step 1: ret = %d\n", (int)ret);
if (ret != ACL_SUCCESS) return -1;
```

### 共享设备内存

Host wrapper 可以接受 torch tensor 的 device pointer，避免额外拷贝：

```cpp
// Python 侧
xyz_tensor = torch.randn(1, N, 3, device='npu:0', dtype=torch.float32)
lib.fps_run_device(ctypes.c_void_p(xyz_tensor.data_ptr()), ...)

// C++ 侧
extern "C" int fps_run_device(float *xyz_dev, float *idx_dev) {
    // xyz_dev 已经在设备上，直接用
    aclrtlaunch_fps_custom(NUM_CORES, stream, xyz_dev, idx_dev, ...);
}
```

## 动态 Shape（Tiling 参数化）

当算子需要支持多种输入 shape 时，用 TilingData 结构体通过 GM 地址传给 kernel，不用编译时常量。

### TilingData 结构体

```cpp
struct MyTilingData {
    int32_t totalN;        // 总数据量
    int32_t npoints;       // 输出数量
    int32_t numCores;      // 实际使用的核数
    int32_t chunk;         // totalN / numCores
    int32_t blocksPerCore; // chunk / BLOCK_SIZE
};
```

Host 侧计算后 `aclrtMemcpy(H2D)` 到 device，kernel 启动时作为最后一个 GM 参数传入。

### Kernel 侧读取 Tiling（关键顺序）

```cpp
__aicore__ inline void Init(..., GM_ADDR tiling) {
    // 1. 先分配 tiling buffer（必须在 DataCopy 之前！）
    pipe.InitBuffer(tilingTmpBuf, 8 * sizeof(int32_t));

    // 2. DataCopy(GM→UB) 读 tiling（不能用 GetValue(GlobalTensor)）
    AscendC::GlobalTensor<int32_t> tilingGm;
    tilingGm.SetGlobalBuffer((__gm__ int32_t *)tiling, 8);
    auto tilingLocal = tilingTmpBuf.Get<int32_t>();
    AscendC::DataCopy(tilingLocal, tilingGm, 8);
    pipe_barrier(PIPE_V);

    // 3. 从 UB 读 tiling 值
    totalN = tilingLocal.GetValue(0);
    npoints = tilingLocal.GetValue(1);
    // ...

    // 4. 用 tiling 值分配其余 buffer
    pipe.InitBuffer(xyzBuf, 3 * totalN * sizeof(float));
    pipe.InitBuffer(distBuf, chunk * sizeof(float));
}
```

**踩坑**：如果 `InitBuffer(tilingTmpBuf)` 放在 DataCopy 之后，会产生"MTE write address out of range"错误（使用未分配的 buffer）。

### 自动降核

多核算子中，每核处理 chunk = N / numCores 个元素。chunk 必须 >= BLOCK_SIZE（通常 64），否则向量操作无法正确工作。

```cpp
// Host 侧：自动降低核数
int32_t max_cores = total_n / BLOCK_SIZE;
if (max_cores < 1) max_cores = 1;
if (num_cores > max_cores) num_cores = max_cores;
```

实际效果（BLOCK_SIZE=64）：
- N=1024: 用 8 核, chunk=128
- N=512: 用 8 核, chunk=64
- N=256: 用 4 核, chunk=64

### Host Buffer 按最大值分配

多 shape 场景下持久 buffer 必须按最大可能尺寸分配，否则首次小 shape 后大 shape 会越界：

```cpp
// 不要按当前 shape 分配
ensure_buf(&g_results, num_cores * chunk * sizeof(float));  // 危险！

// 按最大值分配
ensure_buf(&g_results, MAX_CORES * (MAX_N / MAX_CORES) * sizeof(float));  // 安全
```

## 调试方法论

### 最小化诊断 kernel

遇到多核问题时，先用最小 kernel 确认基础操作：

```cpp
// 最小 alive check：每核写 (coreId+1)*100.0
void Process() {
    auto buf = tmpBuf.Get<float>();
    AscendC::Duplicate(buf, (float)(coreId + 1) * 100.0f, 8);
    pipe_barrier(PIPE_V);
    AscendC::DataCopy(debugGm[coreId * 8], buf, 8);
    pipe_barrier(PIPE_V);
}
```

如果这个都不过，问题在 dispatch 或设备上下文，不在 kernel 逻辑。

### Host Readback 验证

区分 "GM 数据写错了" vs "kernel 内读 GM 有问题"：

```cpp
// C++ host wrapper 中加：
float host_scratch[SIZE];
aclrtMemcpy(host_scratch, SIZE, g_scratch_buf, SIZE, ACL_MEMCPY_DEVICE_TO_HOST);
fprintf(stderr, "Host readback: ");
for (int i = 0; i < 8; i++) fprintf(stderr, "%.1f ", host_scratch[i]);
fprintf(stderr, "\n");
```

如果 host readback 正确但 kernel 内读到错误值，说明问题在 kernel 内的读取方式（GetValue on GlobalTensor 等），不在数据写入。

### 诊断信息编码

多核调试时，每核写固定 stride 的诊断数据，避免跨核覆盖：

```cpp
constexpr int32_t DIAG_FIELDS = 16;  // 每核 16 个 float，对齐 DataCopy
int32_t dOff = coreId * DIAG_FIELDS * DEBUG_ITERS + (j - 1) * DIAG_FIELDS;
AscendC::DataCopy(debugGm[dOff], dbg, DIAG_FIELDS);
```

Python 侧解码：
```python
stride = DIAG_FIELDS  # 16
for core in range(NUM_CORES):
    for j in range(DEBUG_ITERS):
        offset = core * stride * DEBUG_ITERS + j * stride
        fields = debug_host[offset:offset + ACTUAL_FIELDS]
```

### 分离事实和假设

记录测试结果时：
- **事实**：GetValue 返回了 -2.0 而非预期的 10.0（原始数据）
- **假设**：GetValue 读错了地址（需要新实验验证）
- **不要把假设当结论记录**
