# Buffer 管理

**何时读此文件**：kernel 里分配 TBuf/TQue、做 DataCopy、遇到 buffer 复用/对齐/UB 容量问题。

## UB 容量可能是硬约束

310P3 的 UB（Unified Buffer）容量有限。当 buffer 分配总量接近上限时，新增 buffer 可能导致 kernel 挂死（无报错）。NMS 算子中出现过：已有 buffer 约 41KB（N=1000），新增 4KB buffer 即挂死，但根因未确认是否为 UB 溢出。**规划 buffer 时留意总量，新增 buffer 导致挂死时优先怀疑容量问题。**

## TBuf vs TQue

| 特性 | TBuf | TQue |
|------|------|------|
| 使用方式 | `Get<T>()` 直接获取 | `AllocTensor` / `EnQue` / `DeQue` / `FreeTensor` |
| 生命周期 | 整个 Process | 需要手动管理 |
| 适用场景 | 简单算子、单次使用 | 需要流水线并行、double buffer |
| 临时 buffer 位置 | `TBuf<VECIN>` 可用 | 临时 buffer 应用 `TBuf<VECCALC>` |

## DMA Buffer 复用陷阱（关键）

`pipe_barrier(PIPE_V)` **不等 DMA 完成**。同一 buffer DataCopy 后立刻被 Duplicate 覆盖，DMA 读到覆盖后的数据：

```cpp
// 错误：DMA 读到 Duplicate 后的值
AscendC::DataCopy(gm_dst, buf, 8);     // DMA 入队，将读 buf
AscendC::Duplicate(buf, new_val, 8);   // 覆盖 buf！DMA 还没读完

// 正确：用独立 buffer
AscendC::DataCopy(gm_dst, bufA, 8);    // DMA 读 bufA
// bufA 之后再也不会被碰
AscendC::Duplicate(bufB, new_val, 8);  // 用另一个 buf
```

## TBuf 循环内 DMA 流水线 bug（关键）

**现象**：TBuf 模式下，循环内 `DataCopy(UB→GM)` 后，下一轮迭代的 `Duplicate` 或 `DataCopy(GM→UB)` 覆盖同一 buffer。`pipe_barrier(PIPE_V)` 没有阻止编译器将下一轮的 buffer 操作提前到 DMA 完成之前。结果：DMA 读到下一轮覆盖后的数据，输出错误。

**与 TQue 的区别**：TQue 通过 `EnQue/DeQue` 队列机制隐式管理依赖，编译器能正确追踪 DMA 生命周期。TBuf 没有这个机制，编译器可能做激进的软件流水线优化。

**什么时候触发**：TBuf 循环中，某 buffer 在一轮 `DataCopy(UB→GM)` 作为源，在下一轮被 `Duplicate` 或 `DataCopy(GM→UB)` 覆盖（作为目的）。且该 buffer 在 `DataCopy` 后不再被读取。

**修复**：在 `DataCopy(UB→GM)` 后加一行 `GetValue(0)` 建立读取依赖，阻止编译器跨迭代流水线化：

```cpp
// 循环内：
AscendC::DataCopy(idxGm[offset], idxLocal, nsampleAlign);
pipe_barrier(PIPE_V);
// 防止编译器将下一轮的 Duplicate(idxLocal) 提前到此 DMA 完成之前
float _dummy = idxLocal.GetValue(0);
(void)_dummy;
```

**尝试过但不生效的方法**：
- 单独加 `pipe_barrier(PIPE_V)` → 编译器可能忽略（实测无效）
- 加 `paddingBuf` UB 分配但不使用 → 编译器优化掉未使用的 buffer
- 加 `paddingBuf` + `Duplicate`（使用但无 DMA）→ 不影响问题 buffer 的依赖
- 在 host 侧多分配 device 内存 → 不影响 kernel 内的 buffer 依赖

**官方 samples 为什么没记录**：所有 sample kernel 使用 TQue 模式，自带依赖管理。TBuf 循环 + buffer 跨迭代复用的模式在 samples 中未出现。

## 独立 Staging Buffer 模式

需要向 GM 写少量数据时（如跨核通信的 local result），用独立小 buffer 做 staging：

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

## DataCopy 对齐要求

DataCopy 的 count 必须是 8 的倍数（float32 对应 32 字节）。不够时用 DIAG_FIELDS 向上对齐：

```cpp
constexpr int32_t ACTUAL_FIELDS = 10;
constexpr int32_t DIAG_FIELDS = 16;  // 向上对齐到 8 的倍数
```

## LocalTensor 不支持指针算术

```cpp
// 错误
AscendC::DataCopy(cross + c * 8, resultsGm[c * CHUNK], 8);

// 正确：一次 DataCopy 全量，然后从 UB 里读
AscendC::DataCopy(cross, resultsGm, NUM_CORES * CHUNK);
pipe_barrier(PIPE_V);
float val = cross.GetValue(c * CHUNK);
```
