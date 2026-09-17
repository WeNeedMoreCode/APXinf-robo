# ACL Context 管理：OM + torch_npu 同进程混合

## 什么时候读这个文件

出现以下任意一种情况：

- `LaunchAscendKernel ret 107003` 或 `rtKernelLaunchWithHandle ... stream is not in current ctx`
- 进程退出时报 `Stream destroy failed, stream is not in current ctx`
- 自定义 NPU 算子（AscendC kernel）在 OM 推理之后突然失效或输出全错
- 同进程里既有 `ais_bench.InferSession` 又有 `torch_npu` 或自定义 NPU kernel

---

## 症状 → 根因

### 症状 1：推理中途刷屏 `LaunchAscendKernel ret 107003`

```
LaunchAscendKernel ret 107003
LaunchAscendKernel ret 107003
...
iou_mean: 0.10  ← 精度坏掉
```

自定义 NPU 算子（AscendC kernel）launch 失败。算子 stream 属于 torch_npu 创建的 context，但当前线程的 runtime context 已经被 `InferSession.infer()` 切到 OM 自己的 context。算子 launch 时找不到自己的 stream → 107003。

### 症状 2：进程退出时 segfault + stream 错误

```
Stream destroy failed, stream is not in current ctx, stream_id=XX
Segmentation fault (core dumped)
```

atexit 清理时，torch_npu 尝试销毁 stream，但当前 context 不是 torch_npu 的。这是推理过程中 context 反复切换遗留的问题，通常不影响推理结果，只影响进程优雅退出。

### 根因机制

ais_bench 的 `DeviceManager::CreateContext` 逻辑：

```cpp
if (contexts_[deviceId].empty() && !repeatInitAclFlag) {
    aclrtGetCurrentContext(&newContext);  // 第一个 session：复用 torch_npu 的 context
} else {
    aclrtCreateContext(&newContext, deviceId);  // 后续 session：新建独立 context
}
```

- 第一个 `InferSession` 复用 torch_npu 的 context（同一个 handle）
- 后续 `InferSession` 创建自己的 context
- 每次 `InferSession.infer()` 内部会 `set_context(self.context)`，**infer 不会恢复原来的 context**
- infer 之后当前 context = 最后一个 InferSession 的 context
- torch_npu 的 op / 自定义 NPU kernel 用的是 torch_npu 的 context → 不匹配 → 107003

---

## 正确的 Context 管理模式

### 核心三步

```python
import acl
import torch_npu
from ais_bench.infer.interface import InferSession

# 1. 强制 torch_npu 创建 context（lazy init，否则 get_context 拿到 null）
torch.npu.set_device("npu:0")

# 2. 在任何 InferSession 创建之前，保存 torch_npu 的 context
pta_context, ret = acl.rt.get_context()
# 此时 current context = PTA 的，还没有 InferSession 改变它

# 3. 创建 InferSession（第一个会复用 PTA context，后续的会新建）
session = InferSession(device_id, model_path)

# 之后每次 infer 之后，恢复 PTA context
result = session.infer([inputs])
acl.rt.set_context(pta_context)  # ← 恢复，让后续 torch_npu op / 自定义 kernel 能正常 launch
```

### 关键时序约束

| 步骤 | 必须在什么时候做 |
| --- | --- |
| `torch.npu.set_device(device)` | `acl.rt.get_context()` **之前**。否则 context 还没创建，get 返回 null |
| `acl.rt.get_context()` 保存 PTA context | 第一个 `InferSession(...)` **之前**。之后 current context 已经被 ais_bench 改变 |
| `acl.rt.set_context(pta_context)` 恢复 | 每次 `session.infer()` **之后**。infer 不恢复，留给调用方做 |

### 常见错误

| 错误 | 后果 |
| --- | --- |
| 只 `import torch_npu` 没 `set_device` 就 get_context | PTA context 还没创建，保存 null，后续 restore 无效 |
| 在 InferSession 创建之后才 get_context | 拿到的是 InferSession 的 context，不是 PTA 的 |
| 只在进程启动时 restore 一次 | 第一次 infer 之后 context 又被切走，第二次 torch_npu op 又 107003 |
| `try/finally` 里 restore 但 forget 某些异常路径 | 偶发 107003 |
| **restore 按输入设备做条件**（"输入在 NPU 才 restore"） | 换 context 的是 aclruntime，与输入设备无关——全 CPU 输入的调用同样切走 context。Diffusion-Planner 的整循环图调用（循环状态全 host 侧）漏 restore，下一步第一个 torch kernel 107003；DUO 的 torch_npu 每次调用自设 context 掩盖了它，RC 现形。restore 无条件做 |
| **`import torch_npu` / `import acl` 晚于第一个 InferSession** | 进程里先后加载两份 libprotobuf（pyACL、torch_npu 各带一份），混链直接 abort：`libprotobuf FATAL CHECK failed: file != nullptr`。DUO 上碰巧无害、RC 上必崩。铁律顺序：`import torch_npu` → `import acl` → 第一个 `InferSession`——闭环进程天然如此，独立脚本/benchmark 最容易写反 |
| 多模型串测时对每个 session `free_resource()` | 第一个 InferSession 复用的是 PTA context（见下"根因机制"），free 会把它一起拆掉，之后所有 torch op 报 ctx NULL。短命进程直接让运行时退出清理 |

---

## 完整封装：OMRunner

把 save/restore 收敛到一个类里，避免散落到处：

```python
import acl
import torch_npu
from ais_bench.infer.interface import InferSession


class OMRunner:
    """单 OM session + context 自动恢复。

    使用前必须已 torch.npu.set_device(device)，否则 PTA context 不存在。
    """

    _pta_context = None  # 进程级单例，第一个 OMRunner 实例负责保存

    def __init__(self, model_path, device_id=0):
        # 首次创建时保存 PTA context（必须在此之前已 set_device）
        if OMRunner._pta_context is None:
            OMRunner._pta_context, _ = acl.rt.get_context()

        self.session = InferSession(device_id, model_path)
        # InferSession 可能改了 current context，恢复回来
        acl.rt.set_context(OMRunner._pta_context)

    def infer(self, inputs):
        """infer 前后自动管理 context。返回 numpy list。"""
        result = self.session.infer(inputs)
        acl.rt.set_context(OMRunner._pta_context)  # 恢复给后续 torch_npu op 用
        return result
```

多个 `.om` session 各自创建自己的 OMRunner 实例，共享同一个 `_pta_context`。

---

## 特殊场景：自定义 NPU 算子（AscendC kernel）

自定义 NPU 算子（AscendC kernel、第三方编译的 `.so`）launch 时需要 current context = 创建该算子 stream 的 context（通常是 PTA 的）。

如果推理流程是「OM infer → 自定义算子 → OM infer → 自定义算子」交替，必须在**每次** OM infer 之后 restore：

```python
for layer in layers:
    acl.rt.set_context(pta_context)         # 给自定义算子用
    feat = custom_kernel(feat)              # AscendC kernel launch
    feat_om = om_session.infer([feat])      # OM infer，切走 context
    acl.rt.set_context(pta_context)         # 恢复，给下一轮自定义算子用
    feat = process(feat_om)
```

只做一次 restore 不够——每次 infer 都会切走。

---

## 什么时候不需要 context 管理

满足以下**全部**条件可以不做：

- 进程里没有 `torch_npu`（纯 OM + numpy 进出）
- 没有自定义 NPU 算子
- 不在 OM 输出后做 NPU tensor 计算

这种情况下 ais_bench 自己管 context 就够了，torch_npu 不介入，不会冲突。

一旦引入 torch_npu（哪怕是 `.to('npu:0')` 这种小操作）或自定义 NPU kernel，就必须做 context 管理。

---

## 对比：UVDoc 模式

UVDoc 项目（`ACL_PyTorch/built-in/ocr/UVDoc/diff_uvdoc.patch`）是这个模式的参考实现：

```python
torch.npu.set_device("npu:0")
context, ret = acl.rt.get_context()           # save
model = InferSession(device_id, ckpt_path)    # 可能改变 current context

for batch in dataloader:
    result = model.infer([batch])             # infer 切走 context
    acl.rt.set_context(context)               # 恢复
    tensor = torch.from_numpy(result).to(device)  # torch_npu op 正常
```

要点：set_device → get_context → InferSession，这个顺序不能乱。

---

## 排查 checklist

遇到 107003 或 stream 相关错误，按顺序检查：

1. **是否需要 context 管理**：进程里有没有 `torch_npu` 或自定义 NPU kernel？有 → 必须做
2. **save 时机对不对**：`get_context` 是不是在 `set_device` 之后、第一个 `InferSession` 之前？
3. **save 拿到的 context 是否为 null**：打印 `_pta_context` 看看
4. **restore 是否在每次 infer 之后**：不能只 restore 一次
5. **restore 是否无条件**：不得按"本次输入在哪个设备"做条件（见常见错误表）
6. **import 顺序**：`torch_npu`、`acl` 是否都在第一个 `InferSession` 之前（protobuf 混链 abort）
7. **自定义算子路径是否漏 restore**：交替调用 OM 和 kernel 时，每次 infer 后都要 restore
8. **退出时的 stream 报错**：通常是 atexit 清理顺序问题，不影响推理结果，可以忽略或通过不主动 free_resource 来规避；多模型串测同理不要 mid-run free
