# 向量化循环型算子范例：NMS

## 算子特征

多核各跑一个**串行循环**（每步依赖上一步的 mask 更新），循环内部用**向量化 API** 加速批量计算。与 FPS 的区别：每核完全独立处理一张图，无跨核同步。

```
核 0: 读 boxes[0] → 串行 NMS 循环（向量化 IoU）→ 写 output[0]
核 1: 读 boxes[1] → 串行 NMS 循环（向量化 IoU）→ 写 output[1]
...
```

适用场景：NMS、top-k 排序、逐步淘汰型算法，且每个实例独立处理。

## 三轮优化过程

### 第一轮：基础实现

**算法**：标准 NMS — 每轮找最高分 box，计算 IoU 淘汰重叠 box。

**实现**：
- 每核读 `[N, 4]` boxes，标量循环 deinterleave 到 ix1/iy1/ix2/iy2
- NMS 循环内向量化 IoU：Maxs/Mins/Sub/Mul/Compare/Select（一次算 N 个 IoU）
- 结果：正确性通过，单核 1x，8 核 ~3x speedup

**瓶颈**：NMS 每轮需要 O(N) argmax 找最高分，argmax 在 AscendC 中需要完整的向量 Reduce + GetValue，约 6 步向量操作。

### 第二轮：预排序消除 argmax

**优化思路**：Python 端预先按 score 降序排列 boxes，kernel 按顺序扫描，不需要每轮找最大值。

```
原来：每轮 O(N) argmax + O(N) IoU = O(N²) 总体
优化：预排序 O(N log N) + 顺序扫描 O(N) IoU = 仍 O(N²) 但常数更小
```

**影响**：kernel 时间从 N 相关变为近似常数（~3ms），因为预排序消除了每轮的 argmax 开销。但引入了 Python 端 argsort + gather 的 ~0.15ms 固定开销。

### 第三轮：数据布局优化 + 多核修复

**问题 1**：标量 deinterleave 循环（N×4 次 GetValue/SetValue）浪费 ~0.3ms。

**修复**：Python 端 transpose boxes 从 `[B, N, 4]` 到 `[B, 4, N]`，kernel 用 4 个 DataCopy 直接读 4 个通道：

```cpp
// 替代标量循环
DataCopy(ix1, ix1Gm, channelAlign);   // 直接读第 0 列
DataCopy(iy1, iy1Gm, channelAlign);   // 直接读第 1 列
DataCopy(ix2, ix2Gm, channelAlign);   // 直接读第 2 列
DataCopy(iy2, iy2Gm, channelAlign);   // 直接读第 3 列
pipe_barrier(PIPE_V);
```

**问题 2**：TBuf 多核并发写小数据（per-core count）间歇性失败（B=1 通过，B=8 随机 image 垃圾值）。

**修复**：TQue 管理输出 + 移除有问题的 TBuf count 写入。详见 [NMS 小数据并发写入探索](nms_small_write_exploration.md)。

**最终性能**：

| N | torchvision*8 | AscendC 8核 | speedup |
|---|--------------|------------|---------|
| 200 | 3.24ms | 2.66ms | 1.22x |
| 400 | 5.21ms | 2.96ms | 1.76x |
| 600 | 7.53ms | 2.73ms | 2.76x |
| 800 | 10.66ms | 2.79ms | 3.83x |
| 1000 | 14.32ms | 2.85ms | **5.03x** |

kernel 时间 ~2.7-2.9ms 基本不随 N 增长，speedup 随 N 线性增长。

## 关键技术模式

### 1. 预排序优化

当算法每轮需要"找最优元素"时，预排序可以将 O(N) 查找变成 O(1) 顺序取。代价是 Python 端的排序开销。适用于：
- NMS（每轮取最高分）
- Top-k（取前 k 个）
- 贪心算法（每轮取最优）

判断标准：如果排序开销 < 消除的 per-iteration 查找开销总和，就值得做。

### 2. 转置输入消除标量 deinterleave

当 kernel 需要将 `[N, C]`（行主序）拆成 C 个独立向量时：

```
方案 A：读 [N, C] → 标量循环 deinterleave → C 个向量 buffer
方案 B：Python transpose 到 [C, N] → kernel 4 个 DataCopy 直接读
```

方案 B 消除了标量循环，性能提升 10-20%。适用于 C 较小（4-8）且 N 较大（>200）的场景。

### 3. 向量化 IoU 批量计算

对 picked box 与所有 N 个 box 同时计算 IoU：

```cpp
// 一次算 N 个 interX1 = max(px1, all_ix1)
Maxs(t0, ix1, px1, NAlign);
Mins(t1, ix2, px2, NAlign);
// ... interW, interH, interArea, unionArea ...
Compare(cmpMask, interArea, threshUnion, CMPMODE::LE, NAlign);
Select(mask, cmpMask, mask, 0.0f, SELMODE::VSEL_TENSOR_SCALAR_MODE, NAlign);
```

12 步向量操作 + 10 个 pipe_barrier，一次处理 N 个 box。比标量循环快 ~10x。

### 4. TQue 管理多核输出

多核并发写输出时，TQue 的 EnQue/DeQue 让编译器正确追踪 DMA 依赖：

```cpp
auto outputIdx = outputQueue.AllocTensor<int32_t>();
// ... 写 outputIdx ...
outputQueue.EnQue<int32_t>(outputIdx);
auto outLocal = outputQueue.DeQue<int32_t>();
DataCopy(outputGm, outLocal, outAlign);
outputQueue.FreeTensor(outLocal);
```

比 TBuf + Duplicate + DataCopy 更可靠（后者在多核小数据写入时出过问题）。

## 教训

1. **算法优化优先于代码优化**。预排序消除了 argmax，比优化 argmax 实现的收益大一个数量级。
2. **数据布局影响计算效率**。标量 deinterleave 的存在说明输入布局不匹配计算需求。改变布局比优化标量循环更有效。
3. **多核问题用 B=1 vs B=8 对比定位**。单核通过但多核间歇性失败，几乎确定是并发写入问题。
4. **官方 sample 是并发写入的可靠参考**。SetAtomicAdd 和 TQue 是官方验证过的模式，自己摸索 stride/alignment 是浪费时间。

## 未走通的优化：iArea 预计算

### 目标

将 NMS 循环内每轮重复计算的 `allBoxArea = (ix2-ix1)*(iy2-iy1)` 提取到循环外预计算一次，预期节省 3 步向量操作 + 2 个 pipe_barrier。

### 尝试路径

#### 路径 A：新增独立 TBuf（kernel 挂死）

在已有 buffer 列表基础上新增 `pipe.InitBuffer(iAreaBuf, NAlign * sizeof(float))`，循环外预计算 iArea，循环内用 `Adds(t0, iArea, pArea)` 替代原来的 `Sub+Sub+Mul+Adds`。

结果：kernel 直接挂死（无输出、不返回），N=200 即挂。新增一个 buffer 就挂，推测与 310P3 UB 容量有关，但未验证根因。

#### 路径 B：复用 tempBuf[3*NAlign] 存 iArea，循环内不再使用 t3（正确性失败 + 严重退化）

将 iArea 存到 `tempBuf[3*NAlign]`，循环内只用 t0/t1/t2（3 个 slot）。需要重组 IoU 计算步骤：拆分 interX 和 interY 的计算，用 3 个临时变量完成原本 4 个变量的工作。

结果：
- **性能严重退化**：N=200 从 2.76ms → 25.26ms，N=600 从 2.85ms → 457.15ms
- **正确性失败**：N=600 出现 count mismatch（tv=270 vs ac=258）
- 原因：重组后的 barrier 分组中出现多步 RAW（read-after-write）依赖链（如 `Sub → Maxs → Mul` 在同一 group 内连续写读同一 buffer），编译器插入大量 stall 并产生不正确的结果

#### 路径 C：复用 tempBuf[3*NAlign] 但循环内仍使用 t3（实现 bug）

iArea 存在 `tempBuf[3*NAlign]`，循环内第一轮 `Mins(t3, iy2, py2)` 覆盖了 iArea，后续轮次读到垃圾值。

结果：kernel 挂死。

### 结论

iArea 预计算是正确的优化思路，但在此场景下未能找到可行的实现路径。路径 A 新增 buffer 导致挂死（推测 UB 容量不足，未验证），路径 B 重组 barrier 导致性能退化和正确性问题，路径 C 是实现 bug。
