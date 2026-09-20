"""l0_bisect.py — prefix 层 0 逐级对拍：引擎约定复刻 vs golden torch

裁决 kvk_l0 12.6% 分岔在哪一级：
  A. rmsnorm   : 引擎约定 rms(x0, eps=1e-6)·1（(1+w1) 已折叠进投影）
                 vs golden ln0 输出 normed·(1+w1)
  B. k_proj    : normed_e @ (W_k·diag(1+w1)).T + b  vs golden k_proj hook 输出
  C. rope      : rotate-half（split 128/128，theta=10000，pos 0..967）
                 vs golden cache k_l0（post-rope）
全 f32 复算（+f16 cast 对拍），torch golden 走 hook 抓真值。

npu 容器跑法：
  ASCEND_RT_VISIBLE_DEVICES=7 python3 /data/apxinf/l0_bisect.py
"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401

torch_npu.npu.set_compile_mode(jit_compile=False)

sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
GOLDEN = "/data/apxinf/golden/frame0.safetensors"

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
lm = pwe.paligemma.model.language_model  # 模块树真路径（带 .model.）
pwe.paligemma.language_model.config._attn_implementation = "eager"

cap = {}


def mk(name):
    def f(mod, args, kwargs, out):
        if name in cap:
            return
        # GemmaRMSNorm.forward 返回 (out, gate) 元组
        o = out[0] if isinstance(out, tuple) else out
        cap[name] = {"in": args[0].detach().clone(), "out": o.detach().clone()}
    return f


h1 = lm.layers[0].input_layernorm.register_forward_hook(mk("ln0"), with_kwargs=True)
h2 = lm.layers[0].self_attn.k_proj.register_forward_hook(mk("kp0"), with_kwargs=True)
h3 = lm.layers[0].self_attn.q_proj.register_forward_hook(mk("qp0"), with_kwargs=True)

# x0 从 golden（与引擎同源输入），重放 prefix pass 触发层 0 hooks + cache
from safetensors.numpy import load_file  # noqa: E402

g = load_file(GOLDEN)
x0 = torch.from_numpy(g["x0"]).to(torch.float16).unsqueeze(0).npu()
P = x0.shape[1]
with torch.no_grad():
    pos = torch.arange(P, device=x0.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(torch.ones(1, P, P, dtype=torch.bool, device=x0.device))
    pv_out = pwe.paligemma.language_model.forward(
        inputs_embeds=x0, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None,
    )
for h in (h1, h2, h3):
    h.remove()
pkv = pv_out.past_key_values
kcs = pkv.key_cache if hasattr(pkv, "key_cache") else [kv[0] for kv in pkv]
k_gold = kcs[0][0].float().reshape(P, -1).cpu().numpy()  # [968,256] post-rope

w1 = lm.layers[0].input_layernorm.weight.detach().float().cpu().numpy()  # [2048]（原值）
kw = lm.layers[0].self_attn.k_proj.weight.detach().float().cpu().numpy()  # [256,2048]
kb_mod = lm.layers[0].self_attn.k_proj.bias
kb = kb_mod.detach().float().cpu().numpy() if kb_mod is not None else np.zeros(kw.shape[0])

x = g["x0"].reshape(P, -1).astype(np.float64)
EPS = 1e-6

# A: rms（引擎约定：gamma 折叠=1；golden 乘 (1+w1)）——两侧都算 normed 后再比
normed_e = x / np.sqrt((x * x).mean(-1, keepdims=True) + EPS)          # 引擎消费的 normed
ln_out = cap["ln0"]["out"][0].float().reshape(P, -1).cpu().numpy()
normed_g = ln_out / (1.0 + w1)[None, :]                                # golden 的纯 normed
d = np.abs(normed_e - normed_g).max() / max(np.abs(normed_g).max(), 1e-9)
print(f"[A rms   ] engine-convention normed vs golden: rel={d*100:.2f}% |max|_e={np.abs(normed_e).max():.3f} |max|_g={np.abs(normed_g).max():.3f}")

# B: k_proj（fold：W' = W·diag(1+w1)；等价于 golden 的 normed·(1+w1)@W）
kp_gold = cap["kp0"]["out"][0].float().reshape(P, -1).cpu().numpy()    # pre-rope
kpre_e = normed_e @ (kw * (1.0 + w1)[None, :]).T + kb[None, :]
d = np.abs(kpre_e - kp_gold).max() / max(np.abs(kp_gold).max(), 1e-9)
print(f"[B k_proj] folded-W k(pre-rope) vs golden: rel={d*100:.2f}% |max|_e={np.abs(kpre_e).max():.3f} |max|_g={np.abs(kp_gold).max():.3f}")

# C: rope（rotate-half：前 128 与后 128 配对；theta=10000；pos 0..967）
half = 128
inv = 10000.0 ** (-np.arange(0, half) * 2.0 / 256.0)  # [128]
ang = np.arange(P)[:, None] * inv[None, :]            # [968,128]
cos, sin = np.cos(ang), np.sin(ang)
k_f16 = kp_gold.astype(np.float64)                    # 从 golden pre-rope 出发（隔离 rope 单级）
a, b = k_f16[:, :half], k_f16[:, half:]
kpost_e = np.concatenate([a * cos - b * sin, b * cos + a * sin], axis=-1)
d = np.abs(kpost_e - k_gold).max() / max(np.abs(k_gold).max(), 1e-9)
print(f"[C rope  ] rotate-half(theta=1e4) vs golden cache k: rel={d*100:.2f}% |max|_e={np.abs(kpost_e).max():.3f} |max|_g={np.abs(k_gold).max():.3f}")

# 全链（A+B+C 引擎约定端到端 vs golden cache k）
kpost_full = np.concatenate(
    [kpre_e[:, :half] * cos - kpre_e[:, half:] * sin,
     kpre_e[:, half:] * cos + kpre_e[:, :half] * sin], axis=-1)
d = np.abs(kpost_full - k_gold).max() / max(np.abs(k_gold).max(), 1e-9)
print(f"[ALL     ] engine-convention e2e l0 k vs golden: rel={d*100:.2f}%")
print("[C] argmax row/col:", np.unravel_index(np.abs(kpost_e - k_gold).argmax(), k_gold.shape))
