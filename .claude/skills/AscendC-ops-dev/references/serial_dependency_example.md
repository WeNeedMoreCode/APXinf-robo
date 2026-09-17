# 串行依赖型算子开发范例

以 FPS（`furthest_point_sample`）为例，展示串行依赖型多核算子的开发流程。
适用于算法每步依赖上一步结果、需要跨核同步的算子。

## 1. 算法特征

FPS 每步选一个距已选点集最远的点，迭代 npoints 次。每步的全局最远点需要所有核汇总后比较——这就是串行依赖的来源。

多核策略：每步内并行计算各核负责的距离，SyncAll 汇总后选全局最远点，所有核同步后进入下一步。

## 2. 跨核同步（SyncAll）

### 3 参数版 SyncAll（310P3 唯一可靠方式）

```cpp
// GM buffer: NUM_CORES * 8 个 int32_t
AscendC::GlobalTensor<int32_t> syncGm;
syncGm.SetGlobalBuffer((__gm__ int32_t *)sync, NUM_CORES * 8);

// UB buffer: 同大小
AscendC::TBuf<AscendC::TPosition::VECIN> syncBuf;
pipe.InitBuffer(syncBuf, NUM_CORES * 8 * sizeof(int32_t));
auto syncLocal = syncBuf.Get<int32_t>();

// 调用
AscendC::SyncAll(syncGm, syncLocal, NUM_CORES);
```

SyncAll buffer 要求：
- GM: `NUM_CORES * 8` 个 `int32_t`（最小 64 字节）
- UB: 同大小，通过 `TBuf` 分配
- 必须是 `int32_t` 类型

### SyncAll Buffer 必须每次清零（关键）

kernel 完成后 syncGm 残留上一次的同步标志。当 kernel 在 torch_npu 操作后运行时（如 Conv2D/BN/MaxPool 后），AICore 的 GM 缓存使残留标志对新一轮 SyncAll 可见，导致 SyncAll 误判同步状态而死锁（aicore timeout 507014）。

**表现**：kernel 单独测试正常，跑完一轮网络后再次调用就挂。

**修复**：host wrapper 在每次 `ACLRT_LAUNCH_KERNEL` 前清零 sync buffer：
```cpp
int32_t zeros[MAX_CORES * 8] = {0};
aclrtMemcpy(g_sync_buf, sizeof(zeros), zeros, sizeof(zeros), ACL_MEMCPY_HOST_TO_DEVICE);
aclrtlaunch_fps_custom(num_cores, stream, ...);
```

## 3. 跨核数据交换模式

### 写入方：Duplicate + DataCopy

```cpp
auto stage = stageBuf.Get<float>();
AscendC::Duplicate(stage, localBestVal, 1);       // 向量写入（可靠）
AscendC::Duplicate(stage[1], localBestIdxFloat, 1);
AscendC::DataCopy(resultsGm[coreId * CHUNK], stage, 8);
pipe_barrier(PIPE_V);
```

不能用 `SetValue(LocalTensor) + DataCopy(UB→GM)`——DMA 可能在标量写完成前就读走了 UB 数据。

### 同步

```cpp
AscendC::SyncAll(syncGm, syncLocal, NUM_CORES);
```

### 读取方：DataCopy(GM→UB) + 扫描 UB

```cpp
AscendC::DataCopy(cross, resultsGm, NUM_CORES * CHUNK);
pipe_barrier(PIPE_V);
// GetValue(LocalTensor) 可靠——从 UB 读
float val = cross.GetValue(c * CHUNK);
```

不能用 `GetValue(GlobalTensor)`——多核下读 GM 不稳定。

## 4. 不可靠的 API 及替代方案

| 不可靠 API | 替代方案 |
|-----------|---------|
| `GetValue(GlobalTensor)` | `DataCopy(GM→UB) + GetValue(LocalTensor)` |
| `SetValue(GlobalTensor)` | `SetValue(LocalTensor) + DataCopy(UB→GM)` |
| `SetValue(LocalTensor) + DataCopy(UB→GM)` | `Duplicate + DataCopy(UB→GM)` |
| `SyncAll()` 无参版 | `SyncAll(syncGm, syncLocal, coreNum)` 3 参数版 |
| `pipe_barrier(PIPE_MTE3)` | 不是 DMA 同步手段，有害无益 |

## 5. 独立 Staging Buffer 模式

向 GM 写少量数据时（如跨核通信的 local result），用独立小 buffer 做 staging，不能复用计算 buffer：

```cpp
// 错误：复用 dist buffer 污染下一轮计算
AscendC::Duplicate(dist, localBestVal, 1);       // dist[0] 被覆盖！
AscendC::DataCopy(resultsGm[coreId * CHUNK], dist, CHUNK);

// 正确：独立 staging buffer
auto stage = stageBuf.Get<float>();
AscendC::Duplicate(stage, localBestVal, 1);
AscendC::Duplicate(stage[1], localBestIdxFloat, 1);
AscendC::DataCopy(resultsGm[coreId * CHUNK], stage, 8);
```

## 6. 实测性能数据

数据来源：GenPose2 项目（`ACL_PyTorch/built-in/embodied_ai/GenPose2`），PointNet2 点云编码器。
网络为 GenPose++（ECCV 2024）的 6D 姿态估计模型，使用 DINOv2 + PointNet2 + Score/Energy Network 架构。
硬件：Ascend 310P3，DataLoader batch_size=16，共 128 samples。

FPS 在整网 Score+Energy 中占比仅 0.6%（0.603s），单算子加速比 1.1x（0.603s → 0.536s）。
FPS 占比低是因为它只被调用 24 次（3 个 SA 层 × 8 batch），且每次处理的数据量远小于 Grouping。

整网效果见 embarrassingly_parallel_example.md。
