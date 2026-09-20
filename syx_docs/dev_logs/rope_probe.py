"""rope_probe.py — golden rotary 真值取证 + 配对约定枚举对拍"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401

torch_npu.npu.set_compile_mode(jit_compile=False)
sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402
from safetensors.numpy import load_file  # noqa: E402

pol = NpuTorchPi05Policy("/data/apxinf/weights/pi05_libero_finetuned")
pwe = pol.policy.model.paligemma_with_expert
lm = pwe.paligemma.model.language_model
pwe.paligemma.language_model.config._attn_implementation = "eager"

re_ = lm.rotary_emb
print("[rotary] class", type(re_).__name__)
if hasattr(re_, "inv_freq"):
    inv = re_.inv_freq.float().cpu().numpy()
    print("[rotary] inv_freq[:6]", inv[:6])
    for theta in (10000.0, 1000000.0, 500000.0, 8.0):
        ref = theta ** (-np.arange(0, 128) * 2.0 / 256.0)
        print("[rotary] theta", theta, "match_rel", float(np.abs(inv - ref).max() / ref.min()))
cfg = lm.config
for a in ("rope_theta", "rope_scaling", "head_dim", "query_pre_attn_scalar"):
    print("[cfg]", a, "=", getattr(cfg, a, "N/A"))

# 用 golden 的 kp0(pre-rope) 与 cache k_l0 枚举：theta × 配对约定
g = load_file("/data/apxinf/golden/frame0.safetensors")
x0 = torch.from_numpy(g["x0"]).to(torch.float16).unsqueeze(0).npu()
P = x0.shape[1]
cap = {}


def mk(name):
    def f(mod, args, kwargs, out):
        if name not in cap:
            cap[name] = {"out": out.detach().clone()}
    return f


h = lm.layers[0].self_attn.k_proj.register_forward_hook(mk("kp0"), with_kwargs=True)
with torch.no_grad():
    pos = torch.arange(P, device=x0.device).unsqueeze(0)
    pmask = pol.policy.model._prepare_attention_masks_4d(
        torch.ones(1, P, P, dtype=torch.bool, device=x0.device))
    pv = pwe.paligemma.language_model.forward(
        inputs_embeds=x0, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
h.remove()
pkv = pv.past_key_values
kcs = pkv.key_cache if hasattr(pkv, "key_cache") else [kv[0] for kv in pkv]
k_gold = kcs[0][0].float().reshape(P, -1).cpu().numpy()
kpre = cap["kp0"]["out"][0].float().reshape(P, -1).cpu().numpy().astype(np.float64)


def rope_rh(k, theta):
    half = 128
    ang = np.arange(P)[:, None] * (theta ** (-np.arange(half) * 2.0 / 256.0))[None, :]
    c, s = np.cos(ang), np.sin(ang)
    a, b = k[:, :half], k[:, half:]
    return np.concatenate([a * c - b * s, b * c + a * s], -1)


def rope_il(k, theta):
    # GPT-J 交错：偶/奇通道配对
    a, b = k[:, 0::2], k[:, 1::2]
    ang = np.arange(P)[:, None] * (theta ** (-np.arange(128) * 2.0 / 256.0))[None, :]
    c, s = np.cos(ang), np.sin(ang)
    out = np.empty_like(k)
    out[:, 0::2] = a * c - b * s
    out[:, 1::2] = b * c + a * s
    return out


for name, fn in (("rotate_half", rope_rh), ("interleave", rope_il)):
    for theta in (10000.0, 500000.0, 1000000.0):
        r = fn(kpre, theta)
        rel = np.abs(r - k_gold).max() / np.abs(k_gold).max()
        print(f"[enum] {name} theta={theta:.0f}: rel={rel * 100:.2f}%")


def rope_rh_f16inv(k, theta):
    # golden 数值路径复刻：inv_freq 先量化 f16（模型 .to(f16) 连 buffer），
    # HF rotary 再回 f32 计算角——高位置处 f16 步长 × pos ≈ O(0.1 rad) 相位差
    inv16 = np.float64(np.float16(theta ** (-np.arange(128) * 2.0 / 256.0)))
    ang = np.arange(P)[:, None] * inv16[None, :]
    c, s = np.cos(ang), np.sin(ang)
    a, b = k[:, :128], k[:, 128:]
    return np.concatenate([a * c - b * s, b * c + a * s], -1)


r = rope_rh_f16inv(kpre, 10000.0)
rel = np.abs(r - k_gold).max() / np.abs(k_gold).max()
print(f"[enum] rotate_half theta=10000 f16-inv_freq: rel={rel * 100:.2f}%  argmax={np.unravel_index(np.abs(r - k_gold).argmax(), k_gold.shape)}")
