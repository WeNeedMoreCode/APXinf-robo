# GR00T N1.7 Torchair 适配案例

本文件记录 Isaac GR00T N1.7（Qwen3VL 骨干）适配过程中遇到的具体问题。
作为 torchair 适配模式的实际应用参考。

## 1. Conv3D 选择性 JIT

**问题**：`nn.Conv3d`（Qwen3-VL 的 `patch_embed`）在 `jit_compile=False` 下报错
`Op Conv3D does not has any binary`。

**尝试过的方案**：
- 全局 `jit_compile=True`：能跑，但 ~36s/step，不可接受
- 全局 `True` 做 warmup 再切回 `False`：warmup 成功，但切回 `False` 后 Conv3D 仍然报错。
  **JIT 缓存不能跨 compile mode 复用**。
- 选择性 JIT wrapper（只给 `patch_embed` 切 `True`）：**有效**。
  整网保持 `False`，只在 Conv3D 算子执行时临时切 `True`。结果 ~1.55s/step。

**最终代码**（`gr00t_policy.py` 的 NPU 初始化中）：
```python
try:
    patch_embed = model.backbone.model.model.visual.patch_embed
    _orig_forward = patch_embed.forward
    def _selective_jit_conv3d(x):
        import torch_npu
        torch_npu.npu.set_compile_mode(jit_compile=True)
        try:
            out = _orig_forward(x)
        finally:
            torch_npu.npu.set_compile_mode(jit_compile=False)
        return out
    patch_embed.forward = _selective_jit_conv3d
except Exception:
    pass
```

注意：当视觉编码器也被 torchair 编译（compile_level>=2）时，不需要这个 workaround。

## 2. Dynamo `setattr` trace 失败

**问题**：用 torchair 编译 `model.backbone`（transformers Qwen3-VL）时，
Dynamo 报错 `torch._dynamo.exc.Unsupported: Failed to trace builtin operator setattr`。

**根因**：`transformers.models.qwen3_vl.modeling_qwen3_vl` 第 1060 行：
`pixel_values = pixel_values.type(self.visual.dtype)` 触发了 `torch_npu.utils.tensor_methods._npu_type`，
其内部的 `_NPUTensortypeCache.tensortype_list_dict_init()` 使用了类级别的 `setattr` 模式，Dynamo 无法 trace。

**解决方案**：在模型加载时用 `extra_kwargs["torch_dtype"] = torch.float16` 预设 dtype，
避免运行时 `.type()` 调用。同时把 backbone forward 拆分为
`_preprocess_vl_input`（eager）+ `_compiled_visual_forward`（compiled）+ `_language_model_forward`（compiled），
只编译不含 `.type()` 的纯 tensor 运算部分。

## 3. 模型路径备忘

- `model.backbone.model.model.visual.patch_embed`：实际的 `nn.Conv3d` 模块位置
- `Qwen3VLForConditionalGeneration.visual` 是 read-only property；
  可写的实际引用在内部 `Qwen3VLModel` 上

## 4. 视频后端

- `torchcodec 0.12.0` 链接了 `libnvrtc.so.13`（CUDA 13），NPU 环境不兼容
- 改用 `decord` 后端。编译需要 FFmpeg 开发库：
  `apt-get install libavcodec-dev libavformat-dev libswscale-dev libavfilter-dev libavutil-dev`
- decord 编译完成后，把 `build/libdecord.so` 复制到 `site-packages/decord/` 目录下

## 5. scatter_add 优化

**问题**：`_language_model_forward` 中 deepstack visual embedding 注入使用 gather+add+scatter 三个算子。

**优化**：替换为 `scatter_add` 一个算子，节省 ~11ms（211ms → 200ms）。

```python
# Before (3 kernels):
idx = visual_indices.unsqueeze(0).unsqueeze(-1).expand(-1, -1, hidden_states.shape[-1])
current = torch.gather(hidden_states, 1, idx)
updated = current + visual_embed.unsqueeze(0)
hidden_states = hidden_states.scatter(1, idx, updated)

# After (1 kernel):
idx = visual_indices.unsqueeze(0).unsqueeze(-1).expand(-1, -1, hidden_states.shape[-1])
hidden_states = hidden_states.scatter_add(1, idx, visual_embed.unsqueeze(0))
```

## 6. 精度数据（N1.7-3B on Droid，2 trajectories）

| 配置 | MSE | MAE | 每步耗时 |
|---|---|---|---|
| GPU (A10) | 0.008555 | 0.055992 | ~259ms |
| NPU（无编译，eager） | 0.009335 | 0.057575 | ~1.55s |
| NPU（全编译 + 3D 修复） | 0.009353 | ~0.058 | ~440ms → 200ms |

## 7. 修改的文件清单

| 文件 | 作用 |
|---|---|
| `gr00t/policy/gr00t_policy.py` | NPU 初始化：dtype 拆分、选择性 JIT、torchair 编译分级控制 |
| `gr00t/model/modules/qwen3_backbone.py` | forward 拆分、3D tensor 修复、monkey-patch attention、静态值缓存 |
| `gr00t/model/npu_utils.py` | NPU RoPE、FRACTAL_NZ、torchair backend 辅助函数 |
| `scripts/deployment/standalone_inference_script.py` | `--device` 参数、`video_backend="decord"` |
| `gr00t/eval/open_loop_eval.py` | `--device` 参数 |
| `gr00t/eval/run_gr00t_server.py` | NPU 初始化 hook |
| `pyproject.toml` | `torch_npu==2.7.1.post4`、`decord`、`triton>=3.5.0`、`pytz` |

## 8. 精度排查记录（2025-05-30）

详细排查过程见 `syx_records/260530_cuda-vs-npu精度排查结论.md`。

关键结论：
- 通过 syx_save/syx_load 对齐输入后，确认 pixel_values 和 text_embeds 完全一致
- block 0 输出完全一致，差异从 block 1 开始逐层累积（1e-6 → 6e-4）
- block 17-23 误差增长率偏高（~500x），因为该区间值域暴涨（std 1.19→46.24）
- CPU 上两平台 MSE 仅差 0.025%，证明代码适配完全正确
- 差异 100% 来自 NPU vs CUDA 的 fp16 硬件舍入

## 9. FFN Split4 权重时序踩坑（2026-06-08）

将 LLM FFN 的大 MatMul（2048→6144）拆成 4 个小 MatMul（2048→1536）。
在 CPU 上切分权重后 `model.to('npu')`，原始权重和切分权重分别做 NPU 内部格式转换，
导致数值差异：

| 对比项 | CPU 切分后 to('npu') | to('npu') 后切分 |
|---|---|---|
| 权重 max diff | 0.46-0.82 | 0 |
| Linear 输出 max diff | 5-30 | 0 |
| 最终 MSE | 0.0187（+147%） | 0.0076（不变） |

修复：把切分操作延迟到模型已在 NPU 上之后执行。
详细记录见 `syx_records/260608_FFN_Split4优化与NPU权重格式踩坑.md`。

## 10. 视觉编码器内部插桩（2026-06-25）

### 背景

DUO 卡（310P3）preprocess 90ms，RC 卡（310P1，DDR 共享内存）preprocess 189ms，gap 99ms。
eager 外层 `forward()` 已经能测出 preprocess 整体时间，但看不到内部哪个子阶段最慢。
怀疑是视觉编码器（Conv3D + 16 层 transformer + merger），需要拆分插桩确认。

### 第一次尝试：直接在编译函数内 `time.time()`（失败）

把 `if _prof: t0 = time.time()` 加到 `_compiled_visual_forward` 和 `_preprocess_vl_input` 内部，
希望靠 `_prof` flag 在 trace 时跳过计时分支。

**报错**（preprocess 第一次调用时）：
```
torch._dynamo.exc.Unsupported: Attempted to call function marked as skipped
  Explanation: Dynamo does not know how to trace the builtin `time.time.`
  Hint: If it is a Python builtin, please file an issue on GitHub...
  Hint: If it is a third-party C/C++ Python extension, please either wrap it
        into a PyTorch-understood custom operator or use `torch.compiler.allow_in_graph`.

  from user code:
     File ".../qwen3_backbone.py", line 469, in _preprocess_vl_input
       t0 = time.time()
```

**根因**：`_preprocess_vl_input` 是 `torch.compile(..., fullgraph=True)` 编译的，
Dynamo 必须 trace 整个调用链。`_prof` 是 module 属性，运行时才确定，
trace 阶段 Dynamo 仍要进入 `if _prof:` 的 True 分支看 body，遇到 `time.time()` 直接拒绝。

`torch.npu.synchronize()` 倒是可以入图，但 `time.time()` 不行。

### 第二次尝试：eager profiled 路径（成功）

放弃在编译函数内插桩，改为：
- 保留原 `_preprocess_vl_input`（编译，生产路径）
- 新增 `_preprocess_vl_input_profiled`（eager，带计时），调用**单独编译**的 `_compiled_visual_forward`
- `forward()` 按 `_prof` flag 分发

第一次跑通，输出：
```
[PROF] preprocess:  text=0.3  visual=171.7  mask=0.0  rope=2.0  scatter=6.8
```

**结论**：视觉编码器占 preprocess 的 **94.5%**（171ms / 181ms），其他四段加起来 9ms。
RC vs DUO 的 91ms gap 中 ~86ms 都在视觉编码器。

### 第三次尝试：再拆视觉编码器内部

继续把 `_compiled_visual_forward` 拆成 3 个独立编译子方法：
- `_compiled_visual_conv3d`：patch embed + 位置编码 + dtype cast
- `_compiled_visual_blocks`：16 层 transformer + deepstack mergers
- `_compiled_visual_merger`：最终 merger

加 eager 编排器 `_compiled_visual_forward_profiled`，输出：
```
[PROF] visual:  conv3d=X.X  blocks=X.X  merger=X.X
```

`_preprocess_vl_input_profiled` 改为调用 `_compiled_visual_forward_profiled` 而不是 `_compiled_visual_forward`。

### 改动文件清单

| 文件 | 改动 |
|---|---|
| `gr00t/model/modules/qwen3_backbone.py` | 新增 3 个独立编译子方法 + `_compiled_visual_forward_profiled` + `_preprocess_vl_input_profiled`；`forward()` 按 `_prof` 分发 |
| `gr00t/policy/gr00t_policy.py` | 编译列表加入 3 个新子方法（生产路径不变） |

### 关键代码（`qwen3_backbone.py`）

```python
# eager 外层分发
def forward(self, vl_input):
    _prof = getattr(self, '_enable_profiling', False)
    _sync = getattr(self, '_profile_sync', False) and _prof

    if _prof:
        if _sync: torch.npu.synchronize()
        t0 = time.time()
        lm_kwargs = self._preprocess_vl_input_profiled(vl_input)
        if _sync: torch.npu.synchronize()
        t_preprocess = time.time() - t0
    else:
        lm_kwargs = self._preprocess_vl_input(vl_input)  # 生产路径，编译

# eager 编排器，里面可以放心 time.time()
def _preprocess_vl_input_profiled(self, vl_input):
    _sync = getattr(self, '_profile_sync', False)
    # ... text/visual/mask/rope/scatter 五段，每段前后 sync + time.time
    # 视觉段调用 _compiled_visual_forward_profiled 拿到内部 conv3d/blocks/merger 拆分
```

### 编译注册（`gr00t_policy.py`）

```python
if compile and _COMPILE_VISUAL_ENCODER:
    compile_for_npu(model.backbone, "_preprocess_vl_input")          # 生产路径
    # profile 路径子方法，各自独立编译
    compile_for_npu(model.backbone, "_compiled_visual_conv3d")
    compile_for_npu(model.backbone, "_compiled_visual_blocks")
    compile_for_npu(model.backbone, "_compiled_visual_merger")
```

注意：`_preprocess_vl_input_profiled` 和 `_compiled_visual_forward_profiled` 是 eager 编排器，
**不能**注册编译。

### 经验教训

1. **`if _prof:` 保护救不了 `time.time()`**：Dynamo 仍会 trace True 分支 body
2. **eager 编排器只调"独立编译的子方法"**：否则子方法跑 eager，时间不能代表生产
3. **每个子方法单独 `compile_for_npu` 注册**：原 `_compiled_visual_forward` 在生产路径下被 `_preprocess_vl_input` inline，不需要单独编译
4. **`_sync` 必须 True**：否则测的是 kernel launch 时间（9ms）而不是真实执行时间（189ms），数据极具误导性
5. **稳态数据要跳过前 2 步**：编译会溢出到下一步，前 2 步数据不可信

### 完整推理脚本开关

`scripts/deployment/standalone_inference_script.py` 提供了相关命令行开关：

| 参数 | 作用 |
|---|---|
| `--instrument` | 开启逐阶段计时，自动设置 `_enable_profiling=True` 和 `_profile_sync=True` |
| `--skip-timing-steps N` | 跳过前 N 步不计入统计（默认 2，排除编译 spillover） |

环境变量：

| 变量 | 作用 |
|---|---|
| `_GR00T_PER_TRAJ=1` | 每条轨迹独立子进程（避免 Dynamo 跨轨迹累积） |

## 11. PFA 替换 visual attention（2026-06-25）

### 背景

第 10 节拆分插桩后发现：RC 上 preprocess 168ms 中 **blocks 段占 155ms（92%）**，
16 层 visual transformer 是绝对瓶颈。其中每层 attention 用显式
`matmul + softmax(fp32) + matmul`，3 个大 kernel + 8MB 中间张量。

决定替换为昇腾融合 FA 算子，加速 + 省内存。

### 算子选择：FIA → PFA

第一次选了 `npu_fused_infer_attention_score` (FIA)，因为文档说"适配推理场景"。
但跑测试报错。重新读 help 输出，发现：

```
支持的芯片型号:
- Atlas A2 训练系列产品/Atlas 800I A2 推理产品
- Atlas A3 训练系列产品
```

**310P 不在列表里**，FIA 在 310P 上根本调不起来。

改用 `npu_prompt_flash_attention` (PFA)，help 输出明确写：
```
支持的芯片型号:
- Atlas A2 训练系列产品/Atlas 800I A2 推理产品
- Atlas A3 训练系列产品
- Atlas 推理系列加速卡产品    ← 310P 在这里
```

**教训**：FA 系列算子多，按芯片选，不能想当然。决策树见 README "FlashAttention 融合算子" 章节。

### 验证脚本

`test_pfa.py`，跑 4 个 case 对比 PFA vs 显式 attention：

```python
import torch, torch_npu, math, time

def reference_attention(q, k, v, scale):
    aw = torch.matmul(q, k.transpose(-2, -1)) * scale
    aw = torch.nn.functional.softmax(aw, dim=-1, dtype=torch.float32).to(q.dtype)
    return torch.matmul(aw, v)

def pfa_attention(q, k, v, num_heads, scale):
    return torch_npu.npu_prompt_flash_attention(
        q, k, v, num_heads=num_heads, input_layout="BNSD", scale_value=scale,
    )

# 4 cases: 实际 shape / 多 head / 长 seq / 单 batch
# 每个 case 测：① PFA 可调 ② 精度 diff ③ 100 次平均 latency
```

### 实测数据（DUO 310P3）

| Case (BNSD) | PFA | matmul+softmax | speedup | max diff | rel diff |
|---|---|---|---|---|---|
| **[4, 16, 256, 128]** ⭐实际 shape | 0.45ms | 1.07ms | **2.41x** | 0.001 | 0.055% |
| [4, 32, 256, 128] 多 head | 0.67ms | 2.35ms | 3.54x | 0.001 | 0.055% |
| [4, 16, 512, 128] 长 seq | 1.18ms | 4.36ms | 3.71x | 0.0007 | 0.060% |
| [1, 16, 256, 128] 单 batch | 0.42ms | 0.48ms | 1.15x | 0.0005 | 0.055% |

**结论**：实际 shape 加速 2.41x，精度 rel diff 仅 0.055%（fp16 误差量级是 1%），
完全在零损失范围。N/S 越大收益越明显。

### 替换 patch

`gr00t/model/modules/qwen3_backbone.py` 的 `_patch_visual_attention`：

```python
# 顶部加
import torch_npu

# _forward 内
# 关键变化 1: permute 后加 .contiguous()（PFA 不接受非连续 tensor）
q = q.reshape(n_img, tpi, nh, hd).permute(0, 2, 1, 3).contiguous()
k = k.reshape(n_img, tpi, nh, hd).permute(0, 2, 1, 3).contiguous()
v = v.reshape(n_img, tpi, nh, hd).permute(0, 2, 1, 3).contiguous()

# 关键变化 2: 显式 attention → PFA 单算子调用
sc_value = float(sc) if hasattr(sc, 'item') else sc
attn_output = torch_npu.npu_prompt_flash_attention(
    q, k, v,
    num_heads=nh,
    input_layout="BNSD",
    scale_value=sc_value,  # 注意是 scale_value，不是 scale
)
```

### 模型级实测（RC 310P1，稳态）

| 段 | 替换前 | 替换后 | 变化 |
|---|---|---|---|
| conv3d | 1.3ms | 1.2ms | -0.1 |
| **blocks** | **168.8ms** | **155.3ms** | **-13.5** ⭐ |
| merger | 1.7ms | 1.7ms | 0 |
| visual 合计 | 172ms | 158.7ms | -13.3 |
| preprocess 合计 | 182ms | 168.6ms | -13.4 |
| **inference 总** | **346.9ms** | **333ms** | **-13.9** |

| 精度 | 替换前 | 替换后 | 变化 |
|---|---|---|---|
| MSE | ~0.0093 | **0.008248** | **-11%** ⭐ |
| MAE | ~0.058 | **0.055631** | -4% |

### 意外发现：精度反而变好

按理说融合算子和显式 fp32 中间 softmax 应该精度差不多。但实测 MSE 降了 11%。

可能原因：
1. PFA 内部用**在线 softmax**（Online Softmax）算法，数值更稳定
2. 消除了 `softmax(dtype=fp32).to(fp16)` 这步 cast 的累积误差
3. fp16 matmul + fp32 softmax 的组合并非"最优"，只是我们以为最优

**教训**：替换融合算子后，**精度可能变好也可能变差**，必须实测对比。
不要假设手写实现就是基线。

### 经验总结

1. **FIA ≠ PFA**：FIA 是 A2/A3 推理卡的，310P 用不了；310P 用 PFA
2. **参数名差异**：PFA 是 `scale_value`，FIA 是 `scale`；PFA 返回单 tensor，FIA 返回元组
3. **contiguous 必须显式加**：permute/transpose 后立刻 `.contiguous()`，否则报错或结果错
4. **测试先于 patch**：先用最小测试脚本（5 个 case）确认 speedup 和精度，再改 patch
5. **310P 限制要查 help**：sparse_mode 仅 0、不支持 actual_seq_lengths、仅 fp16 等
6. **精度可能反而变好**：融合算子的内部数值算法可能比手写 matmul+softmax 更稳定

## 12. LM PFA 替换失败回撤（2026-06-27）

### 背景

第 11 节 visual PFA 替换成功后，自然想把它扩展到 LM。LM 也用 `eager_attention_forward`（显式 matmul+softmax+matmul），microbenchmark 在 S=1024 上 PFA 测出 **11.48x 加速**，看起来是稳赚的优化。

### 改动

monkey-patch `transformers.models.qwen3_vl.modeling_qwen3_vl.eager_attention_forward`，替换为 PFA 版本。比 visual 复杂：

- **因果掩码**：LM 有 attention_mask + causal mask，PFA 需要传 `atten_mask`
- **GQA**：LM 是 `num_kv_heads < num_heads`，PFA 不支持，要先 `repeat_kv` 展开
- **S 16 对齐**：310P1 上 PFA + atten_mask 要求 S 是 16 的倍数，实际 S=277 → pad 到 288，mask 末尾 pad 列置 True

```python
def _pfa_eager_forward(module, query, key, value, attention_mask, scaling, **kwargs):
    key_states = repeat_kv(key, module.num_key_value_groups).contiguous()
    value_states = repeat_kv(value, module.num_key_value_groups).contiguous()
    q = query.contiguous()
    # Pad S to 16-aligned
    pad = (16 - S % 16) % 16
    if pad > 0:
        q = F.pad(q, (0, 0, 0, pad))
        key_states = F.pad(key_states, (0, 0, 0, pad))
        value_states = F.pad(value_states, (0, 0, 0, pad))
    # ...PFA 调用...
```

### 验证流程

1. patch 应用日志确认（"Patched Qwen3VL LM eager_attention_forward"）
2. 真 PFA 跑通，时间对比：

| 配置 | LM 时间 |
|---|---|
| 原始（显式 attention） | 95ms |
| PFA 替换后 | 90ms |
| 净收益 | **5ms（5%）** |

### 失败原因分析

**根因：microbenchmark 的加速比不能外推到实际序列长度**

| S | PFA vs 显式 attention 加速比 |
|---|---|
| S=1024 | 11.48x |
| **S=277（实际 LM）** | **1.3x** |

PFA 有固定开销（kernel launch / mask 创建 / GQA repeat_kv / S padding），短序列下占比大，长序列下被摊薄。

**第二个根因：LM 是 FFN-bound，不是 attention-bound**

把 LM 时间拆开看：
- 总时间 95ms
- attention 部分约 15ms（看其他诊断）
- FFN + embedding + norm + residual 约 80ms

attention 只占 ~16%，再怎么换 attention 算子也省不了多少。

### 决策与回撤

5ms 收益（5%）相对精度风险（PFA padding/mask/GQA 转换都可能引入数值偏差）不划算。决定**回撤**：
- 删除 `_patch_lm_attention_pfa` 函数定义
- 删除 `gr00t_policy.py` 里的调用点

### 教训

1. **microbenchmark 加速比不能直接外推**：必须在实际序列长度下重新测
2. **优化前先估算目标算子占比**：attention 占总时间 <20% 时换 PFA 不值（profiler 看 op_summary.csv 按 op type 聚合）
3. **不要看到 visual PFA 成功就盲目扩展到 LM**：两者场景不同——visual 是 encoder 全量 attention（无 mask、MHA、S=256），LM 是 causal + GQA + S=277，工作量和风险都翻倍

完整时间线 + 优化历程见 `syx_records/260627_visual_pfa与lm_pfa尝试.md`。
