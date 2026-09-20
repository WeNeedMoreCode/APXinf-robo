"""attn_scale_probe.py — golden GemmaAttention scaling / GQA 结构取证"""
import os
import sys

import torch
import torch_npu  # noqa: F401

torch_npu.npu.set_compile_mode(jit_compile=False)
sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402

pol = NpuTorchPi05Policy("/data/apxinf/weights/pi05_libero_finetuned")
lm = pol.policy.model.paligemma_with_expert.paligemma.model.language_model
sa = lm.layers[0].self_attn
print("[attn] scaling =", float(sa.scaling), " (= query_pre_attn_scalar^-0.5)")
print("[attn] hidden^-0.5 =", 2048 ** -0.5, " head_dim^-0.5 =", 256 ** -0.5)
print("[attn] num_heads =", sa.config.num_attention_heads,
      " kv =", sa.config.num_key_value_heads, " head_dim =", sa.head_dim)
exp = pol.policy.model.paligemma_with_expert.gemma_expert.model.layers[0].self_attn
print("[expert attn] scaling =", float(exp.scaling),
      " width^-0.5 =", 1024 ** -0.5, " head_dim^-0.5 =", 256 ** -0.5)
vis = pol.policy.model.paligemma_with_expert.paligemma.model.vision_tower.vision_model
vs = vis.encoder.layers[0].self_attn
print("[vision attn] scaling =", getattr(vs, "scaling", "N/A"),
      " d_model^-0.5 =", 1152 ** -0.5)
