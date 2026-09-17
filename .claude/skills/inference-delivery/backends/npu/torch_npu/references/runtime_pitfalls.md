# NPU 运行时陷阱

按主题归类的 NPU eager 模式通用陷阱。每章独立——按你正在排查的问题对号入座。

| 你在找 | 读哪章 |
|---|---|
| CPU 准备时间 hide 到 NPU 推理时间内（流水线重叠） | 第 1 章 |
| `time.time()` 测 NPU 操作只显示几 ms，但实际几百 ms | 第 2 章 |
| 派发函数等几百 ms 才返回（应该几 ms） | 第 3 章 |
| 流水线优化没生效，代码里没 synchronize() | 第 3 章 |
| 权重切分/重组（FFN split、LoRA 合并、量化）后精度退化 | 第 4 章 |
| 用了 `format_cast_to_nz` 后对输出做切片，结果错乱 | 第 5 章 |
| 拆 transformers 模型 forward 后精度退化，hidden_states 数值变了 | 第 6 章 |
| DUO 卡上原生 Conv3D 极慢 | 第 7 章 |
| NPU 跑一段时间后莫名变慢，重启没用 | 第 8 章 |
| torch_npu 资源耗尽（event ID 满、stream 满），多步推理卡死 | 第 9 章 |
| 推理跑完卡在退出阶段，进程 kill 不掉 | 第 9 章 |
| 310P1 上 `tensor.max().item()` / fp16 floordiv / `StatelessRandomNormal` 崩 | 第 10 章 |
| GPU 和 NPU 推理结果有差异，不知是代码 bug 还是硬件 fp16 舍入 | 第 11 章 |

---

## 1. CPU/NPU 流水线重叠优化

### 原理

NPU 上的 PyTorch 操作**默认是异步执行**的。调用 `model(inputs)` 后，Python 立即返回，
NPU 在后台执行计算。只有当代码访问 tensor 的实际数据时（如 `.float()`、`.cpu()`、`.numpy()`、
`.item()`、`tensor.tolist()`），才会触发 CPU-NPU 同步，等待 NPU 计算完成。

这个特性可以被利用做 **CPU 准备工作与 NPU 推理的流水线重叠**。

### 模式：三步流水线

把推理逻辑拆成三个方法：

```python
# CPU only：数据预处理（tokenization、图片预处理、collate）
inputs = model.prepare_inputs(observation)

# NPU async dispatch：提交计算图，立即返回（几 ms）
output = model.dispatch_inference(inputs)

# NPU sync + decode：访问 tensor 数据触发同步，解码输出
action = model.decode_action(output)
```

在循环中应用流水线：

```python
inputs = model.prepare_inputs(obs_list[0])

for step in range(num_steps):
    # 1. 立即派发当前步到 NPU（异步，几 ms 返回）
    output = model.dispatch_inference(inputs)

    # 2. CPU 准备下一步数据（与 NPU 推理并行执行）
    if step + 1 < num_steps:
        inputs_next = model.prepare_inputs(obs_list[step + 1])

    # 3. 等待 NPU 完成 + 解码（访问 tensor 触发同步）
    action = model.decode_action(output)

    inputs = inputs_next
```

### 时间线对比

**优化前（串行）**：
```
CPU: [prepare]          [prepare]          [prepare]
NPU:           [infer]           [infer]
     |← CPU + NPU →|
```

**优化后（流水线）**：
```
CPU: [prepare_0] [prepare_1 overlaps] [prepare_2 overlaps]
NPU:              [infer_0]             [infer_1]
     |← max(CPU, NPU) →|
```

CPU 准备时间被隐藏在 NPU 推理时间内，总时间接近 `max(CPU, NPU)` 而非 `CPU + NPU`。

### 关键前提条件

1. **模型内部不能有 `torch.npu.synchronize()` 调用**——否则 NPU 变同步，失去重叠机会
2. **不能设置 `ASCEND_LAUNCH_BLOCKING=1`**——详见第 3 章
3. **CPU 工作必须在主线程**——利用 NPU 自身异步特性，不需要多线程，避免 processor/collator 线程安全问题
4. **下一步输入必须可预取**——离线评估场景适用；实时控制场景中下一步 obs 依赖当前步 action，无法预取

### 实测收益数据（参考）

某 VLA 模型 1 步 denoising 推理：
- 有隐式同步（`ASCEND_LAUNCH_BLOCKING=1`）：347ms
- 去掉隐式同步（流水线生效）：304ms
- 加速：43ms（12.4%）

CPU 准备时间 100ms 完全隐藏在 NPU 推理时间 320ms 内。

---

## 2. NPU 计时陷阱（time.time 测的是 dispatch 时间）

### 现象

用 `time.time()` 测一个实际耗时几百 ms 的 NPU 操作，结果显示只有几 ms。导致：
- 以为编译没生效（实际 timer 测的是派发时间，不是执行时间）
- 以为瓶颈在 eager 操作（实际 NPU 执行时间才是大头）
- profiling 加起来对不上：各步加起来 ~30ms，但实际每步 ~210ms

### 根因

NPU 操作异步执行，`time.time()` 测的是 Python 端**派发**耗时（CPU 把任务塞进队列的时间），
不是 NPU 端**执行**耗时。

### 正确做法：显式同步

```python
torch.npu.synchronize()
t0 = time.time()
output = model(inputs)
torch.npu.synchronize()
t1 = time.time()          # t1 - t0 ≈ 真实执行时间
```

```python
# 不加 synchronize
t0 = time.time()
output = model(inputs)    # 几 ms 后返回（异步派发完成）
t1 = time.time()          # t1 - t0 ≈ 几 ms（错的）
```

### 排查模式

如果 `time.time()` 不加 `synchronize()` 就测到了真实的执行时间（百 ms 级），
说明代码里或环境里有**隐式同步**在生效——参见第 3 章。

### 生产代码不能保留 synchronize

`synchronize()` 会破坏异步执行，影响流水线重叠等优化（详见第 1 章）。
**仅用于诊断**，诊断完及时移除，或用 `if profile_mode:` 包裹。

---

## 3. ASCEND_LAUNCH_BLOCKING 隐式同步

### 现象

代码里**没有显式** `torch.npu.synchronize()` 调用，但 NPU 操作仍然同步执行——
派发函数要等 NPU 跑完几百 ms 才返回。导致：
- 流水线重叠优化失效（CPU 准备时间无法隐藏）
- 任何 async/pipeline 优化都无效
- `time.time()` 不加 synchronize 也测到了真实执行时间

### 根因

环境变量 `ASCEND_LAUNCH_BLOCKING=1`，等价于 CUDA 的 `CUDA_LAUNCH_BLOCKING=1`。
该变量让**每一个 NPU 操作都强制同步**，操作完成后才返回 CPU。

通常这个变量是早期调试时设的，可能放在：
- `.bashrc` / `.profile`
- 启动脚本（`run.sh`、`start_inference.py`）
- IDE 的 launch 配置
- Docker 容器的环境变量

### 验证

```bash
echo $ASCEND_LAUNCH_BLOCKING
# 输出 1 说明在生效
```

或者在 Python 里：
```python
import os
print(os.environ.get("ASCEND_LAUNCH_BLOCKING"))
```

去掉后 NPU 操作恢复异步，派发函数几 ms 返回。

### 跟流水线重叠的关系

`ASCEND_LAUNCH_BLOCKING=1` 是流水线优化的硬性阻碍（详见第 1 章"关键前提条件"）。
即使代码完美实现了三步流水线模式，只要这个环境变量在生效，pipeline overlap 就完全无效。

### 典型踩坑路径

1. 调试 NPU 问题时设了 `ASCEND_LAUNCH_BLOCKING=1`（排查 kernel launch 错误时常用）
2. 问题解决后忘记去掉
3. 后续做异步优化时一切看起来都对，但加速效果不出现
4. 用 timer 测出来 dispatch 时间 = 执行时间，反而误以为"代码正常"——其实是同步在生效

### 教训

- **调试用的环境变量必须记录**：设置时注释原因，调试完及时去掉
- **排查"优化不生效"问题时，先 echo 一下这个变量**

---

## 4. 权重切分/重组的格式转换陷阱

### 场景

你想对模型权重做以下任何一种操作：

- **FFN Split**：把大 `Linear(in, out)` 拆成 N 个小 `Linear(in, out/N)`，提升 NPU cube 利用率
- **LoRA 合并**：把训练好的 LoRA 权重合并回基础权重
- **量化**：把 fp32/fp16 权重转 int8
- **权重预分块**：为算子优化预先重组权重布局

### 陷阱

如果在 `model.to('npu')` **之前**做权重切分，`.to('npu')` 会**对原始大权重和切分后的小权重分别做 NPU 格式转换**，产生**不同数值结果**。

### 实测数据

某 VLA 模型 FFN Split4 场景：

| 层级 | diff（max abs） |
|---|---|
| 权重本身（同一份原始权重切分前后） | 0.46 - 0.82 |
| 单层 Linear 输出 | 5 - 30 |
| 16 层累积后 MSE | 0.007586 → 0.018756（**2.5 倍**） |

经过 matmul 求和放大，权重本身的小差异被显著放大。

### 根因（推测）

`.to('npu')` 内部对 Linear 权重做格式转换（推测为 NZ/FRACTAL_NZ，未确认具体格式）。
格式转换对不同尺寸的矩阵（[6144, 2048] vs 4 × [1536, 2048]）走不同的分块策略，
转换后的数值存在微小差异。这部分是 NPU 内部实现细节，**未通过实验定位到具体格式**。

CUDA 不做这种格式转换，所以 CUDA 上不会出现此问题。

### 正确顺序

**先 `model.to('npu')`，再做权重切分**。此时模型权重已完成格式转换，切分的是已经转换好的权重，数值一致。

```python
# 错误：在 __init__ 里切分，再 to('npu')
class MyModel(nn.Module):
    def __init__(self):
        self.gate_proj = nn.Linear(2048, 6144)
        self._apply_split4()       # ❌ 切分大权重
model = MyModel().to('npu')        # ❌ 大权重和小权重分别做格式转换，数值发散

# 正确：先 to('npu')，再切分
model = MyModel().to('npu')        # ✅ 权重格式转换完成
model._apply_split4()              # ✅ 切分的是已转换好的权重
```

实际项目中常见的做法是把切分操作**延迟到首次 forward 时执行**（lazy init），通过 `_xxx_initialized` 标志位控制：

```python
def _ensure_initialized(self):
    if self._split_done:
        return
    # 此时模型已经在 NPU 上，权重格式转换已完成
    self._apply_split4()
    self._split_done = True

def forward(self, x):
    self._ensure_initialized()
    # ...
```

### 验证方法

切分前后用同一份输入跑一遍 forward，对比输出：

```python
torch.manual_seed(42)
out_before = model(x)

model._apply_split4()
torch.manual_seed(42)
out_after = model(x)

diff = (out_before - out_after).abs().max()
# 应该是 0 或极小（< 1e-5）。如果 > 0.1，说明切分引入了数值差异
```

### 通用性

任何 NPU 项目做权重重组都可能踩这个坑。CUDA 上完全等价的操作，搬到 NPU 上会出问题。

---

## 5. NZ 格式 tensor 切片不可靠

### 场景

模型用 `format_cast_to_nz(model)` / `torch_npu.npu_format_cast(weight, 29)` 把权重转成
FRACTAL_NZ 格式后，模型 forward 输出的 tensor 也在 NZ 格式中。你想对这个输出做切片，
取出某几列或某几行。

### 陷阱（实测数据）

NZ 格式 tensor 上做切片，**部分维度切片正确，部分维度切片错误**：

| 切片方式 | 结果 |
|---|---|
| 1D 切片（最后一维小范围，如 `tensor[:, 0:1]`） | ✅ 正确，max_diff = 0.007 |
| 2D 参数切片（如 `tensor[:, 0:9]`、`tensor[:, 0:7]`） | ❌ 错误，max_diff > 1.0 |

实测某模型的 MSE：0.0076 → 0.754（**100 倍退化**）。

### 根因

NZ 格式（FRACTAL_NZ）下数据按 16×16 fractal block 重排存储，不是按行优先连续排布。
PyTorch 标准切片操作按 ND（行优先）布局解读内存，跟 NZ 实际布局不匹配，取到错位数据。

小范围切片可能恰好落在单个 fractal block 内，结果碰巧正确；大范围切片跨越多个 block，
错误暴露。

### 正确做法

NZ 格式的 tensor 不能直接切片。已验证可行的方案：**把切片前的 tensor 转回 CPU 端再做切片**。
`.cpu()` 会做格式归一化，CPU 端拿到的就是普通的 ND 行优先 tensor。

```python
# 错误
sliced = nz_tensor[:, 0:9]

# 正确（已验证）
normal_tensor = nz_tensor.cpu()      # 转回 CPU，自动归一化为 ND 格式
sliced = normal_tensor[:, 0:9]
```

其他方案（如 `.contiguous()`、`.to(format=0)` 等）**未在原项目中验证**，理论上可能可行，
但不保证。

### 通用性

任何用 `format_cast_to_nz` 提速的项目，如果对模型输出做切片（比如反归一化时按 state_key
拆分多列）都会踩这个坑。CUDA 上同样的切片完全正常，搬到 NZ 格式 NPU 上会出错。

---

## 6. 拆 transformers 模型 forward 后 hidden_states 语义变化

### 场景

为了 torchair 编译、缓存优化、异步派发等目的，把 HuggingFace transformers 模型的 forward
拆成两部分（如 `_preprocess_vl_input` + `_language_model_forward`），直接调用 language_model
子模块。

### 陷阱

transformers 4.57+ 引入了 `_can_record_outputs` 机制，会自动给 decoder layer 注册 forward hook
收集 hidden_states。**但这个机制在直接调用子模块时行为会变化**：

```python
# 通过顶层调用（auto-recording 正常）
outputs = self.model(**vl_input)
outputs.hidden_states[-1]  # ✅ pre-norm，decoder 原始输出

# 直接调用 language_model 子模块（auto-recording 行为变化）
outputs = self.model.model.language_model(**kwargs)
outputs.hidden_states[-1]  # ❌ 变成 post-norm（经过 final LayerNorm）
```

### 实测数据（某 Qwen3-VL 模型）

| 调用方式 | `hidden_states[-1].mean()` |
|---|---|
| 顶层 `self.model(**vl_input)` | 0.090（pre-norm） |
| 直接 `self.model.model.language_model(...)` | 0.023（post-norm） |

差 **4 倍**。LayerNorm 把 mean 压到接近 0（0.023），pre-norm 的 decoder 原始输出 mean 较大（0.090）。

### 后果

如果代码假设 `hidden_states[-1]` 是 pre-norm（顶层调用的语义），但实际拿到的是 post-norm
（直接调子模块的语义），下游所有计算都会基于错误的 hidden_states，导致精度退化。
某项目实测 MSE 退化 **41%**。

### 根因（部分推测）

`_can_record_outputs` 的 hook 注册发生在完整的模型调用链中。直接调用 `language_model` 子模块时：
- `language_model` 本身也是 `PreTrainedModel` 子类，理论上 hook 也会注册
- 但实测 `hidden_states[-1]` 等同于 `last_hidden_state`（post-norm 值）
- **未通过实验定位具体原因**——可能是 hook 注册时机问题，也可能是 `BaseModelOutputWithPast.__init__`
  的默认值覆盖了 hook 收集的结果

确定的事实：**直接调用子模块时 auto-recording 产生的 hidden_states 跟顶层调用不同**。

### 正确做法

**不要依赖 auto-recording 机制在子模块直接调用时产生正确结果**。手动复制原 forward 的
decoder 循环逻辑，明确控制：

1. **是否包含 final LayerNorm**：根据下游需求决定
   - 需要 pre-norm（decoder 原始输出）：在 final `self.norm(hidden_states)` 之前 return
   - 需要 post-norm：包含 `self.norm(hidden_states)`

2. **拆分边界的状态传递**：
   - `attention_mask` / `create_causal_mask`
   - `position_ids` / `rotary_emb`（RoPE cos/sin）
   - `cache_position`
   - 这些数据依赖操作必须留在 eager 阶段或预处理函数中

### 验证方法

拆分前后用同一份输入跑 forward，对比输出：

```python
torch.manual_seed(42)
ref_outputs = original_model(inputs)
torch.manual_seed(42)
split_outputs = split_model(inputs)

diff = (ref_outputs.hidden_states[-1] - split_outputs).abs().max()
# 应该是 0 或极小（< 1e-5）。如果差几十倍，说明 hidden_states 语义不一致
```

### 通用性

任何 transformers 4.57+ 模型（Qwen3-VL、Llama、Qwen2 等）做 forward 拆分都可能踩。
触发条件：
- 用了 `output_hidden_states=True`
- 直接调用 `language_model` / `text_model` 等子模块
- 用了拆分出来的 `hidden_states[-1]` 作为下游输入

### 详细案例

某 Qwen3-VL 项目拆 backbone forward 的完整排查过程（含 5 轮 pdb 调试、源码分析、最终解决方案）
记录在项目级文档中。核心结论已抽象到本章节。如果想看具体推导过程，参考原项目的
拆分排查记录。

---

## 7. DUO 卡上原生 Conv3D 极慢

### 场景

模型含 Conv3D（视频理解、3D 视觉编码器、Qwen3-VL/Eagle 的 patch_embed 等）。

### 实测数据（某 VLA 模型 DUO 卡，310P3 HBM）

| 实现 | visual conv3d 耗时 |
|---|---|
| DUO 原生 `nn.Conv3d` | **31ms** |
| matmul 替代实现 | 1.2ms |

DUO 原生 Conv3D 比替代实现慢 **25 倍**。

整步推理时间：183ms → 158ms（**-25ms**），仅通过替换 Conv3D 实现。

### 现象

DUO 卡上原生 Conv3D 性能极差，比同等计算的 matmul 实现慢一个数量级。
RC 卡（310P1 DDR）的情况不同——RC 没有硬件 Conv3D 加速路径，所以早期就需要替代实现。

### 正确做法

用 Conv2d × T 或纯 matmul 重写 Conv3D。具体实现跟模型强相关，需要根据原 Conv3D 的
kernel/stride/dilation 语义对齐：

```python
# 原始
self.conv = nn.Conv3d(in_ch, out_ch, kernel_size=(t, h, w))

# 替代方案 A：T 维退化（kernel_t=1），空间维用 Conv2d
# 替代方案 B：完全用 matmul 重写
# 替代方案 C：拆成多个 Conv2d + temporal 池化
```

具体选哪种方案，取决于 Conv3D 的 kernel 形状。常见的 `(2, h, w)` / `(4, h, w)` patch_embed
可以用 Conv2d + temporal reshape 替代。

### 实现示例（T 维退化型 patch_embed）

如果原 Conv3D 形如 `kernel_size=(T, H, W)`，其中 T 维只做 temporal merge，可以：

```python
# 假设输入 (B, C, T, H, W)
x = x.permute(0, 2, 1, 3, 4).reshape(B * T, C, H, W)  # 拆 T 维
x = self.conv2d(x)                                    # Conv2d 处理空间维
x = x.reshape(B, T, out_ch, H', W').permute(0, 2, 1, 3, 4)  # 还原
# temporal 维用线性层合并
```

实际项目需要根据 Conv3D 具体形状设计替代实现，**替代后必须对比输出验证数值一致**。

### 通用性

任何 3D 视觉模型在 DUO 卡上跑都可能踩。如果性能 profile 显示某个 Conv3D 算子是瓶颈，
就考虑替换。判断方法：用 `torch_npu.profiler` 采集算子耗时，看 Conv3D 相关算子占比。

---

## 8. NPU 长时间运行后变慢（OS 重启不恢复）

### 场景

性能测试、长期推理、benchmark 采集。

### 现象（实测）

NPU 长时间运行后，**性能显著下降**，但代码完全没变。

某 VLA 模型 RC 卡（310P1 DDR）实测：

| 状态 | 每步耗时 |
|---|---|
| NPU 长时间运行后 | 330ms |
| 物理断电重启后 | **158ms** |

直接快 **2 倍**。同样的代码、同样的权重，只差 NPU 是否冷启动过。

### 关键观察

- **OS 软重启（reboot）不能恢复性能**：尝试过 OS 重启，性能不变
- **物理断电重启才能恢复**：必须切断电源，让 NPU 固件彻底冷启动

推测 OS reboot 不会重置 NPU 固件，物理断电才彻底冷启动回默认高频状态。

### 根因（未验证）

性能下降的具体机制**未通过实验定位**。可能的猜测（**均未证实**）：

- 动态调频（DVFS）降到低频后未恢复
- DDR 频率 fallback
- PCIe 链路降级
- 散热触发的降频保护

实测只知道"物理断电能恢复"，不知道具体哪个机制在降级。

### 正确做法

性能数据采集前**推荐物理断电重启一次**，避免 NPU 处于降级状态影响数据。

如果遇到"今天测出来比之前慢一倍"这种诡异情况，先怀疑这个，物理重启一次再测。

### 通用性

任何 NPU 性能测试都受影响。做 benchmark 时务必先物理重启，否则数据可能不可比。

---

## 9. torch_npu 资源耗尽 / 析构卡死的子进程隔离 workaround

### 场景

torch_npu 在多步推理场景下出现资源累积无法释放，最终撞顶卡死。常见的资源类型：

- **event 池**（Ascend 驱动硬编码上限 1024）
- **stream / context handle**
- **其他驱动级资源**

### 触发征兆

1. **多步后卡死**：前 N 步推理正常，从某一步开始突然卡住（不再前进，也不报错退出）
2. **dmesg 报错**：`grep dmesg` 能看到驱动级错误（如 `event resources are used up`、`event id exhausted`）
3. **进程重启后正常**：kill 整个 Python 进程后重启，前 N 步又能正常跑
4. **资源监测攀升**：debugfs（如 `/sys/kernel/debug/tsdrv/<device>/...`）能看到相关资源占用持续上涨，不回收

### 根因（用户层够不着）

资源泄漏发生在 torch_npu 内部，用户代码层够不着修复。需要等 CANN/torch_npu 更新修复。
在修复之前，只能用 workaround 绕过。

### Workaround 模式：子进程隔离

**核心思路**：torch_npu 资源的唯一可靠释放方式是**进程退出**——OS 强制回收。
把推理拆成多个子进程，每个子进程跑 ≤ N 步（资源累积不超上限），子进程退出后资源被 OS 回收。

### 架构

```
父进程（编排器）
│
├─ spawn 子进程 1（step 0~N-1）
│  └─ 跑完保存预测到 _OUT_FILE
│  └─ 父进程检测到 _OUT_FILE 出现 → proc.kill() 强 kill 子进程
│       （跳过 torch_npu 析构卡死阶段）
│
├─ spawn 子进程 2（step N~2N-1，用 --step-start 跳过前面的）
│  └─ 同上
│
└─ ... 直到所有 step 跑完
   合并所有 _OUT_FILE，得到完整预测
```

### 关键设计点

| 组件 | 作用 |
|---|---|
| `_STEPS_PER_BATCH` 环境变量 | 每子进程跑多少步（按资源泄漏速率算，确保累积不撞顶） |
| `_WORKER=1` 环境变量 | 标识子进程模式，跳过编排逻辑，直接跑推理 |
| `_OUT_FILE` 环境变量 | 子进程保存预测的文件路径（每个子进程不同） |
| `--step-start` 命令行参数 | 子进程跳过前 N 个 timestep（配合 `_STEPS_PER_BATCH` 推进） |
| `proc.kill()` | 子进程跑完后立即 kill，跳过 torch_npu 析构阶段 |

### 为什么必须 proc.kill()

torch_npu 在资源池接近耗尽时，进程退出阶段会**卡死**——析构钩子（atexit hooks）等永不完成的同步。
父进程 `proc.wait()` 永远等不到。

解决：父进程检测到子进程的预测文件出现（说明推理已完成），立即 `proc.kill()` 强 kill。
OS 强制回收资源，跳过卡死的析构阶段。

### 计算每子进程步数

资源泄漏速率 = 资源上限 / 单步泄漏量 / 安全系数

例如 event 池上限 1024，实测每步泄漏 340：
- 单子进程最大步数 = 1024 / 340 ≈ 3
- 留安全系数 → `_STEPS_PER_BATCH=2`

实测可以通过逐步跑 + dmesg 监测确定泄漏速率。

### 代价

每个子进程要重新加载模型权重（~30s+），N 个子进程 = N × 加载开销。

某项目实测：

| 总步数 | 子进程数 | 加载总开销 |
|---|---|---|
| 3 步 | 2 个 | 1 分钟 |
| 12 步 | 6 个 | 3 分钟 |
| 25 步 | 13 个 | 6.5 分钟 |

慢，但**确定能跑通**。

### 何时考虑这个 workaround

只有当**确认是 torch_npu 内部资源泄漏**，且**无法在用户代码层修复**时才用。判断方法：

1. `dmesg` 有驱动级资源耗尽错误 → 基本确认
2. 同样代码在新进程下能跑前几步，再累积撞顶 → 累积型泄漏
3. 用户代码加 `torch.npu.synchronize()`、显式 `del` 都无效 → 用户层够不着

如果代码层面能修复（比如显式 close stream、手动 free tensor），优先用代码层方案。

### 通用性

适用于任何 torch_npu 资源耗尽问题（不止 event pool）。模式可以套到：
- 显存碎片到一定步数后分配失败
- stream handle 泄漏
- 其他 torch_npu 内部资源累积

关键是识别"累积型泄漏"的征兆（每 N 步必崩、重启后恢复），然后套子进程隔离模式。

---

## 10. 310P1（RC 类设备）aicpu 算子集少，常见操作崩

### 场景

在 310P1（Atlas davinci-mini 等 RC 类设备）上跑模型。这些设备的 aicpu 算子集比 910 / 310P3（DUO 卡）少很多。

### 陷阱

以下常见操作在 310P1 上会触发 `Aicpu kernel execute failed`（errno 507018）：

| 操作 | 表现 |
|---|---|
| `tensor.max().item()` / `tensor.min().item()` | reduce + item 组合，aicpu 实现缺失 |
| `StatelessRandomNormalV2` 等随机数算子 | 某些 seed-based 算子不在 310P1 aicpu 列表 |
| fp16 上的 `__floordiv__` | fp16 精度问题导致内核执行失败 |

报错信息类似：
```
Aicpu kernel execute failed, errno=507018
```

### 排障两步法（实测教训，Diffusion-Planner 2026-08）

**第一步：异步栈不可信，先开 blocking 定真凶。** 异步模式下报错指向的算子名是
同步失败时抓的栈，不一定是真凶——实测报 `aclnnNonzeroV2`（布尔索引），加
`ASCEND_LAUNCH_BLOCKING=1` 重跑后真凶现形：`StatelessRandomNormalV2`
（`torch.randn` 的 aicpu 实现）；而"被指控"的 NonZero 一路跑过去没炸。
照误报的算子改代码会白干。

**第二步：多进程误伤，降单进程再定位。** 多 worker（Ray/多进程）场景下一个
worker 的 aicpu 异常会把整个设备搞挂，其余 worker 连 `torch.load` 最基础的 H2D
拷贝都报 507018——报错位置互相误导（最初以为权重加载有问题）。切单进程串行
模式（nuPlan: `worker=sequential`）复现，栈才干净。

**修完 randn 的连带提示**：把 `torch.randn(device='npu')` 换成 CPU 生成再
`.to(npu)` 后，若下游还有别的 aicpu 算子崩，重复第一步定位——同一台设备上
坏算子可能不止一个，逐个揪。GR00T N1.7 的 RC patch 还提供了 `--cache-randn`
（缓存首次噪声复用），适合 RC 上跑 benchmark 的场景。

### 根因

310P1 RC 类设备的 aicpu 算子集**比 910/310P3 少**。同样的算子在 DUO 卡上有 aicpu 实现，
在 310P1 上没有，调用时触发内核执行失败。

这不是"算子不存在"（会报 561000），而是"算子在列表里但内核执行失败"——错误信息更迷惑。

### 正确做法：搬到 CPU

把上述操作搬到 CPU 端执行：

```python
# tensor.max().item() —— 搬 CPU
val = tensor.max().cpu().item()
# 或
val = tensor.cpu().max().item()

# StatelessRandomNormal —— CPU 生成再搬 NPU
torch.manual_seed(42)
noise = torch.randn(shape, device='cpu', dtype=torch.float32).to('npu')

# fp16 floordiv —— 改成 div + cast
# 错误：result = (a // b)  # fp16 上崩
# 正确：
result = (a / b).to(a.dtype)
```

### floordiv 的特殊情况

不只是 310P1 算子集少的问题，fp16 floordiv 本身有精度问题。所有 RC 类设备（fp16 主导计算）
都可能踩这个坑。可以用 monkey-patch 全局修复：

```python
def _patched_floordiv(self, other):
    tmp = self / other
    if isinstance(tmp, torch.Tensor):
        return tmp.type(self.dtype)
    return tmp.__floordiv__(other) if hasattr(tmp, "__floordiv__") else (self // other)

torch.Tensor.__floordiv__ = _patched_floordiv
```

判断当前设备是否是 RC 类（通过 lspci 检测 accelerators 标识）：

```python
import subprocess
def is_rc_device():
    try:
        out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
        pci_info = [line for line in out.stdout.split("\n") if "accelerators" in line.strip()]
        return not pci_info  # RC 设备没有 accelerators 标识
    except Exception:
        return False
```

### 通用性

任何在 310P1 / davinci-mini / Atlas RC 类设备上的项目都会踩。910 / 310P3（DUO）上完全正常
的代码，搬到 310P1 可能直接崩。已在两个项目上独立撞到同款 randn 崩溃且修法一致
（GR00T N1.7 的 RC patch、Diffusion-Planner 2026-08），证据链充分。注意 OM 路径
（ONNX→ATC）的算子同样跑在 NPU 上、并非天然免疫，只是尚未有 OM 项目撞到过此坑
（未深究原因）。常见踩坑位置：

- 评估脚本里 `metric = pred.max().item()` 这类 reduce+item 调用
- 数据增强里的随机数生成
- 任何用 `//` 做整数除法的 fp16 tensor 操作

排查方法：报错信息含 `Aicpu kernel execute failed` 或 `errno=507018` → 基本确认是 310P1 算子集问题。

**修法工具集**（is_rc_device 检测、randn 条件分流、floordiv 补丁、整段搬 CPU 包装、
RC 移植接入清单）见 [`rc_device_toolkit.md`](rc_device_toolkit.md)——拿来即抄的代码模板。

---

## 11. 三层对比法：区分代码 bug 和硬件 fp16 舍入

### 场景

模型从 CUDA 移到 NPU 后，输出有精度差异。需要确认：
- 差异是**代码适配 bug**（必须修）
- 还是**硬件 fp16 舍入**（属于硬件实现差异，无法消除，但符合预期）

直接对比 GPU vs NPU 的输出无法区分这两种情况，因为差异里混了**输入差异**（视频解码器、随机数、
预处理顺序）。

### 三层对比法

跑三次对比，分别验证：

| 层次 | 跑在哪 | 验证什么 |
|---|---|---|
| 1. 硬件 fp16 对比 | GPU 硬件 vs NPU 硬件 | 测原始差异（含 fp16 舍入 + 输入差异） |
| 2. CPU fp16 对比 | GPU-CPU vs NPU-CPU | CPU 上没有硬件 fp16 单元，PyTorch 用 fp32 中间计算 |
| 3. 输入对齐 | GPU 侧保存输入 → NPU 侧加载同样输入 | 消除输入差异 |

### 判断逻辑

```
CPU 上两平台一致（MSE < 0.1%）+ 硬件有差异（MSE > 1%）
  → 确认是硬件 fp16 舍入，代码适配正确（不需要修）

CPU 上两平台也有差异
  → 代码层有 bug（需要修）
```

### 实测数据示例（某 transformer 模型 24 层）

**硬件 fp16 对比**：

| 检查点 | GPU | NPU | 差异 |
|---|---|---|---|
| pixel_values | -0.570096 | -0.570096 | 完全一致 |
| block05 | 0.175765 | 0.175766 | 1e-6 |
| block11 | 0.145370 | 0.145368 | 2e-6 |
| block17 | 0.094921 | 0.094918 | 3e-6 |
| block23 | 0.875229 | 0.875831 | 602e-6 |
| 最终 MSE | 0.008562 | 0.009353 | **9.2%** |

**CPU fp16 对比**：

| 检查点 | GPU-CPU | NPU-CPU | 差异 |
|---|---|---|---|
| block05 | 0.175768 | 0.175768 | 完全一致 |
| block11 | 0.145372 | 0.145372 | 完全一致 |
| block17 | 0.094920 | 0.094920 | 完全一致 |
| block23 | 0.876400 | 0.876395 | 5e-6 |
| 最终 MSE | 0.007949 | 0.007951 | **0.025%** |

**结论**：CPU 上 MSE 仅差 0.025% → 代码适配完全正确；硬件差异 9.2% 是 fp16 舍入累积放大，符合预期。

### 输入对齐工具：保存/加载 .pt 文件

为了让 GPU 和 NPU 跑同样的输入，可以用通用模式：

```python
# GPU 侧（保存输入）
if save_input_mode:
    torch.save({
        'pixel_values': pixel_values.cpu(),
        'text_embeds': text_embeds.cpu(),
        # ... 所有 forward 输入
    }, f'input_step_{step}.pt')

# NPU 侧（加载输入）
if load_input_mode:
    data = torch.load(f'input_step_{step}.pt')
    pixel_values = data['pixel_values'].to('npu')
    # ...
```

注意：
- 保存时搬到 CPU（避免 device 冲突）
- 加载后再搬到目标 device
- 所有 forward 输入都要保存，否则对比失败

### 逐层检查点（CKPT）插入

在 forward 的关键位置插入检查点打印，对比两平台的中间值：

```python
# 在每个 transformer block 后插入
if debug_ckpt:
    print(f"[CKPT-block{idx}] hidden_states mean={hidden_states.mean().item():.6f}")
```

对比时，找到**第一个出现差异的位置**，集中排查那一层。常见发现：

- 前几层完全一致 → 排除前面的问题
- 中间某层开始有微小差异 → 是 fp16 舍入起点
- 后面层差异逐渐放大 → 累积效应

### 关键观察：CPU fp16 实际是 fp32 精度

CPU 没有原生 fp16 运算单元，PyTorch 在 CPU 上用 fp32 做中间计算再转回 fp16。所以：
- CPU 上 fp16 tensor 的计算精度 ≈ fp32
- 两平台在 CPU 上几乎位级一致
- 这正是三层对比法的核心——用 CPU 作为"参考答案"验证代码适配正确性

### 通用性

任何跨 CUDA/NPU 的精度排查都能用这套方法。前提：

1. 模型能在 CPU 上跑（小 batch）
2. 输入能序列化为文件（图像、文本 token、state 等）
3. forward 内部能插入检查点

### 排查方法论总结

1. **不要直接对比 GPU 硬件 vs NPU 硬件**——差异里混了输入差异
2. **先用输入对齐消除输入差异**
3. **再用三层对比法区分代码 bug vs 硬件 fp16 舍入**
4. **找到第一个出现差异的层**，集中排查

这套方法能避免把硬件 fp16 舍入误判为代码 bug，浪费大量排查时间。








