"""attn_l0_h1.py — 层 0 attention 块复刻对拍（约定 vs GE 图接线二分）

复刻引擎约定（已逐项对 golden 验证）：f16-inv_freq rope、q 权重预乘 1/√hd、
无 bias、头主序 q[k, h*256+d]。比两级：
  1. attn_out（o_proj 输出，残差前）vs golden o_proj hook
  2. h1 = x0 + attn_out vs golden layers[1].input_layernorm 输入
≈0% ⇒ 引擎约定对、锅在 GE 图接线（headsplit/attn_manual_gqa/headmerge/TileD）
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
from safetensors.numpy import load_file  # noqa: E402

pol = NpuTorchPi05Policy("/data/apxinf/weights/pi05_libero_finetuned")
pwe = pol.policy.model.paligemma_with_expert
lm = pwe.paligemma.model.language_model
pwe.paligemma.language_model.config._attn_implementation = "eager"
model = pol.policy.model

g = load_file("/data/apxinf/golden/frame0.safetensors")
x0 = torch.from_numpy(g["x0"]).to(torch.float16).unsqueeze(0).npu()
P = x0.shape[1]

cap = {}


def mk(name, mode="out"):
    def f(mod, args, kwargs, out):
        if name in cap:
            return
        o = out[0] if isinstance(out, tuple) else out
        cap[name] = o.detach().clone() if mode == "out" else args[0].detach().clone()
    return f


H = [
    lm.layers[0].self_attn.q_proj.register_forward_hook(mk("q0"), with_kwargs=True),
    lm.layers[0].self_attn.k_proj.register_forward_hook(mk("k0"), with_kwargs=True),
    lm.layers[0].self_attn.v_proj.register_forward_hook(mk("v0"), with_kwargs=True),
    lm.layers[0].self_attn.o_proj.register_forward_hook(mk("o0"), with_kwargs=True),
    lm.layers[1].input_layernorm.register_forward_hook(mk("h1", "in"), with_kwargs=True),
]
with torch.no_grad():
    pos = torch.arange(P, device=x0.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(torch.ones(1, P, P, dtype=torch.bool, device=x0.device))
    pwe.paligemma.language_model.forward(
        inputs_embeds=x0, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
for h in H:
    h.remove()

f = lambda n: cap[n][0].float().cpu().numpy().astype(np.float64)
q_pre, k_pre, v_pre, o_gold, h1_gold = f("q0"), f("k0"), f("v0"), f("o0"), f("h1")


def rope_rh(k):
    # 逐头 rope：[..., heads, 256] 每头内 split 128/128（q 8 头 / k 单头）
    shp = k.shape
    kk = k.reshape(shp[0], -1, 256)
    inv16 = np.float64(np.float16(10000.0 ** (-np.arange(128) * 2.0 / 256.0)))
    ang = np.arange(P)[:, None] * inv16[None, :]
    c, s = np.cos(ang), np.sin(ang)
    a, b = kk[..., :128], kk[..., 128:]
    # rotate-half：前半 a·cos − b·sin；后半 b·cos + a·sin（sin 折叠符号）
    out = np.empty_like(kk)
    out[..., :128] = a * c[:, None] - b * s[:, None]
    out[..., 128:] = b * c[:, None] + a * s[:, None]
    return out.reshape(shp)


q_r, k_r = rope_rh(q_pre), rope_rh(k_pre)
SCALE = 256.0 ** -0.5
out = np.empty((P, 2048))
for h in range(8):
    qh = q_r[:, h * 256:(h + 1) * 256] * SCALE
    sc = qh @ k_r.T                    # [968,968]
    sc = sc - sc.max(-1, keepdims=True)
    e = np.exp(sc)
    out[:, h * 256:(h + 1) * 256] = (e / e.sum(-1, keepdims=True)) @ v_pre
ow = lm.layers[0].self_attn.o_proj.weight.detach().float().cpu().numpy()
attn_rep = out @ ow.T                  # o_proj 无 bias
d1 = np.abs(attn_rep - o_gold).max() / np.abs(o_gold).max()
print(f"[attn_out] engine-convention vs golden o_proj: rel={d1 * 100:.2f}% |max|_rep={np.abs(attn_rep).max():.3f} |max|_g={np.abs(o_gold).max():.3f}")

h1_rep = g["x0"].astype(np.float64) + attn_rep
d2 = np.abs(h1_rep - h1_gold).max() / np.abs(h1_gold).max()
print(f"[h1_attn ] x0+attn vs golden 层输出: rel={d2 * 100:.2f}%（应偏——golden 层输出含 MLP）")

# ---- MLP 块复刻（h1 的“层输出” = x + attn + mlp）----
# layers[1].input_layernorm 的输入 = 层 0 完整输出：x + attn_out + mlp(norm2(x+attn))
L0 = lm.layers[0]
w2 = L0.post_attention_layernorm.weight.detach().float().cpu().numpy()  # [2048] 原值
gw = L0.mlp.gate_proj.weight.detach().float().cpu().numpy()  # [16384,2048]
uw = L0.mlp.up_proj.weight.detach().float().cpu().numpy()
dw = L0.mlp.down_proj.weight.detach().float().cpu().numpy()
res1 = h1_rep  # x + attn（attn 已 0.03% 对上）
n2 = res1 / np.sqrt((res1 * res1).mean(-1, keepdims=True) + 1e-6)  # (1+w2) 折叠进权重
gg = n2 @ (gw * (1.0 + w2)[None, :]).T
uu = n2 @ (uw * (1.0 + w2)[None, :]).T
gelu = lambda x: 0.5 * x * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (x + 0.044715 * x ** 3)))
mlp_out = (gelu(gg) * uu) @ dw.T
h2_rep = res1 + mlp_out
d3 = np.abs(h2_rep - h1_gold).max() / np.abs(h1_gold).max()
print(f"[h2_full ] x+attn+mlp vs golden 层输出: rel={d3 * 100:.2f}% |max|_rep={np.abs(h2_rep).max():.3f} |max|_g={np.abs(h1_gold).max():.3f}")
print("[argmax attn_out]", np.unravel_index(np.abs(attn_rep - o_gold).argmax(), o_gold.shape))
