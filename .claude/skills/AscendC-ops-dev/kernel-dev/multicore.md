# 多核 Dispatch 与跨核同步

**何时读此文件**：kernel 需要多核并行（ACLRT_LAUNCH_KERNEL），或需要跨核同步（SyncAll / GroupBarrier / CrossCoreSetFlag）。

## 多核 Dispatch

### kernel 启动方式

| 方式 | 结果 | 说明 |
|------|------|------|
| `<<<blockDim, nullptr, stream>>>` | **只有部分核执行** | 手动 `_do` 函数不触发正确的多核 dispatch |
| `ACLRT_LAUNCH_KERNEL(name)(blockDim, stream, ...)` | **全部核执行** | 自动生成的 `aclrtlaunch_xxx` 函数 |

**必须使用 `ACLRT_LAUNCH_KERNEL` 方式。**

### 设置步骤

1. 删除 kernel 文件末尾的手动 `_do` 函数
2. Host wrapper 添加 `#include "aclrtlaunch_xxx.h"`（编译时自动生成，在 `out/include/ascendc_kernels_npu/` 下）
3. CMakeLists.txt 添加：
   ```cmake
   target_include_directories(target_name PRIVATE
       ${CMAKE_CURRENT_BINARY_DIR}/out/include/ascendc_kernels_npu)
   ```
4. Host wrapper 调用：
   ```cpp
   ACLRT_LAUNCH_KERNEL(fps_custom)(NUM_CORES, stream, arg1, arg2, ...);
   ```

## 跨核同步

### SyncAll（310P3 正确用法）

来自官方 `0_introduction/16_unaligned_abs_kernellaunch/AbsDuplicateKernelInvocation` sample：

```cpp
// GM buffer: NUM_CORES * 8 个 int32_t
AscendC::GlobalTensor<int32_t> syncGm;
syncGm.SetGlobalBuffer((__gm__ int32_t *)sync, NUM_CORES * 8);

// UB buffer: 同大小
AscendC::TBuf<AscendC::TPosition::VECIN> syncBuf;
pipe.InitBuffer(syncBuf, NUM_CORES * 8 * sizeof(int32_t));
auto syncLocal = syncBuf.Get<int32_t>();

// 调用（3 参数版）
AscendC::SyncAll(syncGm, syncLocal, NUM_CORES);
```

SyncAll buffer 要求：
- GM: `NUM_CORES * 8` 个 `int32_t`（最小 64 字节）
- UB: 同大小，通过 `TBuf` 分配
- 必须是 `int32_t` 类型

### SyncAll Buffer 必须每次清零（关键）

**实测发现**：kernel 完成后 syncGm 残留上一次 SyncAll 的同步标志。当 kernel 在 torch_npu 操作后运行时（如 PointNet2 Conv2D 后），AICore 的 GM 缓存状态使残留标志对新一轮 SyncAll 可见，导致 SyncAll 误判同步状态而死锁（aicore timeout 507014）。

**表现**：kernel 单独测试正常，跑完一轮包含 Conv2D/BN/MaxPool 的网络后再次调用就挂。

**修复**：host wrapper 在每次 `ACLRT_LAUNCH_KERNEL` 前清零 sync buffer：
```cpp
int32_t zeros[MAX_CORES * 8] = {0};
aclrtMemcpy(g_sync_buf, sizeof(zeros), zeros, sizeof(zeros), ACL_MEMCPY_HOST_TO_DEVICE);
aclrtlaunch_fps_custom(num_cores, stream, ...);
```

### OM / static OM 下：没有 host 清时机 → kernel 内清 + 防 DCE（关键）

ctypes/eager 路可以在 host launch 前清 sync buffer（见上）。但**走 static OM（torch→ONNX→ATC→OM→ACL）时没有 host 介入点**——OM 图执行直接 launch 编译好的 kernel，workspace 的 sync 区初始可能是脏的 → 多核 SyncAll 撞 stale flag → 死锁 / aicore timeout（507011 / hwts timeout 0x25）。

**单核算子没事**（numCores=1 时 SyncAll 平凡），**多核必崩**。这是"ctypes 多核能跑、塞进 OM 就崩"的根因。

#### 修复①：kernel 内清 sync

把 host 的"清 sync"搬进 kernel `Process()` 开头，每个核独立把整个 sync 区清零（用 `Duplicate`+`DataCopy`，只靠核内 `pipe_barrier`，不碰 SyncAll，避开"清需要跨核可见、可见又靠 SyncAll"的鸡生蛋）：

```cpp
// Process() 开头，主循环之前
AscendC::Duplicate(syncLocal, (int32_t)0, numCores * 8);   // UB 清零
pipe_barrier(PIPE_V);
AscendC::DataCopy(syncGm, syncLocal, numCores * 8);        // 写回 GM sync 区
pipe_barrier(PIPE_V);
```

等价于把 ctypes 的 "host launch 前清" 搬进 kernel 首部。

#### 修复②（必做）：DCE-defeat —— 否则编译器把清零当死代码删掉

**这是最隐蔽的一坑，光做修复①没用。** AscendC 编译器的 DCE（dead code elimination）会删掉 destination 没被"显式 compute 消费"的 DataCopy。这里的 `DataCopy(syncGm, ...)` 只被 `SyncAll` 读，而 **SyncAll 对编译器不透明**（它内部读 syncGm 的事实编译器看不到）→ 编译器判定 syncGm 写无副作用 → **DCE 删掉整段清零** → 多核照崩。

症状极误导：用**预编译 `.o`**（`make <Op>_ascend310p`，ccec 不做激进 DCE）单算子跑通；但 OM 走 **ATC JIT** 编译的 kernel 还崩——同源码同清零，JIT 把清零优化没了。症状是 OM eval 里多核 aicore timeout，但单算子单独跑没事。

**修复（DCE-defeat）**：清零后**显式读回 syncGm 并假性消费**，建立编译器看得见的数据依赖：

```cpp
AscendC::DataCopy(syncGm, syncLocal, numCores * 8);
pipe_barrier(PIPE_V);
int32_t zero_check = syncGm.GetValue(0);                  // 读回 syncGm → 清零不再是死代码
if (zero_check != 0) { idxLocal.SetValue(npoints - 1, zero_check); }  // 假性消费：清零后恒 0，永不执行，但 pin 住依赖
```

`GetValue` 让 syncGm 有了显式读者，编译器不能删清零。**实测**：加 DCE-defeat 后 OM 多核 SyncAll 不再崩，全量 eval 跑通（3488 帧不崩）。

> 依据（websearch + 实测）：AscendC 文档与 DCE 通用理论都印证"destination 无 compute 消费的 DataCopy 会被删，SyncAll 不建立数据依赖"（[DCE](https://en.wikipedia.org/wiki/Dead-code_elimination)、[AscendC 搬运优化](https://www.hiascend.com/developer/techArticles/20241107-1)）。genmitigate：① 让 destination 被 compute 消费；② 用 SetFlag/WaitFlag 建依赖。GetValue 读回是①的最小实现。

### GroupBarrier（替代方案）

来自官方 `2_features/16_group_barrier` sample，适用于生产者-消费者模式：

```cpp
// 生产者
AscendC::GroupBarrier<MTE3_MODE>::Arrive();
// 写入 GM 数据...

// 消费者
AscendC::GroupBarrier<MTE3_MODE>::Wait();
// 读取 GM 数据...
```

### CrossCoreSetFlag/WaitFlag

来自官方 `4_best_practices/6_group_matmul` sample，用于 AIC↔AIV 核内同步（910B 等多 die 芯片）。
