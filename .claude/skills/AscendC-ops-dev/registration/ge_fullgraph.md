# GE 自定义算子入图（TorchAir fullgraph=True）

## 什么时候用这条路

已有 AscendC kernel，想用 `torch.compile(fullgraph=True, backend=npu_backend)` 把算子完全编进 GE 图（不 graph break）。

跟 OpCommand 路（`README.md`）的区别：

| | OpCommand 路 | GE 入图路 |
|---|---|---|
| fullgraph | False（graph break） | **True**（完全入图） |
| CANN 版本 | ≥ 8.3 | **≥ 9.0** |
| 编译器 | NpuExtension（python setup.py） | **cmake + make binary package** |
| 部署 | LD_LIBRARY_PATH 指 .so | **.run 自解压 → source set_env.bash** |
| Python 接入 | `TORCH_LIBRARY` + `torch.ops.load_library` | **`torch.library.Library` + `register_fx_node_ge_converter`** |
| 官方参考 | op-plugin/examples/cpp_extension | **asc-devkit/examples/.../custom_op** |

## 总体流程

```
AscendC kernel (.cpp)
    ↓ cmake + ascendc toolchain 编译
libcust_opmaster_rt2.0.so  +  kernel .o 二进制
    ↓ make binary package
custom_opp_<os>_<arch>.run  (自解压安装包)
    ↓ ./custom_opp_*.run 部署到 CANN vendors/
GE runtime 可发现算子
    ↓ Python: register_fx_node_ge_converter
torch.compile(fullgraph=True) 自定义算子入图
```

## 完整步骤

### 1. 环境要求

- CANN ≥ 9.0（带 `graph/custom_op.h`）
- 开发镜像（带 cmake + ascendc toolchain + GE headers）
- 参考镜像：`swr.cn-south-1.myhuaweicloud.com/ascendhub/cann:9.0.1-310p-openeuler24.03-py3.12`

### 2. 项目目录结构

参考 `asc-devkit/examples/.../custom_op/`（gitcode 可 clone）：

```
custom_op/
├── CMakeLists.txt          # 顶层：ASCEND_COMPUTE_UNIT + npu_op_package
├── op_kernel/
│   ├── CMakeLists.txt      # ascendc_kernel 编译
│   └── my_op/
│       ├── my_op_kernel.cpp       # AscendC device kernel
│       └── my_op_tiling.h         # tiling 参数
├── op_host/
│   ├── CMakeLists.txt      # host 侧编译
│   └── my_op/
│       ├── my_op_host.cpp         # launch 函数 + torch 注册
│       └── my_op_tiling.h/cpp     # tiling 实现
└── op_api/
    └── my_op/
        └── my_op.cpp       # GE EagerExecuteOp（可选）
```

**关键：`CMakeLists.txt` 顶层必须设 `ASCEND_COMPUTE_UNIT`**

```cmake
set(ASCEND_COMPUTE_UNIT ascend910b ascend910_93 ascend950 ascend310p)
```

compute unit 名从 CANN opp 目录确认：

| 硬件 | compute unit |
|------|-------------|
| 310P / 300I DUO | `ascend310p` |
| 910B | `ascend910b` |
| 910 系列 | `ascend910_93` |

### 3. 编译打包

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
mkdir -p build && cd build
cmake .. -DASCEND_COMPUTE_UNIT=ascend310p   # 限定目标 SOC，省时间
make -j binary package
# 产出：custom_opp_<os>_<arch>.run
```

**`binary` target 是关键**：`make binary package` 里的 `binary` 才真正编译 device kernel（调 opc 把 `.cpp` 编成 `.o` 二进制）。光跑 `cmake --build .` 只编 host 侧库 + 拷源码 + 生成 ops_info json，**不编 kernel**——漏了 `binary` 会让 package 报 `cannot find binary/config: No such file or directory`。

**compute unit 限定**：不传 `-DASCEND_COMPUTE_UNIT` 时按各 op host.cpp 的 `AddConfig()` 全编（多 SOC 慢）。传了只编指定 SOC，但 op 的 `AddConfig` 必须包含该 SOC，否则不编。

### 4. 部署到 CANN

`.run` 是自解压安装包，直接跑就装（不需要手动 `--extract` + `install.sh`）：

```bash
./custom_opp_*.run --quiet
# 装到 /usr/local/Ascend/cann-*/vendors/customize/ 和 .../opp/vendors/customize/
```

部署后**两个环境动作缺一不可**（漏了 GE 找不到 op 或 op_api 符号）：

```bash
# ① 激活 vendor——GE runtime 据此发现算子
source /usr/local/Ascend/cann-*/vendors/customize/bin/set_env.bash
# ② op_api 库——部署结尾会打印这条要求
export LD_LIBRARY_PATH=/usr/local/Ascend/cann-*/opp/vendors/customize/op_api/lib:$LD_LIBRARY_PATH
```

检查部署到位：`find /usr/local/Ascend/cann-*/opp/vendors -name '*my_op*' -path '*ascend310p*'`

### 5. Python 侧：op 注册 + GE converter

```python
import torch, torch_npu, torchair
from torchair.ge import Tensor, TensorSpec

# ① 注册 op 签名 + Meta（纯 Python，不需要 C++ .so）
m = torch.library.Library("ascendc_ops", "FRAGMENT")
m.define("my_op(Tensor x, Tensor y) -> Tensor")

@torch.library.impl(m, "my_op", "Meta")
def my_op_meta(x, y):
    return torch.empty_like(x)

# ② PrivateUse1 stub（可选）——纯 fullgraph 用途可省；加了是给 eager 调用一个清晰报错
@torch.library.impl(m, "my_op", "PrivateUse1")
def my_op_npu(x, y):
    raise NotImplementedError("graph-mode only")

# ③ GE converter：map torch op → GE operator
@torchair.register_fx_node_ge_converter(torch.ops.ascendc_ops.my_op.default)
def convert_my_op(
    x: Tensor, y: Tensor, z: Tensor = None, meta_outputs: TensorSpec = None
):
    return torchair.ge.custom_op(
        "MyOp",                           # GE 侧 REG_AUTO_MAPPING_OP 注册名
        inputs={"x": x, "y": y},
        outputs=["z"],
    )

# ④ fullgraph=True 编译——自定义 op 完全入图
config = torchair.CompilerConfig()
npu_backend = torchair.get_npu_backend(compiler_config=config)
model = torch.compile(MyModel().npu(), fullgraph=True, backend=npu_backend)
```

### 6. 运行时参数作属性（Attr）—— 参数随调用变化时必做

很多算子的参数（radius、nsample、npoint 等）随调用变化（如 PointNet2 各 SA 层参数不同）。ctypes/eager 路这些是运行时实参；GE 路若硬编码在 TilingFunc 里，则只对一组值正确。**正确做法：把变化参数声明为 op 属性（Attr）**，TilingFunc 和 InferShape 都从属性读。

host.cpp（OpDef 声明 + TilingFunc/InferShape 读取，属性按声明顺序索引）：

```cpp
namespace ops {
class MyOp : public OpDef {
    MyOp(const char* name) : OpDef(name) {
        this->Input("x")...Output("y")...;
        this->Attr("radius").Float();   // 属性 idx 0
        this->Attr("nsample").Int();    // 属性 idx 1
        ...
    }
};
}

// TilingFunc（gert::TilingContext）读属性写进 tiling：
auto* attrs = context->GetAttrs();
float radius   = *attrs->GetAttrPointer<float>(0);
int   nsample  = *attrs->GetAttrPointer<int>(1);
tiling->radius = radius; tiling->nsample = nsample;

// InferShape（gert::InferShapeContext 继承 ExtendedKernelContext）也能读，用它定输出维度：
int nsample = *context->GetAttrs()->GetAttrPointer<int>(1);
idxShape->SetDim(2, nsample);   // 如 idx = [B, M, nsample]
```

**kernel 不用改**——这些参数本来就从 tiling 读，只是值改由 host 从 Attr 填入（不再硬编码）。

converter 把属性传进去（值要用 `attr` 包装，见坑 9）：

```python
return torchair.ge.custom_op("MyOp",
    inputs={"x": x},
    attrs={"radius": attr.Float(radius), "nsample": attr.Int(nsample)},
    outputs=["y"])
```

> 实测：ball_query（radius 0.02-0.16 × nsample 16/32 共 8 组合）、fps（npoint 512/256/128）属性化后，对 pipeline 所有真实参数 fullgraph 全 PASS。

## 踩坑记录

### 坑 1：compute unit 名不是 SOC 名

`ascend310p3`（SOC 名）→ ❌，`ascend310p`（compute unit 名）→ ✅。

确认方法：`ls /usr/local/Ascend/cann-*/opp/built-in/op_impl/ai_core/tbe/kernel/`

### 坑 2：部署后必须 source set_env.bash

install.sh 打印 SUCCESS 但 GE 仍找不到 op——没 source `vendors/customize/bin/set_env.bash`。

### 坑 3：CANN 9.0+ 才有 custom_op.h

CANN 8.3/8.5 没有 `EagerExecuteOp`。必须升到 9.0+。验证：`find /usr/local/Ascend/cann-*/ -name custom_op.h`

### 坑 4：ABI 自动处理

CANN 9.0 的 cmake 从 `find_package(Torch)` 读 TORCH_CXX_FLAGS 自动设 ABI，**不要**手动传 `-DGLIBCXX_USE_CXX11_ABI`。

### 坑 5：kernel entry 签名必须有 workspace 参数（高频，必踩）

AscendC GE kernel 的 entry 函数签名约定是 **`(inputs..., outputs..., workspace, tiling)`** —— 倒数第二个必须是 `workspace`，最后是 `tiling`。

autogen 生成的 dispatch wrapper（`<op>_<key>_tilingkey`）按 host OpDef 声明的 I/O 数量自动生成调用，**固定带 `usrWorkspace` 实参**：

```cpp
// autogen 生成（build/op_kernel/MyOp_ascend310p/.../*_kernel.cpp 约 line 43）
my_op(x_in__, y_in__, z_out_, usrWorkspace, tiling);   // 5 个实参
```

若 entry 少写了 workspace：

```cpp
// ❌ 少 workspace
extern "C" __global__ __aicore__ void my_op(
    __gm__ uint8_t* x, __gm__ uint8_t* y, __gm__ uint8_t* z, __gm__ uint8_t* tiling)
// 报错：candidate function not viable: requires 4 arguments, but 5 were provided
//       no matching function for call to 'my_op_0_tilingkey'
```

**修复**：哪怕 kernel 不用 workspace（结果直写输出 GM），也必须加一个不用的 workspace 参数对齐签名：

```cpp
// ✅
extern "C" __global__ __aicore__ void my_op(
    __gm__ uint8_t* x, __gm__ uint8_t* y, __gm__ uint8_t* z,
    __gm__ uint8_t* workspace, __gm__ uint8_t* tiling)
```

host 侧 `GetWorkspaceSizes(1); ws[0]=0;` 即可（workspace 大小为 0 也行，参数必须存在）。

> 实测：ball_query entry 原签名 4 参（缺 workspace）→ autogen 报 "requires 4 arguments, but 5 were provided"；加 workspace 后三 SOC 全过、fullgraph 测试 100% 正确。

### 坑 6：改 kernel 源码后必须干净重建（rm -rf build）

GE 对自定义算子是**运行时按输入 shape 重编译**的，用的是部署到 `opp/vendors/customize/.../customize_impl/dynamic/<op>/` 的**源码**，不是 build 时编出的 `.o`。

`make binary package` 是增量的：改了 kernel 源码后，**device `.o` 会重编**，但打包进 `.run` 的**源码副本**可能仍是缓存旧版。于是：

- 增量 build + 重新部署 → 部署的源码是旧的 → 改动不生效，甚至复现已修好的 bug
- **改了 kernel 源码后，`rm -rf build` 干净重建，再重新部署**

> 实测：修了 ball_query 的 workspace（坑 5），增量重建 + 部署后 runtime 仍报旧错；查部署副本 `.../ball_query/ball_query_kernel.cpp` 还是 4 参旧签名。`rm -rf build` 重建 + 部署后才带上修复。

### 坑 7：tiling struct 名不必等于 OP_TYPE + TilingData

`REGISTER_TILING_DEFAULT(X)` 和 `GET_TILING_DATA` 的 autogen 按 **OP_TYPE 和 kernel 函数名**生成 dispatch 函数，**不按 struct 名**。struct 叫什么都行，只要 host 侧 `GetTilingData<X>` 和 kernel 侧 `REGISTER_TILING_DEFAULT(X)` 引用同一个 `X`。

不必纠结 struct 名是否符合 `OP_TYPE + TilingData` 的 convention——它是 convention 不是硬约束。

> 实测：add_custom 用 `AddCustomTilingData`（符合 convention），fps 用 `FpsTilingData`（OP_TYPE 是 `FpsCustom`，不符合 convention）——两者都能编译通过。ball_query 用 `BallQueryTilingData`、group_points 用 `GroupPointsTilingData`（均不符合 convention）也都通过。

### 坑 8：GE 运行时 kernel 编译缓存不随部署刷新（高频，导致诡异的"改了没用"/假 507011）

GE 对自定义算子是**运行时按输入 shape 重编译**并缓存在 `/root/atc_data/kernel_cache/<SOC>/te_<optype>_<hash>.{o,json,lock}`。这个缓存**不随 `.run` 重新部署而失效**——重新部署了新 kernel，GE 仍可能加载旧的缓存 binary。

症状（按踩坑顺序）：
- 改了 kernel 源码、重新部署后，行为**完全不变**（包括已修好的 bug 仍复现）→ 在跑旧缓存
- runtime 507011 / MTE 越界，但 kernel 代码反复核对无问题 → 可能是**上个 session 残留的崩溃 binary** 在缓存里
- 裁剪 kernel 到极简（只写输出）仍崩 → 几乎可以确定是缓存，不是 kernel

**排查方法**：看崩溃日志里的 `fault kernel_name=te_<optype>_<hash>`，再看 `/root/atc_data/kernel_cache/<SOC>/` 里是不是同一个 hash。若跨多次源码大改 hash 不变 → 缓存在作祟。

**修复**：清掉该 op 的运行时缓存再重跑（GE 会按当前部署源码重编译）：

```bash
rm -f /root/atc_data/kernel_cache/Ascend310P3/te_<optype>_*
```

> 实测：FPS 这个 session 反复 507011，裁剪到 ultra-minimal（只写 8 个零）仍崩、OBS_TEST（写常量 12345）却输出真实 FPS 结果——全是上 session 残留的崩溃/旧 binary 在缓存里。`rm -f /root/atc_data/kernel_cache/Ascend310P3/te_fpscustom_*` 后立刻正常。**这个坑浪费了整整一轮裁剪二分调试。**

**关联坑 8b（已验证）— op 级缓存：对已部署 op 的 host tiling / kernel body 改动不生效，必须改名**：除坑 8 的 runtime kernel cache 外，还有一层更顽固的 **op 级缓存**——对一个**已部署过的 OP_TYPE**，后续改它的 host TilingFunc 或 kernel body，部署后 runtime **仍跑旧的**（新 .so 时间戳是新的、build log 也显示重编了，但 GE 就是不加载新的）。这层缓存** survives 卸载重装 + 清空整个 atc_data**，找不到独立的缓存目录可清。

证据链（FPS 为例）：
- host `GetDim(1)` 改 `GetDim(2)`，build log 显示 `fps_host.cpp.o` 重编、部署 .so 时间戳刷新，但 runtime 仍用 `GetDim(1)`（靠错误码 `The burst num of the mte command is incorrect` 反推 totalN 仍是旧值）
- 把 totalN **硬编码**成 1024 仍不生效
- `uninstall.sh` 卸载 + `rm -rf /root/atc_data` + 重装，仍不生效
- 但**新 op**（首次部署，如 group_points）和**签名级改动**（如 ball_query 加 workspace 参数）都能正常生效

**可靠破法：给 op 改个新名字（新 OP_TYPE）**。新 OP_TYPE 是全新 op，部署从零注册、无缓存命中，所有 host/kernel 改动立即生效。

```python
# 改名要同步这几处（OP_TYPE 驱动 autogen 生成的 .py 名 + kernel entry 名，必须一致）：
# 1. op_kernel/CMakeLists.txt:  OP_TYPE FpsCustom -> FpsGe
# 2. op_host/fps_host.cpp:       class FpsCustom -> FpsGe ; OP_ADD(FpsCustom) -> OP_ADD(FpsGe)
# 3. op_kernel/*.cpp:           extern "C" ... void fps_custom -> fps_ge   (entry = OP_TYPE 的 snake_case)
# 4. Python converter:          custom_op("FpsCustom", ...) -> custom_op("FpsGe", ...)
```

> 实测：FPS 改名 FpsCustom→FpsGe 后，之前死活不生效的 host `GetDim(2)` + layout 修复立即生效，测试 MATCH 512/512。
>
> **启示**：调试已存在 op 的 GE 改动时，若"改了源码、重新部署、清了 runtime cache，行为仍不变"——别再怀疑自己的代码，先怀疑 op 级缓存，直接改名验证。这比反复裁剪二分（会被坑 8 + 8b 联手骗过去）高效得多。

### 坑 9：converter 的 attrs 值必须用 `attr` 包装，不能传裸值

`custom_op(..., attrs={...})` 的 value 必须是 `torchair.ge.attr` 构造的对象（`_Attr` 类型），传裸 float/int 会报 `Invalid attr 'x' type:float vs expect one of [ge.attr.Float, ...]`。

```python
from torchair.ge import attr
# ❌ 裸值
attrs={"radius": radius, "nsample": nsample}
# ✅ 包装
attrs={"radius": attr.Float(radius), "nsample": attr.Int(nsample)}
```

常用类型：`attr.Float` / `attr.Int` / `attr.Bool` / `attr.String` / `attr.ListFloat` 等。具体哪些用 `from torchair.ge import attr; [k for k,v in vars(attr).items() if isinstance(v,_Attr)]` 看（需 source 了 set_env 才能 import torchair）。

### 坑 10：`torchair.ge` 没有 transpose——转置放 torch 侧，别在 converter 里做

converter 里若想对输入做转置（如 fps kernel 要 `[B,3,N]`、torch op 给的是 `[B,N,3]`），**别找 `torchair.ge.transpose`——它不存在**（AttributeError）。

正确做法：**在 torch op wrapper / model forward 里用标准 `torch.transpose` 转置**，dynamo 会把它 trace 成原生 GE 转置节点，converter 直接收转置后的 tensor：

```python
# torch 侧（model forward 或 _xxx_via_op wrapper）
xyz_t = xyz.transpose(1, 2).contiguous()       # 标准 torch，dynamo 原生 trace
return torch.ops.my.fps(xyz_t, npoint)         # converter 收到 [B,3,N]，直传 FpsGe

# converter 侧——不需要 transpose，直传
return torchair.ge.custom_op("FpsGe", inputs={"xyz": xyz}, ...)
```

### 坑 11：converter 的 `meta_outputs` 参数不能加类型注解（高频，症状 flaky 极易误导）

`register_fx_node_ge_converter` 注册的 converter 函数，最后一个 `meta_outputs` 参数**不要写 `: TensorSpec` 注解**：

```python
# ❌ 加注解 —— converter 注册了但不绑定，op 退 eager 派发
@torchair.register_fx_node_ge_converter(torch.ops.ascendc.fps_ascendc.default)
def _convert(xyz: Tensor, npoint: int, num_cores: int, meta_outputs: TensorSpec = None):
    ...

# ✅ 无注解
@torchair.register_fx_node_ge_converter(torch.ops.ascendc.fps_ascendc.default)
def _convert(xyz, npoint, num_cores, meta_outputs=None):
    ...
```

注解会让 torchair 的 converter 绑定失效（注册调用不报错，但运行时 converter 没生效）→ dynamo 把自定义 op 当普通 torch op 派发 → 无 eager kernel → **硬崩溃**。症状极误导：同一份代码每次崩法不同（`std::bad_alloc` / SIGSEGV / 整张 dispatch key 表 dump），排查时容易怀疑 namespace、注册时机、Meta 写法，反复白调。

> 实测：converter 加 `: TensorSpec` 注解时，无论用 npu FRAGMENT、ascendc DEF、函数级还是模块级注册，全崩（4 轮不同错误）；**只去掉注解**（其余不变）立即 3 配置全 PASS。注解是唯一变量，根因锁定。

**配套：自定义 GE op 用独立 DEF namespace（如 `ascendc`），别塞 torch_npu 的 `npu` namespace**。`torch.library.Library("ascendc", "DEF")` + 模块级 `define`/`impl`/`register_fx_node_ge_converter`（参考 add_custom POC 范式）最稳。注解坑修复后是否 npu namespace 也可行**未单独验证**（已用 ascendc 跑通，没回测 npu）。

### 坑 12：torchair 缺 `aten.amax` converter——用 `max.dim` 互换

torchair（CANN 9.0 这版）的 `aten.amax` converter 是空壳（`raise NotImplementedError("amax ge_converter is not implemented!")`），fullgraph 一碰到 `torch.amax(..., dim=...)` 就编不过。PointNet2 SA 层的 max-pool 正好用它。

`torch.amax(x, dim, keepdim) ≡ torch.max(x, dim, keepdim).values`，而 `aten.max.dim` 有 GE 实现（`ge.ReduceMax`）。故 fullgraph 路把 amax 互换成 max：

```python
torch.amax = lambda x, dim, keepdim=False: torch.max(x, dim=dim, keepdim=keepdim).values
```

> 实测：单 SA 层（fps→gather→ball_query→group_points→Conv2d MLP→amax→max）fullgraph 全 PASS，max 互换数值正确。注意 `aten.max.other`（两 tensor 逐元素 max）也是 RuntimeError 不支持，别撞；只 `max.dim` / `max.default`（ReduceMax）可用。

### 坑 13：torchair 运行时 multi-op fullgraph 概率性 507011（flaky，driver 层）——走 static OM 绕开

> **2026-07-20 重大修正**：本坑原写"整图累积多 custom op 后 aicore 静默超时，阈值~3 MSG 层，切几段编译绕过"——**归因错误**。实测 fresh 4 层整图 fullgraph 能过（`test_2layer_real`），根本没有 op 数阈值。真因是 **torchair 运行时（dynamo→GE 运行时 session）对 multi-op 图的 stream 同步 flaky 竞态**（driver 5070xx 家族，社区 lmdeploy #3354/vllm-ascend #4972 "probabilistic hangs"），代码层修不了。
>
> **实测**（PointNet2）：单 op / 单 SA 层 torchair fullgraph 稳过；multi-op（SA 层链/整图/split-2）概率性 507011（2 过/6 挂）。`ASCEND_GLOBAL_LOG_LEVEL=0` / `ASCEND_LAUNCH_BLOCKING=1` 都**不**解决（一度以为 debug 日志能避开，验证后是单点过拟合）。
>
> **507011 细节**：aicore 28s watchdog 超时；本例是 copy-stream 同步超时（**无 fault kernel_name**，跟 vllm 的 aicore compute-fault 不同）；dmesg 有 `devmm Set free error ref_count=2`（清理症状，非根因；坑原说"dmesg 静默"是漏 grep）。
>
> **正路 = static OM（不走 torchair 运行时）**：torch→ONNX（`register_custom_op_symbolic` 把 op emit 成部署的 GE op_type）→ ATC → OM → ACL `aclmdlExecute`。GE 官方 demo（`D:\compass\ge\examples\custom_op\compilable_add_custom`）走这条，多 op custom-op 图稳过，README 明说"不适合 torchair"。详见 GenPose2 `syx_docs/summary/2026-07-20_torchair_flaky_pivot_to_static_om.md`。
>
> 下方为原（错误归因的）记录，保留作上下文——**split-N workaround 不靠谱（flaky 里的幸存），别再走**。

~~GE 把含大量自定义 op 的图编成一个 model（或链多个 torch.compile 模型）执行时，会 aicore 静默超时（507011）。阈值不在单 op/单层（单 op、单层、少层都 PASS），而在累积——实测 PointNet2 MSG encoder 约 3+ 个双尺度 MSG 层（~15+ custom ops）就挂。~~ **（2026-07-20 作废：无 op 数阈值，是 flaky 运行时 bug）**

GE 把**含大量自定义 op 的图**编成一个 model（或链多个 torch.compile 模型）执行时，会 aicore 静默超时（507011）。阈值不在单 op/单层（单 op、单层、少层都 PASS），而在**累积**——实测 PointNet2 MSG encoder 约 3+ 个双尺度 MSG 层（~15+ custom ops）就挂。

排查要点（全部实测排除过，别重复怀疑）：不是接线（小图全过）、不是单 kernel/shape（单 op 大 C OK）、不是图编译复杂度（per-layer 避开编译仍挂）、不是设备争用（切空闲卡仍挂）、不是 event 池（hang 期间稳定不泄漏）、dmesg 静默无线索。精确定位要 tlparse 把 task_id 映射到 node（成本高，常非接线可修）。

**workaround：切几段编译（split-N）**。把模型切成 N 段，每段单独 `torch.compile(fullgraph=True)`，段间 eager 串。关键是**每段的"编译模型链式数"卡在阈值下**——实测 2 段（链 2 个编译模型）PASS、4 段（链 4 个）仍 hang，阈值在 2-4 之间。每段内部仍是完整 fullgraph（custom op 走 GE converter），段间只过原生 eager op（gather/cat 等）。

```python
# 例：4 层 encoder 切 2 段（每段 2 层）
ch1 = torch.compile(Half1(), fullgraph=True, backend=npu_backend)  # SA0+SA1
ch2 = torch.compile(Half2(), fullgraph=True, backend=npu_backend)  # SA2+SA3
# 段间 eager
l1_xyz, l1_feat, fg1 = ch1(xyz, features)
out = ch2(l1_xyz, l1_feat, fg1)
```

> 实测：PointNet2 MSG 整图 / per-layer(4) 都 hang，split-2（2 段）跑通（out finite、shape 对）。这是"整图 fullgraph 走不通"时的退路——不是整图 fullgraph（段间有 eager 缝），但 custom op 全入 GE，无 graph break 退 OpCommand eager。

### 坑 14：static OM 里多核 SyncAll 必崩 → kernel 内清 + DCE-defeat

坑 13 的正路是 static OM。但 **static OM 下多核（numCores>1）+ 跨核 SyncAll 的 custom op 会崩**（507011 / hwts timeout 0x25）：OM 图执行没有 host launch 前清 sync buffer 的时机（ctypes 路有），workspace sync 区初始脏 → SyncAll 死锁。且 ATC JIT 还会把 kernel 内清零当死代码删。

**修复 = kernel 内清 sync + DCE-defeat（GetValue 读回）**，完整技术与代码见 [kernel-dev/multicore.md 的"OM / static OM 下"段](../kernel-dev/multicore.md)。

> 实测：fps 8 核 OM 单算子（预编译 `.o`）跑通，但 eval（ATC JIT）崩；光 kernel 内清零不够（被 DCE 删），加 DCE-defeat 后全量 eval 3488 帧跑通、IoU 不降。

### 坑 15：`make binary package` 报 "Is a directory"（CANN cmake 模板 bug）

`make binary package` 的 cmake_install 把 `build/op_kernel/ascendc_kernels/binary/dynamic` 当 **TYPE DIRECTORY** 拷，但 `binary/dynamic` 实际是**单个文件**（dynamic impl，如 `<op>.py`）→ 报 `file INSTALL cannot copy ... Is a directory`，package 失败、不产新 `.run`。

根因：asc-devkit cmake 模板对 dynamic impl 产物结构的假设错（该是目录但产成文件），CANN 框架层 bug。改 cmake_install 没用（生成的，re-cmake 覆盖）。

**workaround**：绕 `make package`，手动 cp build 产物到 deploy：
- `.o` + `.json`：`build/op_kernel/ascendc_kernels/binary/<soc>/<op>/` → `/usr/local/Ascend/cann-*/opp/vendors/customize/op_impl/ai_core/tbe/kernel/<soc>/<op>/`
- host `.so`：`build/op_host/libcust_opmaster_rt2.0.so` → `.../op_impl/ai_core/tbe/op_tiling/lib/linux/aarch64/`
- dynamic impl 源：`build/.../binary/dynamic`（文件）→ `.../customize_impl/dynamic/<op>/<op>.py`（**注意**：ATC JIT 实际读的源由 `<op>.py` 里 `get_kernel_source` 决定，常 fallback 到 `customize_impl/dynamic/<op>/<src>.cpp`，改 kernel body 要 cp 到那）
- per-op config：`build/.../binary/config/<soc>/<op>.json` → `.../kernel/config/<soc>/`

注意：`bash custom_opp_*.run`（旧包）install 会**还原到 .run 打包时的状态**，覆盖你手动 cp 的改动——只在你想要那个快照时用。

> 参考：[Gitee ascend/samples IC2FR1](https://gitee.com/ascend/samples/issues/IC2FR1) 类似 path 问题。

### 坑 16：custom dynamic op 在 OM 里走 JIT、不用 prebuild .o

onnx_plugin 注册 custom op 若用 `ImplyType::TVM`（dynamic shape op 常见），ATC/runtime 对每个 runtime shape **即时编译**（`te_<op>_<sha256>`），而不是直接用预编译 `.o`——即使 deploy 了 prebuild `.o` 也不一定用。

JIT vs prebuild 由几层决定：
- `enable_op_prebuild`（build config，默认 True=用 prebuild binary）。dynamic shape：先找 prebuild binary，找不到才 JIT。
- per-op config 的 `binList`/`staticKey`/`simplifiedKey` 是否命中 runtime shape。
- `.json` 的 `sha256` 是否匹配实际 `.o`（不匹配 → runtime 不信任 prebuild → 回退 JIT）。

**意义**：若能让 OM 用 prebuild `.o`（不走 JIT），坑 14 的 DCE 问题就不存在（prebuild `.o` 是 ccec 编的，不做激进 DCE，清零保留）。但实际常卡在 make package（坑 15）设不了 prebuild 模式 → 走 JIT → 必须 DCE-defeat。

排查 OM 崩时，看崩溃日志 `fault kernel_name`：
- `te_<op>_<hash>`（shape-hash）= JIT 编译的 → 清零可能被 DCE → 检查 DCE-defeat。
- `<Op>_<op-spec-hash>` = prebuild `.o` → 清零保留 → 问题在别处。

> 参考：[torchair 算子在线编译 enable_op_prebuild](https://www.hiascend.com/document/detail/zh/Pytorch/700/modthirdparty/torchairuseguide/torchair_0028.html)。

### 坑 17：TilingContext::GetInputShape 返回 StorageShape*（cann-9.0.1），不能赋给 Shape*

**症状**：`cmake ..` 配置阶段（`npu_op_code_gen` → `compile_ascendc_all_ops_so`）失败，配置没生成 makefile：
```
error: cannot convert 'const gert::StorageShape*' to 'const gert::Shape*' in initialization
   const gert::Shape* xyzShape = context->GetInputShape(0);
```

**根因**：cann-9.0.1 起，`TilingContext::GetInputShape()` 返回 `const gert::StorageShape*`，不是 `Shape*`。`StorageShape` 和 `Shape` 是两个不同类型，不能隐式互转。

**关键陷阱**：**不同 Context 的 `GetInputShape` 返回类型不同**，TilingFunc 和 InferShape 里的写法**不能照抄**：

| Context | `GetInputShape` 返回 | 出现在 |
|---|---|---|
| `gert::TilingContext` | `StorageShape*` | TilingFunc |
| `gert::InferShapeContext` | `Shape*` | InferShape |

**修法**：
```cpp
// TilingFunc（TilingContext）—— StorageShape*：用 auto，或链式 GetOriginShape() 转回 Shape
auto* xyzShape = context->GetInputShape(0);                              // StorageShape*
int32_t totalN = context->GetInputShape(0)->GetOriginShape().GetDim(2);  // 不存指针，链式取

// InferShape（InferShapeContext）—— Shape*：直接用
const gert::Shape* xyzShape = context->GetInputShape(0);
```

**为什么 Tiling 用 StorageShape**：tiling 阶段输入 shape 可能含 padding/对齐（storage 布局），tiling 要看实际存储；InferShape 算的是逻辑 shape。`GetOriginShape()` 从 StorageShape 取回逻辑 Shape。

> 实测：fps TilingFunc 从旧版 `const gert::Shape* = GetInputShape(0)`（编译失败）改成 `GetInputShape(0)->GetOriginShape().GetDim(2)` 后通过。cann-9.0.1 + ascend310p。

### 坑 18：tiling struct 必须全局（不能包在 namespace optiling），否则 REGISTER_TILING_DEFAULT 找不到

**症状**：`make -j binary package` 编 device kernel 时，FATBIN 阶段失败：
```
ld.lld: error: cannot open .../kernel_meta_<OP>_<hash>/<OP>_<hash>_0.o: No such file or directory
Kernel Compilation Error: OpType <OP> Kernel File <op>_kernel.cpp!
```
（`.o` 没生成 = cce 编译 kernel 失败，但 cce 的具体报错被 opc 吞了，只剩链接器找不到 `.o`）

**根因**：kernel.cpp 里的 `REGISTER_TILING_DEFAULT(X)` 和 `GET_TILING_DATA` 在**全局作用域**找 `X`。若 tiling.h 把 `X` 包在 `namespace optiling { }` 里，kernel.cpp（全局）的名字查找找不到 `optiling::X` → cce 编译失败。

**为什么 host.cpp 不报、只有 kernel.cpp 报**：host.cpp 的 `TilingFunc` 通常写在 `namespace optiling`，里面 `GetTilingData<X>` 解析到同 namespace 的 `X`，OK。但 kernel.cpp 的 `REGISTER_TILING_DEFAULT(X)` 在全局，要全局 `X`。`X` 只能放全局（host 和 kernel 两边都够得着）。

**修法**：tiling struct **全局**，无 namespace：
```cpp
// my_op_tiling.h
#pragma once
#include <cstdint>

struct MyOpTilingData {        // 全局！不要 namespace optiling
    int32_t totalN;
    int32_t npoints;
    // ...
};
```

**易错点**：抄 op-plugin 或老 demo 时，tiling struct 可能带 `namespace optiling`（host 侧惯例）。只要 kernel 侧用了 `REGISTER_TILING_DEFAULT`，struct 就得提到全局。host.cpp 里的 TilingFunc 仍可留在 `namespace optiling`，它引用的 `X` 是全局的（跨 namespace 查找能找到）。

> 实测：fps_tiling.h 旧版 `namespace optiling { struct FpsTilingData {...}; }` → kernel 编译失败（`.o` 没生成）；去掉 namespace 改全局纯 struct 后通过。对照组 ball_query/group_points 的 tiling.h 本就是全局纯 struct，一直能编——fps 是当时唯一包了 namespace 的异类。

### 坑 19：onnx 导出 bs 与 ATC --input_shape bs 不匹配 → om 异常膨胀 → 推理慢 N 倍（IoU 却正常，极易误判）

**症状**：OM 推理 latency 突然退化数倍（如 6×），ATC 编译也异常慢（数十分钟 vs 正常几分钟），但 IoU/精度正常。极易误判成「推理代码（forward loop）变慢」「kernel 多核问题」或「keep_dtype/precision 配置」——通常都不是。

**排查信号（先查）**：对比 **om 与 onnx 文件大小**。正常 ATC 压缩（om ≤ onnx）。**om > onnx（膨胀几倍～几十倍）+ ATC 异常慢** = ATC 图处理异常的明确信号。

**根因**：onnx 导出的 batch size 与 ATC `--input_shape` 的 bs **不一致**（如 onnx 按 `--batch_size 4` 导成 bs4，但某算子 kernel 限制使 ATC 必须 bs1）。ATC 用 input_shape 覆盖 onnx 的 batch 维，但 onnx 内部基于原 bs 的固定张量/常量未同步 → 图处理异常 → om 膨胀 + 编译极慢 + 推理慢。精度（IoU）往往正常（最具迷惑性）。

**修法**：onnx 导出 bs 必须与 ATC `--input_shape` bs **一致**。若某算子限制 ATC 必须 bs1（如 FpsGe kernel B=1），onnx 也必须 bs1 导出——把 bs1 固化进 export 脚本（别让 `--batch_size` 参数覆盖它）。

**OM 性能排查顺序**：① om/onnx 大小比（膨胀？）→ ② onnx 导出 bs vs ATC --input_shape bs（不匹配？）→ ③ ATC 编译时长（异常慢？）→ ④ 最后才查推理代码。别一上来改 forward / keep_dtype。

> 实测（GenPose2 pointnet2，FpsGe B=1）：onnx 按 `--batch_size 4` 导成 bs4 + ATC `--input_shape pointcloud:1,...` bs1 → om 膨胀 44MB / ATC 50min / 推理 809ms（IoU 仍 0.30 正常，故先后误判成 bs1 loop、keep_dtype，控制变量后才坐实 bs 不匹配）；改 bs1 onnx + bs1 ATC → om 3.87MB / ATC <2min / 134ms。验证时注意 ATC 有 kernel cache（`/root/atc_data/kernel_cache`），对比实验前要清，否则结果可能是缓存假象。详见项目 `syx_docs/summary/2026-08-02_om_perf_gap_rootcause.md`。

### 附：keep_dtype 方案——曾经规避不明精度/性能掉点，现多数冗余，备查

`--keep_dtype=<file>`（列特定算子节点保 fp32、其余走默认 fp16）**曾经是排查含自定义算子 OM 的「不明精度掉点 / 性能掉点」的有效手段**——历史上几次出现 OM 精度或性能莫名掉，加 keep_dtype 后规避了。但后续（算子升级为 AscendC op、声明 DT_FLOAT）ATC 默认就保 fp32，keep_dtype 不再必要。记录现象，备查：

- **曾有效**：FpsGe 还非 AscendC op 时，ATC 默认把 xyz 降 fp16 → FPS idx 50/512（密集点云 argmax 翻转）→ IoU 掉；加 keep_dtype 保 FpsGe fp32 → 512/512，IoU 恢复（[[2026-07-24_keep_dtype_om_iou_040]]）。
- **现冗余**：FpsGe 升级 AscendC op（DT_FLOAT）后，ATC 默认保 fp32；**清 kernel cache 对照实验**证明 keep_dtype 有无，IoU/性能/om 大小全一致（都 0.3036 / ~134ms / 3.87MB）。
- **310P3 注意**：全局 `--precision_mode=must_keep_origin_dtype` 会 ATC 失败（无 fp32 Conv 内核，Conv 报 "No supported Ops kernel"），只能 per-op `--keep_dtype`。

**何时再试**：含自定义算子的 OM 出现**不明精度掉点**（怀疑某算子被默认精度降级）或**不明性能掉点**时，加 `--keep_dtype` 排查——曾经有效，现在多数冗余，但不排除特定算子/CANN 版本下又需要。先清 kernel cache 再对照，排除缓存假象。

## 验证模式：单 op 隔离 fullgraph 测试（强烈建议，先于接 pipeline）

接真实 pipeline 前，先写**单 op 隔离测试**验证「GE 路径通 + kernel 数值对」。比直接接 pipeline 调试快得多——编译/部署一轮就能区分是集成问题还是 kernel 问题。

模板（纯 Python，不需要 C++ torch op `.so`）：

```python
import numpy as np, torch, torch_npu, torchair
from torchair.ge import Tensor

# ① 独立 namespace 注册 op（避免和 pipeline 的 torch.ops.npu.* 冲突）
LIB = torch.library.Library("ge_test", "DEF")
LIB.define("my_op(Tensor x, Tensor y) -> Tensor")

@torch.library.impl(LIB, "my_op", "Meta")
def _meta(x, y):
    return x.new_empty(...)        # 返回正确 shape/dtype

# ② GE converter：torch op → 部署的 GE 算子
@torchair.register_fx_node_ge_converter(torch.ops.ge_test.my_op.default)
def _conv(x: Tensor, y: Tensor, meta_outputs=None):
    return torchair.ge.custom_op("MyOpCustom", inputs={"x": x, "y": y}, outputs=["z"])

class M(torch.nn.Module):
    def forward(self, x, y):
        return torch.ops.ge_test.my_op(x, y)

# ③ fullgraph 跑 + CPU golden 比对
model = M().npu()
cfg = torchair.CompilerConfig()
opt = torch.compile(model, fullgraph=True,
                    backend=torchair.get_npu_backend(compiler_config=cfg))
out = opt(x.npu(), y.npu()).cpu().numpy()
assert np.allclose(out, golden)
```

运行前必须 source cann env + vendor set_env.bash + op_api LD_LIBRARY_PATH（见 step 4）。

> 实测：ball_query `[1,10,32]` int32 vs CPU golden 100%、group_points `[1,8,16,32]` float vs gather golden 100%，都是这个模板一次跑通。
>
> **torchair import 注意**：`import torchair` 只在 source 了 `set_env.sh` 之后才解析得了（实际走 `torch_npu/dynamo/torchair`），裸 `python -c "import torchair"` 会 ModuleNotFoundError。
>
> **`.npu()` 报 `'int' object is not callable`？** 多半是变量名撞了——别在 `main()` 里用 `M` 同时当类名和形状变量（`B,N,M=...`），`M()` 就变成调 int。

## 多 op 链 fullgraph 测试（单 op 全过后做）

单 op 都验证正确后，把真实数据流的多个 op 串成一个 module 编译 fullgraph，验证它们在**同一个图里协同正确**（多 op + 标准 torch op 如 gather 混编）。比直接接完整 pipeline 简单（不依赖整套环境），又能暴露多 op 图编译的问题。

```
以 PointNet2 SA 层为例：fps(xyz) → gather(取 new_xyz) → ball_query → group_points
四个 op 串成一个 SALayer.forward，fullgraph=True 编译，多组真实参数验正确
```

> 实测：fps→gather→ball_query→group_points 链 fullgraph，gather 用原生 `torch.gather`（避开 C++ ext 依赖），3 组真实参数全 PASS。

### 调试陷阱：多 op 链测试里 golden 的维度极易写错

多 op 链的 CPU golden 通常比单 op 复杂（FPS + gather + ball_query + group_points 全要 CPU 复现），**维度错误会伪装成集成 bug**。典型坑：输入是 `[B,N,3]` 3D，写 FPS 距离时 `(xyz - xyz[0]).sum(axis=1)`——axis=1 是 N，求和成 `[B,3]` 而非逐点距离 `[N]`，golden 全错，但看起来像"集成结果不对"。

排查要点：链测试 FAIL 时，**先单独打印每一步的中间结果（如 fps_idx）和单步 golden 比对**，确认是哪一步开始错——是 golden 错还是 kernel 错。别一上来就怀疑多 op 图编译。

## 已解决案例：FPS（串行依赖 + 跨核 SyncAll + 转置布局）

FPS 是三个 pointnet2 op 里最难的（跨核 SyncAll、workspace 跨核通信、kernel 假设 xyz 转置布局）。迁移过程踩了坑 8（runtime cache 致 507011）+ 坑 8b（op 级缓存吞改动），最终靠**改名新 op** + **layout 修复**解决，GE fullgraph 测试与 CPU 标准 FPS golden 完全一致（MATCH 512/512）。

**关键：kernel 假设 xyz 是 `[3,N]` 转置布局**（坐标连续，向量化距离计算需要），ctypes/eager 路调用前做了 `xyz.permute(0,2,1).contiguous()`。GE 路的等价做法：让 op 收 `[B,3,N]`（host TilingFunc 用 `GetDim(2)` 取 N），调用方/converter 负责 permute。

**生产集成注意**：pipeline 的 FPS torch op 收的是 `[B,N,3]`，converter 里需要先 transpose 成 `[B,3,N]` 再喂给 FpsGe（converter 是 Python，不受坑 8/8b 缓存影响，改动可靠生效）。

**对比**：ball_query / group_points（embarrassingly parallel，无跨核同步、无转置假设）GE 入图一次跑通且数值正确，无需这些周折。

## 官方参考

- 完整工程模板（cmake + .run 部署路）：`asc-devkit/examples/01_simd_cpp_api/02_features/99_acl_based/00_acl_compilation/custom_op/`
- 图模式 Python 接入范式（`register_fx_node_ge_converter` + `custom_op` + fullgraph）：`asc-devkit/examples/01_simd_cpp_api/02_features/00_framework/00_pytorch/ge_torchair/add_custom_test.py`
  - 注意：该样例用 `.asc` 源编进单个 `libascendc_ops.so`（EagerExecuteOp 路），和本文的 cmake/.run 部署路在 **kernel 交付方式上不同**，但 **Python 侧 converter + fullgraph 模式完全一致**，是写 converter 的最佳模板。
- gitcode：`https://gitcode.com/cann/asc-devkit`
