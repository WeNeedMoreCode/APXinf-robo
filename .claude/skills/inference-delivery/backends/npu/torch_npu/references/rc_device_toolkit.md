# RC 设备（310P1 类）适配工具集

> 拿来即抄的代码模板。出处：GR00T N1.7 RC patch（实测通过）+ Diffusion-Planner
> 2026-08 二次验证（同款 randn 崩溃、同款修法）。坑的机理与排障方法见
> [runtime_pitfalls.md 第 10 章](runtime_pitfalls.md)，本文只放工具。

适用场景：模型在 910 / 310P3（DUO）上跑通，要移植到 310P1 类 RC 设备
（Atlas davinci-mini 等，老固件/驱动）。RC 上有三类已知问题，每个配一个工具。

## 工具 1：RC 设备检测（一切分支的前提）

```python
import shutil, subprocess

_rc_device_cache = None

def is_rc_device():
    """RC boards report no 'accelerators' entry in lspci (heuristic from the
    GR00T N1.7 RC bring-up, cached after first call)."""
    global _rc_device_cache
    if _rc_device_cache is not None:
        return _rc_device_cache
    if shutil.which("lspci") is None:
        _rc_device_cache = False   # no lspci => not the target board type
        return _rc_device_cache
    out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
    _rc_device_cache = not any("accelerators" in line for line in out.stdout.split("\n"))
    return _rc_device_cache
```

用法：**所有 RC 分支都从它出发**——正常设备走原始路径一个字节不变（已验证的
基准/精度口径不受影响），RC 才切换到 workaround。不要无条件改主路径。

## 工具 2：randn 条件分流（StatelessRandomNormalV2 在 RC 上崩）

`torch.randn(device='npu')` 落到 aicpu `StatelessRandomNormalV2`，RC 固件执行不了
（errno 507018）。小张量（噪声/初始化）直接 CPU 生成再拷，代价可忽略：

```python
def randn_rc_safe(shape, dtype=torch.float32, device="npu"):
    _dev = "cpu" if is_rc_device() else device
    return torch.randn(*shape, dtype=dtype, device=_dev).to(device)

# 调用点（扩散/flow-matching 的初始噪声是最高发位置）：
noise = randn_rc_safe((B, horizon, dim), device=x.device)
```

**注意 RNG 流**：CPU 采样与设备采样的随机数流不同——对"噪声只要是标准正态"
的推理场景等价，但任何依赖具体随机序列的对拍/复现要用固定 seed + CPU 两端对齐。

**benchmark 场景的可选加速**：缓存首次噪声复用（GR00T 的 `--cache_randn`），
消除 RC 上每步的采样+拷贝，适合跑性能基准时消除噪声来源的方差。

## 工具 3：fp16 floordiv 补丁（RC 上算错）

RC 原生 floor division 在 fp16 下精度丢失产生**错误结果**（不崩，更隐蔽）。
全局 monkey-patch 成"真除再 cast"：

```python
def patch_floordiv_for_rc():
    if not is_rc_device():
        return

    def _patched_floordiv(self, other):
        tmp = self / other
        if isinstance(tmp, torch.Tensor):
            return tmp.type(self.dtype)
        return tmp.__floordiv__(other) if hasattr(tmp, "__floordiv__") else (self // other)

    torch.Tensor.__floordiv__ = _patched_floordiv
```

在模型加载前调用一次。注意语义变化：fp16 下 `(a // b)` 与 `(a / b).to(fp16)`
在边界值上有 ulp 级差异——对位置编码/索引计算等用途无感，但涉及安全逻辑时
先确认调用点。

## 工具 4：问题段"整体搬 CPU"包装（通用逃生门）

某段计算在 RC 上崩但难以逐算子改写时，把整段包装成 CPU 执行 + 结果拷回。
GR00T 对视觉 rotary 位置编码的实战写法（原地替换方法，不动上游源码结构）：

```python
if is_rc_device():
    _orig = module.rot_pos_emb

    def _cpu_safe(t):
        dev = t.device
        return _orig(t.cpu()).to(dev)

    module.rot_pos_emb = _cpu_safe
```

适用前提：该段计算量小（位置编码/索引类，ms 级）、输入输出边界清晰。
大段计算搬 CPU 会吃掉 NPU 的意义，那种情况回到逐算子处理。

## 工具 5：`jit_compile=False`（RC 上在线编译通道不可用）

RC 的 tbe 在线编译器用 multiprocessing 队列传编译结果，板上该队列的
`qsize()` 抛 `NotImplementedError` → 任何需要在线编译的算子直接失败
（`Failure_to_Compile_Op E40021` + `500002`，栈里可见 tbe 的 cast.py）。
触发面比 randn 宽：**任何"首次遇到的新形状/新算子"**（bool 掩码赋值的
NonZero、动态 shape 的 Cast……）都可能走进在线编译。DUO 上同样的
编译能成功，所以问题只在 RC 现形。

修法一行，进程最早处执行（与主推理代码同款）：

```python
import torch, torch_npu
torch.npu.set_compile_mode(jit_compile=False)  # precompiled kernels only
```

**注意独立脚本/benchmark**：主工程若已在入口设过，脱离它跑的工具脚本
（bench、探针、重放）要自己带上这行——Diffusion-Planner 的 bench_step
漏抄后在 RC 上崩于 normalizer，主闭环因 planner.py 一直设着而从未踩到。

## 集成清单（新项目移植到 RC 的接入顺序)

1. 引入 `is_rc_device()`（工具 1），进程最早处 `torch.npu.set_compile_mode(jit_compile=False)`（工具 5）
2. 检索模型内 `torch.randn(..., device=npu设备)` 的调用点 → 工具 2 分流
   （扩散/flow-matching action head 的初始噪声必查）
3. 检索 `//`（floordiv）在 fp16 tensor 上的使用 → 工具 3 补丁
4. 跑通后若仍有算子崩：`ASCEND_LAUNCH_BLOCKING=1` 定真凶（异步栈的算子名
   不可信），确认为 RC 缺失算子后用工具 4 或 CPU 化处理
5. RC 上跑性能基准：考虑噪声缓存复用（工具 2 附注）
