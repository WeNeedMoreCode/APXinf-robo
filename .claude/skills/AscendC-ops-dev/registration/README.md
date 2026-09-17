# 注册 AscendC kernel 为 torch op（接入 torch.compile/TorchAir）

## 什么时候读这个文件

已有 AscendC kernel（通过 ctypes 或 NpuExtension launch），要用 `torch.compile(..., backend=torchair)` 把上层模型编进图，但遇到以下任一症状：

- `torch._dynamo.exc.Unsupported: call_method UserDefinedObjectVariable(...) __call__`
- `Dynamic control flow is not supported at the moment`（来自 kernel wrapper 里的 `assert xyz.is_npu`）
- `undefined symbol: _ZN3c106detail14torchCheckFail...`（加载 .so 时）

根因：dynamo 不能 trace 进 ctypes/C++ 扩展的 Python wrapper。修法是把 kernel 注册成 `torch.ops.<ns>::<name>`，让 dynamo 把它当图节点（配合 Meta 实现推断输出 shape，不 trace 进实现）。

---

## 总体思路

```
AscendC kernel (.cpp)
    ↓ AscendC toolkit 编译
lib<kernel>_host.so  (导出 extern "C" launch 函数)
    ↓ 加一层 C++ torch wrapper (TORCH_LIBRARY 注册)
lib<op>_torch_op.so  (注册成 torch.ops.npu.<name>)
    ↓ Python load_library + register Meta
torch.ops.npu.<name>(...) 可在 eager 和 torch.compile 里用
```

不重写 kernel，只在现有的 `.so` 之上加一层薄的 torch op wrapper。

---

## 三件套

### 1. C++ wrapper（`<op>_torch_op.cpp`）

**核心模式**：用 `OpCommand::RunOpApi` 包裹 kernel launch，让它进入 torch_npu 的 op 队列，与 `at::` 操作（zeros、to、cast 等）自动按序执行。这是从 op-plugin 官方示例（`examples/cpp_extension/csrc/host/utils.h`）复刻的模式，实测验证通过。

```cpp
// Force old ABI to match torch_npu's libc10.so
// NpuExtension ignores extra_compile_args, so define in source
#undef _GLIBCXX_USE_CXX11_ABI
#define _GLIBCXX_USE_CXX11_ABI 0

#include <torch/extension.h>
#include <ATen/ATen.h>
#include <stdexcept>
#include "acl/acl.h"
// ⚠️ 正确路径是 torch_npu/csrc/.../，不是 c10/npu/...
#include "torch_npu/csrc/core/npu/NPUStream.h"
#include "torch_npu/csrc/framework/OpCommand.h"

// Linked via -l<kernel>_host_dynamic
extern "C" int <kernel_run>(void *in_ptr, void *out_ptr, ..., void *stream_ptr);

namespace {

at::Tensor run_<op>(const at::Tensor &input, /* extra args */)
{
    // ❌ 不要用 xyz.is_npu() — C++ ATen 没这个方法
    if (input.device().type() != c10::DeviceType::PrivateUse1)
        throw std::runtime_error("input must be on NPU");

    // ❌ 不要用 TORCH_CHECK — 它引用 c10::detail::torchCheckFail
    if (input.scalar_type() != at::kFloat)
        throw std::runtime_error("input must be float32");

    at::Tensor output = at::zeros({...}, input.options().dtype(at::kInt));
    aclrtStream stream = c10_npu::getCurrentNPUStream().stream(false);

    // ⚠️ OpCommand 可能推迟执行 lambda 到 flush 时，**必须值捕获**
    at_npu::native::OpCommand::RunOpApi("<op>",
        [input, output, ..., stream]() -> int {
            int ret = <kernel_run>(
                input.data_ptr(), output.data_ptr(), ..., stream);
            if (ret != 0)
                throw std::runtime_error("kernel failed: ret=" + std::to_string(ret));
            return 0;
        });

    return output.to(at::kLong);
}

} // namespace

TORCH_LIBRARY_FRAGMENT(npu, m)
{
    m.def("<op>(Tensor input, ...) -> Tensor");
}

TORCH_LIBRARY_IMPL(npu, PrivateUse1, m)
{
    m.impl("<op>", run_<op>);
}
```

### 2. setup.py（NpuExtension 编译）

```python
import os
import torch
from setuptools import setup
from torch_npu.utils.cpp_extension import NpuExtension

KERNEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "<kernel_dir>")
LIB_DIR = os.path.join(KERNEL_DIR, "out", "lib")

setup(
    name="<op>_torch_op",
    ext_modules=[
        NpuExtension(
            name="<op>_torch_op",
            sources=["<op>_torch_op.cpp"],
            include_dirs=[KERNEL_DIR],
            library_dirs=[LIB_DIR],
            libraries=["<kernel>_host_dynamic"],
            # ❌ NpuExtension 不传 extra_compile_args 给 g++，
            #    所以 ABI flag 必须写在 .cpp 源文件顶部
            extra_link_args=["-Wl,-rpath," + LIB_DIR],
        )
    ],
)
```

### 3. Python 加载 + Meta 注册（`register_meta.py`）

```python
import os
import glob
import torch
import torch_npu  # noqa
from torch.library import Library, impl


def load_<op>_torch_op():
    so_dir = os.path.dirname(os.path.abspath(__file__))
    # Build 产出 <op>_torch_op.cpython-XXX-XXX.so（带 tag），用 glob 匹配
    candidates = glob.glob(os.path.join(so_dir, "<op>_torch_op*.so"))
    if not candidates:
        raise FileNotFoundError(
            f"Run `python setup.py build_ext --inplace` first.")
    torch.ops.load_library(candidates[0])

    # torch 2.1 没有 torch.library.register_fake，用 Library("Meta") + @impl
    m = Library("npu", "IMPL", "Meta")
    @impl(m, "<op>")
    def _<op>_meta(input, ...):
        return torch.empty(input.shape[0], ..., dtype=torch.int64, device=input.device)
```

---

## 踩过的坑（全部实测验证）

### 坑 1：ABI 不匹配 → undefined symbol torchCheckFail

**症状**：`torch.ops.load_library` 时报
```
OSError: undefined symbol: _ZN3c106detail14torchCheckFailEPKcS2_jRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE
```

**根因**：`.so` 用 CXX11 ABI 编译（`std::__cxx11::basic_string`），torch_npu 的 libc10.so 用老 ABI。两者 `std::string` 符号 mangling 不同。

**修复**：`.cpp` 顶部（所有 `#include` 之前）加：
```cpp
#undef _GLIBCXX_USE_CXX11_ABI
#define _GLIBCXX_USE_CXX11_ABI 0
```

**为什么不用 setup.py 的 `extra_compile_args=['-D_GLIBCXX_USE_CXX11_ABI=0']`**：实测 `NpuExtension` 不把这个 kwarg 传给 g++（build 命令里看不到 flag）。必须写在源文件。

**怎么确认 torch 用哪个 ABI**：
```bash
python -c "import torch; print(torch.compiled_with_cxx11_abi())"
# False → 老 ABI（torch_npu 常见）→ define 0
# True  → CXX11 ABI → define 1
```

> ⚠️ **版本演进（2026-07 实测补充）**：上面"必须源码硬编码"写于 torch_npu 2.1（NpuExtension 不把 extra_compile_args 传给 g++）。torch 升级到 2.10（`compiled_with_cxx11_abi()=True`）后，源码硬编码 `#define _GLIBCXX_USE_CXX11_ABI 0` 会**过时**——.so 用 old ABI 编、torch 用 new ABI，`torch.ops.load_library` 时报 undefined symbol（典型：`torch::jit::parseSchema`，old-ABI 的 `Ss` mangling 对不上 new-ABI 的 `NSt7__cxx11...`）。修法：**源码不要硬编码 ABI**，让 setup.py 的 abi_flag 动态控制——
> ```python
> abi_flag = '-D_GLIBCXX_USE_CXX11_ABI=' + str(int(torch.compiled_with_cxx11_abi()))
> ```
> 新版 NpuExtension 会把它传给 g++。只在确认 NpuExtension 确实不传 flag 时，才回退源码 `#define`（且值要跟着 `compiled_with_cxx11_abi()` 走，别写死 0）。

### 坑 2：TORCH_CHECK 引用未定义符号

**症状**：即使去掉所有手写的 `TORCH_CHECK`，加载 `.so` 还是报 `undefined symbol torchCheckFail`。

**根因**：`TORCH_LIBRARY_FRAGMENT` / `TORCH_LIBRARY_IMPL` 宏内部也用 `TORCH_CHECK` 做注册冲突检查，仍会引用 `torchCheckFail`。光去掉手写的 `TORCH_CHECK` 不够。

**修复**：这个符号引用本身不可避免（除非不用 `TORCH_LIBRARY`），但只要坑 1 的 ABI 对齐了，符号就能从 libc10.so 正常 resolve。所以坑 2 是坑 1 没修的次生症状——确认 ABI flag 生效即可。

### 坑 3：`is_npu()` 在 C++ 里不存在

**症状**：编译报 `'const class at::Tensor' has no member named 'is_npu'`。

**根因**：`is_npu()` 是 torch_npu 给 Python `Tensor` 加的方法，C++ 的 `at::Tensor` 只有 `is_cpu()` / `is_cuda()`。NPU 在 C++ 里注册为 `PrivateUse1` device。

**修复**：
```cpp
// ❌ TORCH_CHECK(xyz.is_npu(), "...");
// ✅
if (xyz.device().type() != c10::DeviceType::PrivateUse1)
    throw std::runtime_error("...");
```

### 坑 4：`torch.library.register_fake` 在 torch 2.1 不存在

**症状**：`AttributeError: module 'torch.library' has no attribute 'register_fake'`。

**根因**：`register_fake` 是 torch 2.4+ 的 API。torch 2.1（torch_npu 2.1.0.post17 配套）还没引入。

**修复**：用 op-plugin 同款写法（`Library("IMPL", "Meta")` + `@impl`）：
```python
from torch.library import Library, impl
m = Library("npu", "IMPL", "Meta")

@impl(m, "<op>")
def _<op>_meta(input, ...):
    return torch.empty(..., device=input.device)
```

### 坑 5：build 产出的 .so 名字带 tag

**症状**：`register_meta.py` 找 `fps_torch_op.so` 找不到。

**根因**：`python setup.py build_ext --inplace` 实际产出 `<op>_torch_op.cpython-310-aarch64-linux-gnu.so`，带 Python 版本和平台 tag。

**修复**：glob 匹配：
```python
candidates = glob.glob(os.path.join(so_dir, "<op>_torch_op*.so"))
```

### 坑 6：依赖 .so 找不到

**症状**：`torch.ops.load_library` 报 `lib<kernel>_host_dynamic.so: cannot open shared object file`。

**根因**：`<op>_torch_op.so` 链接了 `lib<kernel>_host_dynamic.so`，但运行时 loader 找不到。

**修复**（任选一个）：
```bash
# 方案 A：环境变量（临时）
export LD_LIBRARY_PATH=/path/to/kernel/out/lib:$LD_LIBRARY_PATH

# 方案 B：rpath（写进 .so，setup.py 里设）
extra_link_args=["-Wl,-rpath," + LIB_DIR]

# 方案 C：复制到同目录（loader 默认找同目录）
cp lib<kernel>_host_dynamic.so <op>_torch_op.so 所在目录/
```

实测方案 A 最稳；方案 B 在 `NpuExtension` 下 rpath 可能被覆盖；方案 C 简单但两个 .so 要同步维护。

### 坑 7：nullptr stream 导致精度炸裂（关键）

**症状**：注册的 op 在单元测试里正确（`old == new: True`），但接到完整 pipeline 后 iou 从 0.299 暴跌到 0.041。

**根因**：C++ wrapper 传 `stream_ptr = nullptr` 给 kernel。kernel 内部（`fps_host_dynamic.cpp`）遇到 nullptr 会 `aclrtCreateStream(&g_stream)` 创建自己的 stream。这个 stream 跟 torch 的默认 NPU stream **不同**：
- xyz 在 torch 的 stream 上写 → FPS 在 g_stream 上读 → **数据竞争**，FPS 可能读到未写完的 xyz
- FPS 在 g_stream 上写 idx → 下游在 torch stream 上读 → **idx 未就绪**

**为什么单元测试没暴露**：测试脚本多次调用之间有 Python 延迟，kernel 有时间跑完。Pipeline 里连续调用（PointNet2 forward 内 FPS → gather → ball_query → group_points → MLP），没间隙就炸。

**修复**：创建独立 stream + 显式同步：
```cpp
#include "acl/acl.h"

static aclrtStream s_stream = nullptr;

at::Tensor run_op(const at::Tensor &input, ...) {
    if (s_stream == nullptr)
        aclrtCreateStream(&s_stream);

    // 确保 torch stream 的数据就绪（xyz 已写完）
    aclrtSynchronizeDevice();

    // kernel 在独立 stream 上跑
    for (int64_t b = 0; b < B; ++b)
        kernel_run(..., s_stream);

    // 等 kernel 完成（idx 已写完）
    aclrtSynchronizeStream(s_stream);

    return output;
}
```

`aclrtSynchronizeDevice()` 比较重（全设备同步），但保证正确。优化方向：拿到 torch 的 stream 直接传给 kernel（用 `c10::npu::getCurrentNPUStream()`），但相关 C++ 头文件在 torch_npu 2.1 下路径未确认。

**教训**：单元测试验证 `old == new` 只说明**算子逻辑**对，不能验证** stream 同步**。必须在真实 pipeline（多算子交替、连续调用）里验证精度。

> ⚠️ 后续发现：这个 "dedicated stream + aclrtSynchronizeDevice" 修复**只在输入是 Python 端已 materialized 的 tensor 时有效**。如果 wrapper 内部有 C++ `at::` 操作（如 `at::to(kInt)` cast 或 `at::zeros`），这些操作进入 torch_npu lazy queue 但没有被 `aclrtSynchronizeDevice()` flush（它只 sync ACL 队列，不 flush torch_npu 的 lazy 队列）。正确解法见 [坑 8](#坑-8opcommandrunopapi-才能正确集成-torch_npu-lazy-queue)。

### 坑 8：OpCommand::RunOpApi 才能正确集成 torch_npu lazy queue（关键）

**症状**：注册的 op 在单元测试里结果全是 0（100% zero），而 ctypes 版本正常（~70% zero）。对比如下：

| 调用方式 | zero rate |
|---------|-----------|
| ctypes（Python torch.zeros → ctypes 调 .so） | 70.70% |
| torch op（C++ at::zeros → 直接 extern "C" 调 .so）| 100.00% |
| torch op + Python 端先 torch.npu.synchronize() | 70.70% ✓ |

**根因**：直接 `extern "C"` 调 .so 函数**绕过 torch_npu 的 op 框架**。C++ 端的 `at::zeros`、`at::to` 等操作进入 torch_npu 的 **lazy queue**——它们不会立即提交到 ACL，而是等到 Python 边界才 flush。kernel 是直接 ACL launch，不经过 lazy queue，所以先跑完。之后 Python 边界触发 flush，`at::zeros` 的 zero-fill 才执行——**覆盖 kernel 已有的输出**，洗成全零。

ctypes 为什么对：Python 端 `_get_npu_stream()` 访问 `torch.npu.current_stream()._cstream` 属性，这个 Python 操作触发了 torch_npu flush，flush 完才调 kernel。

**修复**：用 `at_npu::native::OpCommand::RunOpApi(name, callable)` 包裹 kernel 调用（参考 op-plugin `examples/cpp_extension/csrc/host/utils.h`）。OpCommand 把 kernel 注册进 torch_npu 的 op 队列，框架自动保证 at:: 操作和 kernel 之间的顺序——不需要任何手动 sync。

```cpp
#include "torch_npu/csrc/core/npu/NPUStream.h"
#include "torch_npu/csrc/framework/OpCommand.h"

aclrtStream stream = c10_npu::getCurrentNPUStream().stream(false);
at_npu::native::OpCommand::RunOpApi("<op>", [...](...) -> int {
    int ret = <kernel_run>(..., stream);
    if (ret) throw ...;
    return 0;
});
```

**为什么 `aclrtSynchronizeDevice()` 不行**：`aclrtSynchronizeDevice` 只同步 ACL 队列，不 flush torch_npu 的 lazy queue。在 C++ op wrapper 内部调它，torch_npu 的 lazy 队列可能仍然是空的（at:: 操作还没被提交到 ACL），sync 立即返回，没有实际效果。

### 坑 9：OpCommand lambda 必须值捕获——引用捕获 [&] → segfault

**症状**：kernel 调用能正常完成（测试输出 `step3 fps ok shape torch.Size([1, 512])`），但程序退出时 segfault（exit 139）。

**根因**：OpCommand::RunOpApi **推迟执行** lambda——它在 torch_npu lazy queue flush 时才调用，这时包装函数已返回，栈上变量（`at::Tensor`）已析构。`[&]` 引用捕获导致 lambda 持有了悬空引用，执行时访问已释放的 tensor storage，触发 segfault。

**修复**：显式**值捕获**。`at::Tensor` 是引用计数的智能指针，值捕获后 lambda 持有一份拷贝，tensor storage 不会提前释放：

```cpp
// ❌ 引用捕获——推迟执行时引用悬空
at_npu::native::OpCommand::RunOpApi("op", [&]() -> int { ... });

// ✅ 值捕获——lambda 持有的 tensor 引用计数 +1，storage 存活
at_npu::native::OpCommand::RunOpApi("op",
    [xyz, idx, B, N, stream]() -> int { ... });
```

### 坑 10：`<c10/npu/NPUStream.h>` 不存在——正确路径在 `torch_npu/csrc/` 下

**症状**：编译报 `c10/npu/NPUStream.h: No such file or directory`。

**根因**：torch_npu 2.1 的头文件不在 `<c10/npu/>`，而在 `<torch_npu/csrc/>` 下。

**修复**：
```cpp
// ❌ 这个路径不存在
#include <c10/npu/NPUStream.h>

// ✅ torch_npu 2.1 的正确路径
#include "torch_npu/csrc/core/npu/NPUStream.h"
#include "torch_npu/csrc/framework/OpCommand.h"
```

**为什么这两个头文件可用了**：之前以为拿不到 torch stream（头文件缺失→被迫传 nullptr→stream race→坑 7 的 sync 方案）。现在确认了正确路径，可以直接用 `c10_npu::getCurrentNPUStream().stream(false)` 获取 torch 当前 stream + OpCommand 集成，不需要手动 sync。

---

## 验证（最小测试脚本）

注册成功后，必须验证两点：① eager 调用输出正确；② 注册前后输出一致。

```python
import torch
import torch_npu
from register_meta import load_<op>_torch_op

load_<op>_torch_op()

# 对比 ctypes 版本（注册前已有的 kernel 调用方式）
xyz = torch.randn(B, N, 3, device='npu:0', dtype=torch.float32)
idx_old = old_ctypes_kernel(xyz, npoints)
idx_new = torch.ops.npu.<op>(xyz, npoints, num_cores)

assert torch.equal(idx_old, idx_new), "old != new"
print("PASS")
```

**重要**：单元测试 `old == new` 只验证算子逻辑正确，**不验证 stream 同步**。如果 C++ wrapper 传了 `nullptr` stream，单元测试可能通过（调用间隙 kernel 有时间跑完），但 pipeline 里精度会炸。必须在完整 pipeline 里验证精度。详见 [坑 7](#坑-7nullptr-stream-导致精度炸裂关键)。

---

## 在 torch.compile 里用注册过的 op

注册完成后，`torch.ops.npu.<op>` 在 dynamo 眼里是一个有 Meta 实现的算子，trace 时不会进实现——它把这个调用当图节点保留。配合 `torch._dynamo.disable` 把其他 ctypes 算子标成 eager black box，就能让整张图里**这一段编译，其他段 graph break**：

```python
# 把其他没注册的 ctypes 算子标成 eager
pointnet2_utils.gather_operation = torch._dynamo.disable(pointnet2_utils.gather_operation)
# ...

# 注册过的 fps 不用 disable，dynamo 能 trace
model.forward = torch.compile(model.forward, dynamic=False, fullgraph=False, backend=npu_backend)
```

`fullgraph=False` 允许 graph break（`@disable` 的算子处自动断），`fullgraph=True` 不兼容 `@disable`（会报 `call torch._dynamo.disable() wrapped function`）。

---

## 已知限制（未验证路径）

- **TorchAir GE converter**：注册成 `torch.ops.npu.<op>` + Meta 后，dynamo 能 trace，但 TorchAir 把 FX graph 转 GE graph 时**是否自动支持自定义 op** 未验证。可能仍 graph break（op 没有对应 GE converter），也可能进图（如果 TorchAir 有通用 CustomOp 节点）。本次验证只到 "dynamo 不报错 + eager 输出正确" 这一步。

---

## 案例参考

完整实施案例（FPS kernel）：
- C++ wrapper：`GenPosePlus/ascendc_kernels/torch_op/fps_torch_op.cpp`
- setup.py：`GenPosePlus/ascendc_kernels/torch_op/setup.py`
- register_meta.py：`GenPosePlus/ascendc_kernels/torch_op/register_meta.py`
- 测试脚本：`GenPosePlus/ascendc_kernels/torch_op/test_fps_op.py`
- 接入 evaluation_tracking.py 的 TorchAir 路径：搜索 `TORCHAIR_PT2` 环境变量

op-plugin 的参考实现（Huawei 官方）：`op-plugin/examples/cpp_extension/`，展示了纯自定义 AscendC kernel 的完整注册链路（`TORCH_LIBRARY_FRAGMENT` + `NpuExtension` + `load_library`）。但 op-plugin 的 example 只测了 eager，没测 torch.compile。
