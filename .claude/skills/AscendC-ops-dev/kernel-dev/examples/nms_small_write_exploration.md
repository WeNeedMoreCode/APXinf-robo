# NMS 多核并发小数据 GM 写入探索记录

## 背景

NMS kernel 采用 embarrassingly parallel 模式：8 核各处理 1 张图（B=8），无 SyncAll。每核完成 NMS 后需向 GM 写入两个输出：
1. 保留的 box 索引数组（几百个 int32，数据量大）
2. 保留数量 keepCount（1 个 int32，数据量小）

问题出在第 2 项：per-core keepCount 的写入。

## 已有算子的对比

| 算子 | 数据量 | 同步手段 | 结果 |
|------|--------|---------|------|
| FPS | 小（8 个 float） | SyncAll 串行化写入 | PASS |
| GroupPoints | 大（几千个 float） | 无 SyncAll | PASS |
| BallQuery | 大（向量化输出） | 无 SyncAll | PASS |
| **NMS V1** | **小（8-16 个 int32）** | **无 SyncAll** | **FAIL** |

差异点：NMS 是唯一需要"多核并发写入小数据且无 SyncAll"的算子。

## 症状

- B=1（单核）：全部 PASS，count 值正确
- B=8（多核）：间歇性 FAIL，不同 image 每次随机失败
- 垃圾 count 值：如 1141330736, 1132324404 等，转成 float 后在 [0, 640] 范围内（box 坐标值）
- NMS 索引本身正确（sorted indices 匹配 torchvision），只有 count 是垃圾

诊断特征：**B=1 通过、B=8 间歇性失败、垃圾值是 float 坐标、每次随机哪个 image 失败**——这是多核并发小数据写入问题的标准模式。

## 尝试过的路径

### 路径 1：TBuf + coreIdx*8 stride（32 字节）

```cpp
outCountGm.SetGlobalBuffer(outCounts + coreIdx * 8, 8);
Duplicate(countLocal, keepCount, 8);
DataCopy(outCountGm, countLocal, 8);
```

结果：B=8 间歇性 FAIL。N=400/600/800/1000 均出现垃圾 count。

### 路径 2：TBuf + coreIdx*16 stride（64 字节）

假设 DMA 写入粒度为 64 字节，相邻 32 字节写入落在同一 cache line 导致 read-modify-write 竞争。

```cpp
outCountGm.SetGlobalBuffer(outCounts + coreIdx * 16, 16);
Duplicate(countLocal, keepCount, 16);
DataCopy(outCountGm, countLocal, 16);
```

结果：仍然 FAIL。stride 64 字节未解决问题，DMA 粒度理论排除。

### 路径 3（有效）：TQue + SetAtomicAdd

对齐官方 sample 模式（reduce_min, group_barrier, vectoradd）：

```cpp
// TQue 管理输出依赖
auto outputIdx = outputQueue.AllocTensor<int32_t>();
// ... NMS loop ...
outputQueue.EnQue<int32_t>(outputIdx);
auto outLocal = outputQueue.DeQue<int32_t>();
DataCopy(outputGm, outLocal, outAlign);
outputQueue.FreeTensor(outLocal);

// SetAtomicAdd 保护并发 count 写入
SetAtomicAdd<int32_t>();
DataCopy(outCountGm, countLocal, 16);
SetAtomicNone();
```

结果：B=8 全部 match=True，N=200/400/600/800/1000 均通过。

性能：kernel ~3ms（vs V1 的 ~2.8ms），SetAtomicAdd 开销约 +8%。speedup 仍从 1.23x (N=200) 增长到 4.71x (N=1000)。

## 根因分析（假设，未验证）

垃圾值是 float box 坐标而非 keepCount，说明 DataCopy 读取的 UB 数据不是 Duplicate 写入的 keepCount。可能原因：

1. 编译器在 TBuf 模式下对 Duplicate → DataCopy 的依赖追踪不完整，导致 DataCopy 读到 boxesBuf 残留数据
2. 多核并发时 DMA 引擎对小数据量传输的处理与大数据量不同

均未进一步验证。有效路径已找到（SetAtomicAdd + TQue），根因定位的 ROI 不高。

## 教训

1. **官方 sample 是可靠的参考**。出现多核写入问题时，先查 sample 中类似场景（reduce_min, group_barrier）的写法，而不是自己摸索 stride/alignment。
2. **B=1 vs B=8 对比是定位多核问题的标准手段**。单核通过但多核间歇性失败，几乎可以确定是并发写入问题。
3. **记录"什么没通过"比猜测"为什么没通过"更有价值**。我们尝试了 stride 32B 和 64B 都没通过，这个事实比"DMA 粒度是 64B"的推理更有指导意义。
