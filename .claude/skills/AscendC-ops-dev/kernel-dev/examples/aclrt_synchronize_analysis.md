# aclrtSynchronizeStream 实测分析

> 基于 GenPose2 项目（Ascend 310P3）的 Ball Query / GroupPoints / FPS 多核算子实测
> 根因未确认，以下记录事实和假设

## 结论

Host wrapper 中 `aclrtlaunch` 后必须加 `aclrtSynchronizeStream(stream)`。三个算子统一加 synchronize 后无性能损失。

## 事实

### Ball Query：去掉 synchronize 导致 tracking 模式严重退化

| 场景 | 无自定义算子 | 有自定义算子（无 synchronize） | 有自定义算子（有 synchronize） |
|------|-------------|------------------------------|------------------------------|
| 逐样本串行推理（tracking） | 700ms | 1100ms（慢 57%） | 160ms（快 4.4x） |
| 分阶段批处理（single） | 800ms | 200ms（快 4x） | 未单独测（200ms） |

- tracking：每样本走完整个模型（score → energy → scale）再处理下一个样本
- single：所有样本先走完 score 阶段，再走 energy 阶段，再走 scale 阶段

### GroupPoints：加不加 synchronize 无差异

- 精度：正确性测试 PASS（无/有 synchronize 均通过）
- 性能：加 synchronize 后无性能损失（159ms vs 161ms，正常浮动）
- 可能精度有微弱提高（未定量确认）

### FPS：始终有 synchronize

FPS host wrapper 因 SyncAll 需要 sync buffer 清零，始终包含 `aclrtSynchronizeStream`。

### 三个算子统一加 synchronize 后

- tracking：160ms（比无自定义算子的 700ms 快 4.4x）
- single：200ms（比无自定义算子的 800ms 快 4x）

## Host Wrapper 代码模式

```cpp
// kernel launch 后必须同步
aclrtlaunch_xxx_dynamic(num_cores, stream, ..., g_tiling_buf);
aclrtSynchronizeStream(stream);
return 0;
```

## 假设（未确认）

### 假设 1：aclrtMemcpy 不走 stream 队列

`aclrtMemcpy`（H2D）直接写 GM，不经过 stream 队列。如果两次 host wrapper 调用紧邻，第二次的 `aclrtMemcpy` 可能在第一次的 kernel 读 tiling buffer 之前就覆盖了它。

**为什么不能解释全部现象**：
- GroupPoints 和 Ball Query 的 host wrapper 结构完全一样，都只有一个 static `g_tiling_buf`
- 如果是 tiling buffer 竞态，GroupPoints 也应该受影响，但实测不受影响
- single 模式下 Ball Query 也不受影响，但 single 也有连续调用

### 假设 2：执行模式差异

tracking 模式下 NPU 利用率更高、调用间隔更短，触发了某种资源竞争或调度异常。single 模式下 CPU 密集的 ODE 采样（scipy，数百 ms）给 NPU 留了足够的空闲时间。

**为什么不能完全确认**：
- 无法解释为什么只有 Ball Query 受影响而 GroupPoints 不受
- 没有单独测量 Ball Query kernel 在两种模式下的执行时间

## 后续验证方向（如需深入）

1. 测量 Ball Query 和 GroupPoints kernel 的执行时间差异
2. 在 single 模式下人为缩短调用间隔（去掉 ODE 采样），观察是否复现退化
3. 用独立小 buffer 替代 static `g_tiling_buf`（每次调用动态分配），观察是否解决问题
4. 用 `aclrtMemcpyAsync`（走 stream）替代 `aclrtMemcpy`（同步），观察行为变化
