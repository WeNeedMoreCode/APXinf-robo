# TorchAir 图模式路径

## 概述

TorchAir 是华为提供的 PyTorch 图模式加速方案。通过 `torch.compile` + TorchAir 后端，将 eager mode 的模型转为 NPU 图模式执行，获得算子融合和内存优化收益，无需导出 ONNX。

图化后端到端仍慢、或两块板同图性能差异大时，问题常在**图外残留的小算子串**（发射邮费）——诊断方法与削减策略见跨路径公共文件 [../references/LAUNCH_OVERHEAD.md](../references/LAUNCH_OVERHEAD.md)。

## 核心原则

1. **import 顺序**：`import torch_npu` 必须在 `import torch` 之后立即执行，
   因为它会在导入时 monkey-patch torch.cuda 的相关调用。
2. **device 和 dtype**：`model.to(device, dtype)` 在 NPU 上一般可直接使用。
   若遇到 "Torch not compiled with CUDA enabled" 再拆成 `model.to(device)` + `model.half()`。
3. **Conv3d 的 half/npu 顺序**：`conv.half().to(npu)` 会把 half 权重重置回 float32。
   正确顺序是先 `to(npu)` 再 `half()`。
4. **jit_compile 是全局设置**：`torch_npu.npu.set_compile_mode(jit_compile=False)`
   影响整个进程，不能按模块单独设置。

---

## 基本用法

```python
import torch
import torch_npu
import torchair as tng
from torchair.configs.compiler_config import CompilerConfig

config = CompilerConfig()
config.experimental_config.frozen_parameter = True
config.experimental_config.tiling_schedule_optimize = True
npu_backend = tng.get_npu_backend(compiler_config=config)

# 编译指定方法
compiled_fn = torch.compile(
    model.some_method,
    dynamic=False,
    fullgraph=True,
    backend=npu_backend,
)
model.some_method = compiled_fn
```

**重要**：`fullgraph=True` 会完整 trace 整个调用链。如果被 trace 的代码中包含 Dynamo 无法 trace 的操作
（例如某些 `torch_npu` 内部实现、复杂的 `setattr` 模式），编译会失败。此时应编译小而明确的方法，
而不是直接编译庞大的 transformers `forward`。**不要用 `fullgraph=False`**——它会产生
不一致的编译结果，排查问题更困难。

---

## jit_compile 模式

| 模式 | 行为 | 适用场景 |
|---|---|---|
| `jit_compile=True`（默认） | 首次执行时动态编译算子 | 开发调试，或遇到 "Op X does not has any binary" 时 |
| `jit_compile=False` | 只使用预编译算子，无 JIT 开销 | 生产推理，追求稳定性能 |

### 选择性 JIT

如果某个算子在 `jit_compile=False` 下缺少预编译内核，但你想让网络其余部分保持 `False`，
可以只给该算子的 `forward` 包一层 wrapper，临时切到 `True`：

```python
_orig_forward = problematic_module.forward

def _selective_jit_forward(x):
    import torch_npu
    torch_npu.npu.set_compile_mode(jit_compile=True)
    try:
        out = _orig_forward(x)
    finally:
        torch_npu.npu.set_compile_mode(jit_compile=False)
    return out

problematic_module.forward = _selective_jit_forward
```

注意：如果该算子后续被 torchair 编译（整网编译时），就不需要选择性 JIT 了，
torchair 会处理好。选择性 JIT 只在 eager 模式下需要。

---

## Attention 实现

NPU 在很多 transformers 版本下不支持 `flash_attention_2` 和 `sdpa`，需要强制 eager：

```python
extra_kwargs["attn_implementation"] = "eager"
```

### FlashAttention 融合算子（首选）

eager 模式下，**首选**昇腾提供的融合 FA 算子替代手写 matmul+softmax+matmul。
融合算子省掉 `[B, H, S, S]` fp16 中间张量（DDR 带宽瓶颈场景下收益尤其大），
且内部常用在线 softmax，**精度可能反而优于** 手写 `softmax(dtype=fp32).to(fp16)`。

**算子选择按芯片系列**：

| 算子 | 适用芯片 | 典型场景 |
|---|---|---|
| `torch_npu.npu_fusion_attention` | 910 系列 / A2 / A3 训练卡 | 通用 FA（训练 + 推理） |
| `torch_npu.npu_fused_infer_attention_score` (FIA) | 800I A2 / A3 推理卡 | LLM decode + KV cache + PageAttention |
| `torch_npu.npu_prompt_flash_attention` (PFA) | **310P 等老推理卡** | encoder/visual 全量 attention |

**决策树**：

```
要替换 attention
├─ 训练卡（910 / A2 / A3）？           → npu_fusion_attention
├─ 推理卡 + LLM decode + KV cache？    → npu_fused_infer_attention_score (FIA)
└─ 推理卡 + encoder/visual 全量？      → npu_prompt_flash_attention (PFA)
```

**关键陷阱**：FIA 的官方支持芯片**不含 310P**，调用会失败。310P 必须用 PFA。
两者参数名也不同：

| 项 | FIA | PFA |
|---|---|---|
| head 数参数名 | `num_heads` | `num_heads` |
| scale 参数名 | `scale` | **`scale_value`** |
| 返回值 | `(out, softmax_lse)` 元组 | 单个 tensor |

#### 替换流程

1. **查芯片型号**：`torch.npu.get_device_name(0)`（如 `Ascend 310P3` → PFA）
2. **查接口签名**：`help(torch_npu.xxx)`，不同 torch_npu 版本参数有差异，文档可能滞后
3. **写最小测试**：4-5 个 case 验证精度（vs 现实现）+ 性能（speedup）
4. **替换 patch**：注意 contiguous 要求（见下）
5. **全链路验证**：单算子 OK 不代表 N 层累积 OK，要跑完整模型对齐 MSE/MAE

#### contiguous 要求

融合 FA 算子**不接受非连续 tensor**。`permute` / `transpose` 后必须 `.contiguous()`：

```python
q = q.reshape(B, S, N, D).permute(0, 2, 1, 3).contiguous()  # 不能省 .contiguous()
attn_out = torch_npu.npu_prompt_flash_attention(
    q, k, v, num_heads=N, input_layout="BNSD", scale_value=scale,
)
```

contiguous 会触发一次拷贝，但相对融合算子省下的中间张量读写，净收益仍正。

#### 310P（推理系列加速卡）的限制

PFA 在 310P 上有额外约束（vs A2/A3）：

- 数据类型**仅 fp16**（不支持 bf16/int8）
- 不支持 `actual_seq_lengths` / `actual_seq_lengths_kv`（变长场景）
- `sparse_mode` **仅支持 0**（causal 等其他模式要靠手动构造 atten_mask 矩阵）
- `pre_tokens` 仅默认值，`next_tokens` 仅 0 或 2147483647
- 轴上限：B ≤ 128, N ≤ 256, S ≤ 65535, D ≤ 512
- **`atten_mask` 约定**：2D bool 张量，`True = mask-out`（不参与 attention）。causal 场景用 `~torch.tril(ones(S,S,bool))`，上三角 True 屏蔽未来 token。约定容易搞反，验证参考 `references/gr00t_n1d7_example.md` 第 11 节
- **S 16 对齐（隐藏约束）**：使用 `atten_mask` 时 S 必须是 16 的倍数，否则报 "attention mask must be NULL, when Qs,Kvs is unAlign"。这条不在官方文档，是 tiling 实现的隐性约束。不传 `atten_mask`（纯 encoder 全量 attention）不受此限制

典型 encoder attention 场景（B=4, N=16, S=256, D=128）全部满足，无需 atten_mask 也满足 16 对齐。

#### 精度可能反而变好

不要默认以为手写 fp32 中间 softmax 是最优。融合算子内部常用更稳定的数值算法
（在线 softmax 等），实测某 16 层 visual encoder 替换后 **MSE 反而降了 11%**，
具体数据和 case 见 [references/gr00t_n1d7_example.md](references/gr00t_n1d7_example.md) 第 11 节。

#### 短序列收益评估（重要）

microbenchmark 测出的 PFA 加速比**不能直接套到实际场景**——PFA 有固定开销（kernel launch / mask 创建 / GQA repeat_kv / padding），短序列下这些开销占比大，长序列下的高加速比会骤减。

实测对照（同样硬件、同样 N=16, D=128, fullgraph 编译）：

| 序列长度 S | PFA vs 显式 attention 加速比 |
|---|---|
| S=1024 | **11.48x** |
| S=277（实际 LM 场景）| **1.3x** |

替换前必须做这两步评估：

1. **测实际序列长度下的 PFA 加速比**，不要拿长序列数字外推
2. **估算 attention 占总阶段时间的比例**：如果阶段是 FFN-bound（attention 占 <20%），换 PFA 顶多省 5% 总时间，搭精度风险不划算

判断 attention 占比的方法：用 `torch_npu.profiler` 采集算子级数据，按 op type 聚合 PromptFlashAttention / Matmul 各自的总耗时（注意融合算子拆分，可用 `op_ratio_analyzer.py`）。详见 `torch-npu-profiler` skill。

具体反例（LM S=277 上 PFA 只省 5ms / 95ms）见 [references/gr00t_n1d7_example.md](references/gr00t_n1d7_example.md) 第 12 节。

---

### 显式 matmul + softmax（融合算子不可用时的 fallback）

如果融合算子在当前芯片 / torch_npu 版本不可用，回退到显式实现。NPU 上的
`F.scaled_dot_product_attention` 数值行为与原始 eager 路径可能不同，建议显式展开：

```python
# 替代 F.scaled_dot_product_attention
attn_weights = torch.matmul(q, k.transpose(-2, -1)) * scaling
attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(q.dtype)
attn_output = torch.matmul(attn_weights, v)
```

`softmax(dtype=torch.float32)` 在 NPU 和 CUDA 上行为一致，避免 fp16 softmax 的
数值差异。这在视觉编码器等高精度要求的场景中尤其重要。

---

## RoPE（旋转位置编码）替换

用 `torch_npu.npu_rotary_mul` 替换标准 RoPE 实现：

```python
def apply_npu_rope(q, k, cos, sin, position_ids=None, unsqueeze_dim=1):
    cos = cos.unsqueeze(unsqueeze_dim)
    sin = sin.unsqueeze(unsqueeze_dim)
    n_q = q.shape[1]
    n_k = k.shape[1]
    merged_states = torch.cat([q, k], dim=1)
    merged_rot = torch_npu.npu_rotary_mul(merged_states, cos, sin)
    q_embed, k_embed = merged_rot.split([n_q, n_k], dim=1)
    return q_embed, k_embed

# 给模型的 RoPE 函数打补丁
import transformers
transformers.models.qwen3.modeling_qwen3.apply_rotary_pos_emb = apply_npu_rope
```

---

## FRACTAL_NZ 权重格式

torchair 图编译前，把 Linear 层权重转成 FRACTAL_NZ 格式以优化内存布局：

```python
import torch_npu

FRACTAL_NZ = 29
for name, module in model.named_modules():
    if isinstance(module, torch.nn.Linear):
        if hasattr(module, "weight") and module.weight is not None:
            weight_nz = torch_npu.npu_format_cast(module.weight, FRACTAL_NZ)
            module.weight = torch.nn.Parameter(weight_nz, requires_grad=False)
```

---

## 进阶模式

以下是从实际项目（视觉语言模型、24 层 ViT + LLM）中提炼的通用适配模式。

### 1. Forward 拆分模式：eager 预处理 + compiled 推理

大型模型（VLM、ViT+LLM 等）的 forward 通常包含两类操作：
- **数据依赖操作**：动态 shape、条件分支、`torch.linspace`、`.tolist()`、`.item()`、
  Python 循环依赖运行时值 — **不可编译**
- **纯 tensor 运算**：矩阵乘法、LayerNorm、attention、MLP — **可编译**

解决方案：把 `forward` 拆成两步：
1. `_preprocess()` — 所有数据依赖操作（eager，不编译）
2. `_forward()` — 纯 tensor 运算（可被 torchair 编译）

```python
class MyBackbone(nn.Module):
    def _preprocess(self, inputs):
        """数据依赖预处理，不可编译。"""
        position_ids = compute_positions(inputs)  # .tolist(), 条件分支等
        mask = create_causal_mask(...)             # 数据依赖
        embeddings = scatter_images(...)            # 数据依赖
        return {"embeddings": embeddings, "mask": mask, ...}

    def _forward(self, embeddings, mask, ...):
        """纯 tensor 运算，可被 torchair 编译。"""
        for layer in self.layers:
            embeddings = layer(embeddings, attention_mask=mask, ...)
        return embeddings

    def forward(self, inputs):
        kwargs = self._preprocess(inputs)  # eager
        return self._forward(**kwargs)       # compilable
```

编译时只编译 `_forward`：
```python
compile_for_npu(model.backbone, "_forward")
```

**关键**：`_preprocess` 中的数据依赖操作不能被 Dynamo trace。把它们集中到一个方法中，
确保 `_forward` 内部没有任何数据依赖。

### 2. 静态值缓存模式

对于输入 shape 固定的推理场景，很多"看起来动态"的值其实是常量。
在模型首次推理时预计算并缓存，后续步直接使用：

```python
def _ensure_cache(self):
    """首次推理时预计算静态值。绕过 torch.linspace/.tolist/.item 等编译障碍。"""
    if self._cache_initialized:
        return

    # 固定的 grid 配置
    grid = torch.tensor([[1, 16, 16]] * 4, ...)

    # 缓存位置编码
    self._cached_pos_embeds = self.model.compute_pos_embeds(grid)

    # 缓存旋转编码
    rotary = self.model.compute_rotary(grid)
    self._cached_pe_cos = rotary.cos()
    self._cached_pe_sin = rotary.sin()

    # 缓存 attention 的 cu_seqlens
    cu_seqlens = compute_cu_seqlens(grid)
    self._cached_cu_seqlens = cu_seqlens

    self._cache_initialized = True
```

然后在 `_forward` 中使用缓存值（纯 tensor 运算，可编译）：
```python
def _forward(self, hidden_states):
    pos_embeds = self._cached_pos_embeds.to(hidden_states.device, hidden_states.dtype)
    pe_cos = self._cached_pe_cos.to(hidden_states.device, hidden_states.dtype)
    pe_sin = self._cached_pe_sin.to(hidden_states.device, hidden_states.dtype)
    # ... 使用缓存值进行计算
```

### 3. 2D vs 3D 张量精度

**关键发现**：torchair 编译时，2D `[seq, dim]` 张量经过 Linear/LayerNorm 使用的内核
精度**低于** 3D `[batch, seq, dim]` 张量。这在深网络（20+ 层）中会导致显著精度退化。

**现象**：
- 编译单个 block 后精度立即退化（如 MSE 从 0.0093 变成 0.0104）
- 层数越多退化越严重

**解决方案**：给 2D 张量添加假 batch 维度，让 torchair 使用 3D 内核：

```python
# 编译的 forward 中
hidden_states = hidden_states.unsqueeze(0)  # [seq, dim] → [1, seq, dim]

for layer in self.layers:
    hidden_states = layer(hidden_states, ...)  # 3D → 3D，高精度内核

hidden_states = hidden_states.squeeze(0)  # [1, seq, dim] → [seq, dim]
```

**适用条件**：当模型原始输入是 2D（如 ViT 的 `[num_patches, embed_dim]`），
且需要被 torchair 编译时。

**验证方法**：对比编译前后某个 block 的输出 mean/std，如果差异 >1e-4，
就说明需要 3D 修复。

### 4. Monkey-patch 替换不可编译操作

HuggingFace 模型中常有动态操作阻碍编译。解决方案：monkey-patch 其 forward 方法。

**典型模式**：`torch.split(lengths.tolist(), dim=2)` 创建数据依赖的 symbolic shape。

**修复**：如果 `lengths` 在推理时是固定值，用 reshape 替代：

```python
def _patch_attention(visual):
    num_images = 4
    tokens_per_image = 256  # 固定值

    for blk in visual.blocks:
        attn = blk.attn
        # 捕获闭包变量
        nh, hd, sc, pr, qkvl = (
            attn.num_heads, attn.head_dim, attn.scaling, attn.proj, attn.qkv
        )

        def _make_forward(nh, hd, sc, pr, qkvl, n_img, tpi):
            def _forward(self_attn, hidden_states, cu_seqlens=None,
                         position_embeddings=None, **kw):
                seq_length = hidden_states.shape[-2]
                was_3d = hidden_states.ndim == 3
                # QKV 投影（保留原始 ndim 以便 torchair 选择合适的内核）
                qkv_out = qkvl(hidden_states)
                q, k, v = (
                    qkv_out.reshape(seq_length, 3, nh, hd)
                    .permute(1, 0, 2, 3)
                    .unbind(0)
                )
                # reshape 到静态 batch（替代 torch.split(lengths.tolist())）
                q = q.reshape(n_img, tpi, nh, hd).permute(0, 2, 1, 3)
                k = k.reshape(n_img, tpi, nh, hd).permute(0, 2, 1, 3)
                v = v.reshape(n_img, tpi, nh, hd).permute(0, 2, 1, 3)

                # 显式 matmul + softmax(float32) + matmul
                attn_weights = torch.matmul(q, k.transpose(-2, -1)) * sc
                attn_weights = F.softmax(
                    attn_weights, dim=-1, dtype=torch.float32
                ).to(q.dtype)
                attn_output = torch.matmul(attn_weights, v)

                # reshape 回来
                attn_output = (
                    attn_output.permute(0, 2, 1, 3)
                    .reshape(seq_length, -1)
                    .contiguous()
                )
                if was_3d:
                    attn_output = attn_output.unsqueeze(0)
                attn_output = pr(attn_output)
                return attn_output
            return _forward

        attn.forward = _make_forward(
            nh, hd, sc, pr, qkvl, num_images, tokens_per_image
        ).__get__(attn, type(attn))
```

**要点**：
- 用 `__get__` 绑定到实例，保持 `self` 引用正确
- 用工厂函数 `_make_forward` 捕获闭包变量，避免循环变量捕获问题
- 保留 `was_3d` 检查以支持 2D 和 3D 输入

### 5. 不支持的写法

torchair 编译不支持以下写法，需替换：

| 不支持 | 替代方案 |
|---|---|
| `tensor[:, indices] += value`（in-place index assign） | `tensor.scatter_add_(1, idx, value)` 或 `tensor = tensor.scatter_add(1, idx, value)` |
| `tensor[:, indices] = value`（index assign） | `tensor.scatter(1, idx, value)` |
| `torch.split(lengths.tolist(), dim)`（动态 split） | reshape 到固定 shape |
| `x[valid_mask]` 剔除 + scatter 回零（padded batch 常见） | 行独立模块：全量计算 + 输出乘 valid mask 置零（bit-exact） |
| `if tensor.sum() > 0:`（数据依赖分支） | `torch.where`（两侧都算，按位选）；重分支则外提 eager |
| `torch.atan2` 等无 GE converter 的算子 | 含该算子的最小数据流独立段外提 eager |

报错信息、根因分析、deepstack 演进案例（gather/scatter → scatter_add 实测省 11ms）、
布尔散回根治的等价性论证详见
[`references/compiler_constraints.md`](references/compiler_constraints.md)。

### 6. fp16 硬件精度预期

NPU 和 CUDA 的 fp16 运算单元实现不同，每步操作有微小舍入差异（~1e-7）。
经过 20+ 层 transformer 逐层累积，差异会放大到 ~1e-4 级别。

**预期表现**：
- 单步 mean 差异：block 0 约为 0，block 5 约 1e-6，block 23 约 6e-4
- 最终 MSE 相对差异：~5-10%
- MAE 相对差异通常更小（< 5%）

**这是正常的**，不是代码 bug。在 CPU 上运行两边结果几乎完全一致（MSE 相对差异 <0.1%），
证明代码适配完全正确。

**调试建议**：如果需要确认精度差异是否来自代码而非硬件：
1. 两边都用 CPU 运行（PyTorch CPU fp16 实际用 fp32 计算，精度更高）
2. 对比 CPU 结果——如果一致，说明差异纯粹是硬件 fp16 舍入

**注意**：CPU fp16 的"高精度"是假象——PyTorch CPU 用 fp32 做中间计算再转回 fp16。
生产环境跑在 NPU 上仍然会有 fp16 硬件差异。

### 7. 精度排查方法论

当 NPU 推理精度与参考平台（CUDA）不一致时：

1. **对齐输入**：用 `torch.save` 保存参考平台的输入，在 NPU 上 `torch.load` 加载，
   排除数据预处理差异。
2. **逐层插桩**：在模型关键节点打印 mean/std（而非保存整个 tensor），
   定位差异首次出现的位置。
3. **block 内部插桩**：用 `register_forward_hook` 在子模块（norm1, attn, norm2, mlp）
   上挂钩，精确定位到具体操作。
4. **CPU 对照**：两边都用 CPU 运行，如果一致则差异是硬件 fp16 而非代码问题。

### 8. 编译粒度策略

推荐使用分级编译控制，便于逐步验证每个编译模块的精度：

```python
# 0=不编译，1=编译主要部分，2=编译全部（包括视觉编码器）
compile_level = 2

if is_npu and compile_level:
    format_cast_to_nz(model)
    if compile_level >= 2:
        compile_for_npu(model.backbone, "_compiled_visual_forward")
    compile_for_npu(model.backbone, "_language_model_forward")
    compile_for_npu(model.action_head, "forward")
```

好处：可以逐步验证每个编译模块的精度，而不是一次性全编译出问题后难以定位。

### 9. 性能插桩：编译函数内禁止 `time.time()`

定位编译函数内部瓶颈时，**不能**在 `fullgraph=True` 编译的方法体内直接调用 `time.time()`、`time.perf_counter()` 等 Python 内置计时函数。

**报错**：
```
torch._dynamo.exc.Unsupported: Attempted to call function marked as skipped
Explanation: Dynamo does not know how to trace the builtin `time.time.`
```

**关键陷阱**：`if _prof: t0 = time.time()` 这种保护**无效**。Dynamo 在 trace 时仍会进入 True 分支的 body 并尝试 trace `time.time()`，因为 `_prof` 是 module 属性、运行时才确定，trace 阶段必须把两个分支都看一遍。`torch.npu.synchronize()` 倒是可以入图，但 `time.time()` 不行。

#### 正确做法：拆子方法 + eager 编排

把编译函数拆成多个**独立编译的小方法**，由一个 **eager 编排方法**依次调用并计时。生产路径走原来的大编译函数，profile 路径走 eager 编排方法。

**三种角色**：

```python
class MyModule(nn.Module):
    # 角色一：生产路径的编译函数（保持原样）
    def _big_compiled_fn(self, x):
        ...  # 完整逻辑，被 torchair 整体编译
        return out

    # 角色二：拆出的独立编译子方法
    def _stage_a(self, x):
        """stage A: 可独立编译"""
        ...
        return intermediate

    def _stage_b(self, intermediate):
        """stage B: 可独立编译"""
        ...
        return out

    # 角色三：eager 编排器，**不要**编译它
    def _big_fn_profiled(self, x):
        _sync = getattr(self, '_profile_sync', False)

        if _sync: torch.npu.synchronize()
        t0 = time.time()
        intermediate = self._stage_a(x)        # compiled
        if _sync: torch.npu.synchronize()
        t_a = (time.time() - t0) * 1000

        if _sync: torch.npu.synchronize()
        t0 = time.time()
        out = self._stage_b(intermediate)      # compiled
        if _sync: torch.npu.synchronize()
        t_b = (time.time() - t0) * 1000

        logging.info(f"[PROF] big_fn:  a={t_a:.1f}  b={t_b:.1f}")
        return out

    # 在 eager 外层 forward 里分发
    def forward(self, x):
        _prof = getattr(self, '_enable_profiling', False)
        if _prof:
            out = self._big_fn_profiled(x)
        else:
            out = self._big_compiled_fn(x)
        return out
```

**注册时**：所有子方法都要单独 `compile_for_npu`，但 `_big_fn_profiled` 不能编译：

```python
compile_for_npu(model, "_big_compiled_fn")    # 生产路径
compile_for_npu(model, "_stage_a")            # profile 路径子方法
compile_for_npu(model, "_stage_b")            # profile 路径子方法
# 不要 compile _big_fn_profiled！
```

#### 关键点

1. **生产路径零影响**：原 `_big_compiled_fn` 还是被整体编译，inline 调用链不变
2. **profile 路径略有 eager 开销**：子方法之间有 Python 派发开销（每个调用 ~0.1ms），且 dtype/cast 等小操作如果留在编排器里会变 eager。但相对子方法内部几十毫秒的耗时，这部分可以忽略，**比例是可信的**
3. **`_sync` 必须为 True**：否则测的是 kernel launch 时间（几毫秒），不是真实执行时间（几十毫秒）。每个 `time.time()` 前都要 `torch.npu.synchronize()`
4. **首次调用会有编译时间**：profile 路径的子方法是独立编译的，首次调用要 trace + 编译，稳态数据要跳过前几步

#### 替代方案：profile 时全 eager

如果不想拆方法，可以在 profile 时完全跳过编译：

```python
def forward(self, x):
    _prof = getattr(self, '_enable_profiling', False)
    if _prof:
        out = self._big_fn_eager_with_timing(x)   # 纯 eager，随便 time.time
    else:
        out = self._big_compiled_fn(x)             # 编译
    return out
```

简单，但 profile 数据**不能代表生产性能**——eager 模式下算子分布、调度都不一样。只用于看大概比例。

#### 何时用哪种

| 目标 | 方案 |
|---|---|
| 找瓶颈在哪个子阶段（占比） | 拆子方法 + eager 编排（方案 A） |
| 验证生产路径绝对耗时 | eager 外层 `forward()` 计时（已有），不动编译函数 |
| 不在乎精度，只想看大概比例 | profile 时切全 eager（方案 B） |

具体项目案例（含报错原文和最终代码）见 [references/gr00t_n1d7_example.md](references/gr00t_n1d7_example.md) 第 10 节"视觉编码器内部插桩"。

### 10. cache_compile：编译产物跨进程持久化

`torch.compile(body, backend=npu_backend)` 的图缓存是**进程内**的——每个 worker
进程（Ray / dataloader worker / 多次起服务）首次调用都重新编译（大图 30s+）。多
worker 场景下编译时间 ×N 纯浪费。

`torchair.inference.cache_compile` 把编译产物序列化落盘，后续进程直接加载：

```python
import torchair

config = torchair.CompilerConfig()
compiled = torchair.inference.cache_compile(
    body.forward,                      # 注意：只接受 bound method，不接受 module 实例
    config=config,
    dynamic=False,
    cache_dir="/data/cache/torchair",  # 不传则 $TORCHAIR_CACHE_HOME 或 ./.torchair_cache
)
out = compiled(x, ...)                 # 用法与 torch.compile 产物一致
```

**实测**（Diffusion-Planner，两图 encoder+DiT body，2026-08）：
- 首步编译 74s → 35s（cache 命中后仍剩 GE 侧首次加载）
- **意外收益：warm 每步还快了 ~4ms**——`torch.compile` 每次调用过 dynamo guard
  （Python 帧捕获 + guard 匹配），cache_compile 重放 marshal 出来的编译产物，
  每步调度路径更薄

**两个坑**（源码级确认，torchair 7.2）：
1. cache key = `str(module)` + config 选项的 md5，**不含 forward 源码 hash**——改了
   模块代码但结构没变，会**静默加载旧图**。改代码后删 cache 目录或换 `cache_dir`。
2. 只接受 `nn.Module` 的 bound method（`body.forward`），传 module 实例直接
   `ValueError: Only method can be cached now`。

---

## 权重操作时序

对模型权重做切分/重组等操作时，必须在 `model.to('npu')` **之后**执行。

`model.to('npu')` 会对权重做内部格式转换。如果先切分再搬到 NPU，原始权重和切分权重
分别做格式转换后数值不一致，经过 matmul 求和放大后导致显著精度退化。

实测案例见 [references/gr00t_n1d7_example.md](references/gr00t_n1d7_example.md) 的"FFN Split4 权重时序"章节。

## 常见编译失败原因

| 错误 | 原因 | 解决方案 |
|---|---|---|
| `Failed to trace builtin operator setattr` | torch_npu 内部的 setattr 模式 | 用 `torch_dtype` 预设 dtype 避免 `.type()` 调用；拆分 forward |
| `ge_converter is not implemented`（如 atan2） | GE 后端没写该 ATen op 的图转换器（eager 正常，硬件有算子） | 含该算子的最小数据流段外提 eager（约束文档第 5 章有三类障碍速查表） |
| `Op X does not has any binary` | 算子缺少预编译内核 | 选择性 JIT 或全局 `jit_compile=True` |
| 编译后精度显著退化 | 2D tensor 使用低精度内核 | 添加假 batch 维度（unsqueeze） |
| `torch.split` 动态 shape | `.tolist()` 创建数据依赖 shape | monkey-patch 用 reshape 替代 |
| `Unsupported: Logger not supported` | 模块级 `logging.Logger`（transformers 的 `warning_once`）被 trace；常因 checkpoint 带训练期状态（`gradient_checkpointing=True`）或未 `.eval()` 使 warning 分支变热路径 | 加载后 `gradient_checkpointing_disable()` + `.eval()` 治本；分支躲不开时把模块 `logger` 换成 no-op 普通对象（`_SilentLogger`，Dynamo 可内联追踪普通对象）——详见 [references/compiler_constraints.md](references/compiler_constraints.md) 第 6 章 |

---

## 参考资料

- [TorchAir 官方文档](https://torchair.readthedocs.io/)
- [torch_npu 图模式使用指南](https://gitee.com/ascend/pytorch)
- 具体项目适配案例：[references/gr00t_n1d7_example.md](references/gr00t_n1d7_example.md)
