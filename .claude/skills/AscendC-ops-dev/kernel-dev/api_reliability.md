# API 可靠性与管线同步

**何时读此文件**：kernel 里用了 GetValue/DataCopy/SyncAll/pipe_barrier 等 API，需要知道 310P3 上哪些可靠、正确用法是什么。

## API 可靠性矩阵（310P3 实测）

| API | 可靠性 | 备注 |
|-----|--------|------|
| `GetValue(LocalTensor)` | **可靠** | 读 UB（on-chip），向量写入后立即可读 |
| `GetValue(GlobalTensor)` | **不可靠** | 多核下读 GM 不稳定，即使加了 SyncAll。Host readback 证明 GM 数据正确，但 kernel 内读不到 |
| `DataCopy(GM→UB) + SyncAll` | **可靠** | 跨核读 GM 的**唯一**正确方式。8/8 PASS |
| `DataCopy(UB→GM)` | **可靠** | Host `aclrtMemcpy D2H` 验证，数据正确写入 |
| `Duplicate(count=1)` | **可靠** | 独立 buffer 验证，8/8 PASS |
| `SyncAll(syncGm, syncLocal, coreNum)` | **可靠但需清零** | syncGm 必须在每次 kernel launch 前清零，否则残留标志导致死锁 |
| `SyncAll()` 无参版 | **无效** | 可能是 910B 专用，310P3 上无效 |
| `pipe_barrier(PIPE_V)` | **不完全可靠** | 两种已知问题（见下方跨管线同步） |
| `pipe_barrier(PIPE_MTE3)` | **有害** | 使结果更差，不是正确的 DMA 同步手段 |
| `SetValue(GlobalTensor)` | **不可靠** | 多核下写入值对其他核不可见 |
| `SetValue(LocalTensor) + DataCopy(UB→GM)` | **不可靠** | DMA 可能在标量写完成前就读走了 UB 数据 |
| `Duplicate + DataCopy(UB→GM)` | **可靠** | 纯向量操作，DMA 排队正确 |
| `TBuf + Duplicate + DataCopy(多核并发小数据, 无SyncAll)` | **未找到有效路径** | ≤16 元素的并发 GM 写入，stride 32B/64B 均未通过。有效路径：`SetAtomicAdd` 或 `TQue`。详见 [NMS 小数据并发写入探索](examples/nms_small_write_exploration.md) |

## 读取 GM 数据的正确模式

```cpp
// 错误：GetValue(GlobalTensor) 不可靠
float val = xyzGm.GetValue(idx);

// 正确：DataCopy(GM→UB) + GetValue(LocalTensor)
auto buf = tmpBuf.Get<float>();
AscendC::DataCopy(buf, xyzGm[offset], count);
pipe_barrier(PIPE_V);
float val = buf.GetValue(0);
```

## 跨核读 GM 数据的正确模式

```cpp
// 1. 写入方：Duplicate + DataCopy(UB→GM)
auto stage = stageBuf.Get<float>();
AscendC::Duplicate(stage, val, 1);
AscendC::DataCopy(resultsGm[coreId * CHUNK], stage, 8);
pipe_barrier(PIPE_V);

// 2. 同步
AscendC::SyncAll(syncGm, syncLocal, NUM_CORES);

// 3. 读取方：DataCopy(GM→UB) + 扫描 UB
AscendC::DataCopy(cross, resultsGm, NUM_CORES * CHUNK);
pipe_barrier(PIPE_V);
float val = cross.GetValue(c * CHUNK);  // GetValue(LocalTensor) 可靠
```

## 多核并发小数据 GM 写入的正确模式

当多个核各自向 GM 写入少量数据（如 per-core count）且不使用 SyncAll 时，TBuf + Duplicate + DataCopy 未找到有效路径。已验证的有效方案：

**方案一：SetAtomicAdd（来自官方 sample reduce_min / group_barrier）**

```cpp
auto countLocal = countBuf.Get<int32_t>();
Duplicate(countLocal, keepCount, 16);
pipe_barrier(PIPE_V);
SetAtomicAdd<int32_t>();           // DMA 模式切换为原子加
DataCopy(outCountGm, countLocal, 16);
pipe_barrier(PIPE_V);
SetAtomicNone();                   // 恢复普通模式
```

前提：GM 初始值为 0（torch.zeros），原子加等价于赋值。

**方案二：TQue 输出管道（来自官方 sample vectoradd_kernellaunch）**

```cpp
auto outputIdx = outputQueue.AllocTensor<int32_t>();
// ... NMS loop writes to outputIdx via SetValue ...
outputQueue.EnQue<int32_t>(outputIdx);
auto outLocal = outputQueue.DeQue<int32_t>();
DataCopy(outputGm, outLocal, outAlign);
outputQueue.FreeTensor(outLocal);
```

TQue 的 EnQue/DeQue 让编译器追踪 DMA 依赖，避免 TBuf 的依赖盲区。

## 跨管线同步模式

AscendC 有三个主要管线，各自独立：

```
PIPE_MTE2 — DMA 引擎：GM → UB（DataCopy 读进来）
PIPE_V    — 向量/标量引擎：GetValue/SetValue/Sub/Mul 等计算
PIPE_MTE3 — DMA 引擎：UB → GM（DataCopy 写出去）
```

不同管线之间**不自动同步**。必须显式声明依赖。

### 两种已知同步问题和修复

| 场景 | 管线 | 问题 | 修复 |
|------|------|------|------|
| DataCopy(UB→GM) 后循环内复用 buffer | MTE3→V | pipe_barrier 被编译器流水线忽略 | GetValue 建立读取依赖 |
| DataCopy(GM→UB) 后向量计算读数据 | MTE2→V | pipe_barrier 不保证 MTE2 完成 | SetFlag/WaitFlag MTE2_V |

### MTE2→V 依赖的正确写法（DataCopy GM→UB 后做向量计算）

官方 sample 推荐用 HardEvent：

```cpp
DataCopy(xLocal, xGm[offset], size);                   // MTE2 提交搬运
SetFlag<HardEvent::MTE2_V>(EVENT_ID0);                  // MTE2 完成后发信号
WaitFlag<HardEvent::MTE2_V>(EVENT_ID0);                 // V 管线等信号
Add(zLocal, xLocal, yLocal, size);                      // 现在向量计算安全
```

来源：`0_introduction/23_static_tensor_programming_kernellaunch`。

### pipe_barrier(PIPE_V) vs SetFlag/WaitFlag

| | pipe_barrier(PIPE_V) | SetFlag/WaitFlag MTE2_V |
|---|---|---|
| 语义 | 等 V 管线所有操作完成 | MTE2 完成后通知 V |
| 精度 | 粗粒度（全等） | 精准（只等特定事件） |
| 可靠性 | 大部分时候行，多核高负载下偶发漏 | 明确可靠 |
| 适用 | 简单场景、数据量小、负载轻 | 多核竞争、大数据量、出过问题 |

**经验**：GroupPoints 用 pipe_barrier 能工作（单次搬运 + 轻负载）。NMS 在 pose val 高负载下出问题，改用 SetFlag/WaitFlag 后修复。两者在不同场景下各有适用，出过问题就换 SetFlag/WaitFlag。
