# ModelZoo π0.5 NPU 适配分析（lerobot_diff.patch，317 行）

> 外部知识归档。来源：`vla/pi05_lerobot/infer_with_torchair/patches/lerobot_diff.patch`（LeRobot v0.4.3 基线）。**阶段二原生移植的算子映射直接受益于此。**

## 逐项分析

### 1. RoPE → `npu_rotary_mul`

monkey-patch `transformers.models.gemma.modeling_gemma.apply_rotary_pos_emb`：

```python
merged = torch.cat([q, k], dim=1)          # [B, n_q+n_k, S, D]
merged_rot = torch_npu.npu_rotary_mul(merged, cos, sin)
q_embed, k_embed = merged_rot.split([n_q, n_k], dim=1)
```

- q、k 拼接后**一次算子调用**完成两者的 RoPE，再切回——减少 kernel 启动
- 对应 CANN 算子：`aclnnRotaryMul`。⇒ 阶段二 `qkv_rope` 融合 kernel 的 NPU 候选

### 2. 权重 NZ 格式（FRACTAL_NZ = 29）

`format_cast_to_NZ(model)`：加载时遍历所有 `nn.Linear`，`torch_npu.npu_format_cast(weight, 29)`。

- 昇腾 Cube 阵列的矩阵乘原生吃 NZ 分形布局，ND→NZ 转换放加载期一次完成
- ⇒ 阶段二：权重 `to_device` 时做布局转换（或 aclnnMatmul 直接配 NZ）

### 3. FP16 全面替换 BF16

- 模型 `.to(torch.float16)`（原 bfloat16）
- 噪声采样 dtype fp16、`time_tensor` fp16、图像 fp16
- 删掉 `suffix_out.to(float32)`（动作头输出保持 fp16）
- 图像预处理：只走 NHWC 路径（删掉 channels-first 分支），`[-1,1]` 归一化在 fp16 下做

### 4. TorchAir 图编译（三个子图）

```python
config = CompilerConfig()
config.experimental_config.frozen_parameter = True
config.experimental_config.tiling_schedule_optimize = True  # tiling 全下沉
npu_backend = tng.get_npu_backend(compiler_config=config)
# fullgraph=True, dynamic=False
paligemma_with_expert.forward / embed_image / denoise_step → torch.compile(backend=npu_backend)
```

- 替换原版 `torch.compile(mode=...)`（CUDA 语义）
- **denoise_step 整体编译**：flow matching 循环体（10 步迭代）是延迟大头
- `frozen_parameter` + `dynamic=False`：权重固化 + 静态 shape，换更激进编译
- ⇒ 阶段二：ApxInf CUDA Graph 的 NPU 对应物可参考"整图下发"思路（host 录制算子序列一次、重放）

### 5. 多视角图像合并 batch

原版逐图 `embed_image(img)`；改后 `torch.cat(images, dim=0)` 一次调用（batch 维合并），embedding 再 reshape 拆分。视角数 = batch，减少图编译实例和 kernel 启动次数。

### 6. vision tower 用 eager attention

`vlm_config_hf.vision_config._attn_implementation = "eager"`——siglip 的 ViT 在 310P 上不用 FA/sdpa 而用 eager matmul。

- ⇒ 推测（未严格证明）：310P3 上 FA 类算子对 ViT 的 shape（非因果、seq~256+）覆盖或性能不佳。阶段二 `vision_sdpa` 实现前需实测 aclnnFusionAttention 在该 shape 的可用性，eager 是兜底

### 7. 其它

- `torch_npu.npu.set_compile_mode(jit_compile=False)`（禁 PJIT 走 GE 路径）
- 删 `select_action`/`predict_action_chunk` 里的 `self.eval()`（热路径省调用）
- `utils.is_torch_device_available` 加 `npu` 分支
- eval 脚本：`transfer_to_npu` + `torch.npu.set_device("npu:0")` 必须在 `import gymnasium` **之前**（仿真与 NPU 冲突）
- `resize_with_pad` 支持 fp16 分支

## 对阶段二的映射表（更新相异点清单用）

| ApxInf CUDA kernel | NPU 候选（来自本 patch 的证据） |
|---|---|
| `qkv_rope`（融合） | `npu_rotary_mul`（q+k cat 一次调用） |
| GEMM 权重布局 | 加载期 `npu_format_cast(FRACTAL_NZ)` |
| 图捕获/重放 | TorchAir fullgraph 整图编译的思路；ACL 侧无直接 API |
| `vision_sdpa` | 实测 aclnnFusionAttention，eager 兜底 |
| 精度 | FP16（310P3 无 BF16） |
