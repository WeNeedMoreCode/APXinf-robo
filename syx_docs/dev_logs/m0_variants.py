"""m0_variants.py — 枚举 attention 错误变体，找与引擎 m0 吻合的那个

引擎 m0（GE 图层 0 attention 合并输出）35.3% 偏 golden。此脚本用 golden 的
q/k/v（hook 真值）复算各变体 m0，比对 /data/apxinf/ge_m0.f16：
吻合（rel→0）= 引擎实际执行了该变体 = 根因。
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


def mk(name):
    def f(mod, args, kwargs, out):
        if name not in cap:
            cap[name] = {"out": out.detach().clone()}
    return f


H = [
    lm.layers[0].self_attn.q_proj.register_forward_hook(mk("q0"), with_kwargs=True),
    lm.layers[0].self_attn.k_proj.register_forward_hook(mk("k0"), with_kwargs=True),
    lm.layers[0].self_attn.v_proj.register_forward_hook(mk("v0"), with_kwargs=True),
]
with torch.no_grad():
    pos = torch.arange(P, device=x0.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(torch.ones(1, P, P, dtype=torch.bool, device=x0.device))
    pwe.paligemma.language_model.forward(
        inputs_embeds=x0, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
for h in H:
    h.remove()

f = lambda n: cap[n]["out"][0].float().cpu().numpy().astype(np.float64)
q_pre, k_pre, v_pre = f("q0"), f("k0"), f("v0")
m0_gold = g["m0"].astype(np.float64)
ge_m0 = np.fromfile("/data/apxinf/ge_m0.f16", dtype=np.float16).astype(np.float64).reshape(P, 2048)
print(f"[load] ge_m0 {ge_m0.shape} |max|={np.abs(ge_m0).max():.3f}; golden |max|={np.abs(m0_gold).max():.3f}")
print(f"[base ] ge vs golden m0: rel={np.abs(ge_m0 - m0_gold).max() / np.abs(m0_gold).max() * 100:.2f}%")

INV16 = np.float64(np.float16(10000.0 ** (-np.arange(128) * 2.0 / 256.0)))
ANG = np.arange(P)[:, None] * INV16[None, :]
C, S = np.cos(ANG), np.sin(ANG)


def rope_perhead(x, heads):
    kk = x.reshape(P, heads, 256)
    a, b = kk[..., :128], kk[..., 128:]
    out = np.empty_like(kk)
    out[..., :128] = a * C[:, None] - b * S[:, None]
    out[..., 128:] = b * C[:, None] + a * S[:, None]
    return out.reshape(x.shape)


def rope_whole(x):
    a, b = x[:, :1024], x[:, 1024:]
    c, s = np.cos(np.arange(P)[:, None] * np.float64(np.float16(10000.0 ** (-np.arange(1024) * 2.0 / 2048.0)))[None, :]), \
           np.sin(np.arange(P)[:, None] * np.float64(np.float16(10000.0 ** (-np.arange(1024) * 2.0 / 2048.0)))[None, :])
    return np.concatenate([a * c - b * s, b * c + a * s], -1)


def m0_from(q_r, k_r, scale, f16_softmax=False, heads=8, v=None):
    v = v_pre if v is None else v
    out = np.empty((P, 2048))
    for h in range(heads):
        qh = q_r[:, h * 256:(h + 1) * 256] * scale
        sc = qh @ k_r.T
        if f16_softmax:
            sc = sc.astype(np.float16).astype(np.float64)
            sc = sc - sc.max(-1, keepdims=True)
            e = np.exp(sc).astype(np.float16).astype(np.float64)
            p = (e / e.sum(-1, keepdims=True).astype(np.float16).astype(np.float64))
        else:
            sc = sc - sc.max(-1, keepdims=True)
            e = np.exp(sc)
            p = e / e.sum(-1, keepdims=True)
        out[:, h * 256:(h + 1) * 256] = p @ v
    return out


def report(tag, m):
    d_ge = np.abs(m - ge_m0).max() / max(np.abs(ge_m0).max(), 1e-9)
    d_gd = np.abs(m - m0_gold).max() / max(np.abs(m0_gold).max(), 1e-9)
    print(f"[var] {tag}: vs_ge={d_ge * 100:.2f}%  vs_golden={d_gd * 100:.2f}%")


k_r = rope_perhead(k_pre, 1)
report("correct (perhead rope, /16)", m0_from(rope_perhead(q_pre, 8), k_r, 256 ** -0.5))

# ---- infer 侧 q/k/v（golden_gen hook）vs 重放侧 hook ——裁决 m0 35% 分岔 ----
q0i, k0i, v0i = (g[k].astype(np.float64) for k in ("q0i", "k0i", "v0i"))
for tag, a, b in (("q", q_pre, q0i), ("k", k_pre, k0i), ("v", v_pre, v0i)):
    d = np.abs(a - b).max() / max(np.abs(b).max(), 1e-9)
    print(f"[qkv] replay {tag} vs infer {tag}: rel={d * 100:.2f}%")
mi = m0_from(rope_perhead(q0i, 8), rope_perhead(k0i, 1), 256 ** -0.5, v=v0i)
report("infer-qkv correct-recipe", mi)
report("q no-rope", m0_from(q_pre, k_r, 256 ** -0.5))
report("q whole-rope(2048)", m0_from(rope_whole(q_pre), k_r, 256 ** -0.5))
report("no scale", m0_from(rope_perhead(q_pre, 8), k_r, 1.0))
report("scale 1/sqrt(2048)", m0_from(rope_perhead(q_pre, 8), k_r, 2048 ** -0.5))
report("f16 softmax", m0_from(rope_perhead(q_pre, 8), k_r, 256 ** -0.5, f16_softmax=True))
report("q no-rope + no scale", m0_from(q_pre, k_r, 1.0))

# ---- h1 变体：GE 图 m0 之后（o_proj/残差/MLP）哪级坏 ----
ge_h1 = np.fromfile("/data/apxinf/ge_h1.f16", dtype=np.float16).astype(np.float64).reshape(P, 2048)
L0 = lm.layers[0]
w2v = L0.post_attention_layernorm.weight.detach().float().cpu().numpy()
gwv = L0.mlp.gate_proj.weight.detach().float().cpu().numpy()
uwv = L0.mlp.up_proj.weight.detach().float().cpu().numpy()
dwv = L0.mlp.down_proj.weight.detach().float().cpu().numpy()
owv = L0.self_attn.o_proj.weight.detach().float().cpu().numpy()
x0f = g["x0"].astype(np.float64)
m0_c = m0_from(rope_perhead(q0i, 8), rope_perhead(k0i, 1), 256 ** -0.5, v=v0i)
res1 = x0f + m0_c @ owv.T


def gelu_tanh(x):
    return 0.5 * x * (1 + np.tanh(0.7978845608028654 * (x + 0.044715 * x ** 3)))


def mlp(n2, fold=1.0, swap=False):
    g_, u_ = (uwv, gwv) if swap else (gwv, uwv)
    sc = (1.0 + w2v * fold)[None, :]
    return (gelu_tanh(n2 @ (g_ * sc).T) * (n2 @ (u_ * sc).T)) @ dwv.T


def norm2(x):
    return x / np.sqrt((x * x).mean(-1, keepdims=True) + 1e-6)


def h1rep(tag, h):
    d = np.abs(h - ge_h1).max() / max(np.abs(ge_h1).max(), 1e-9)
    print(f"[h1var] {tag}: vs_ge={d * 100:.2f}%")


n2 = norm2(res1)
# 关键：ge 的 res 输出（x+attn 段）是否 = x0 + o_proj(ge_m0)——验 GE 图
# m0→res 段；是 ⇒ GE attention+o_proj+残差全对，锅收窄到 MLP 段
res1_ge = x0f + ge_m0 @ owv.T
d = np.abs(res1_ge - ge_h1).max() / max(np.abs(ge_h1).max(), 1e-9)
print(f"[h1var] x0+o_proj(ge_m0) vs ge_res输出: rel={d * 100:.2f}% (≈0 ⇒ GE 图到 res 全对)")
print(f"[h1var] |max|: ge_res={np.abs(ge_h1).max():.1f} res1_ge={np.abs(res1_ge).max():.1f} res1_py={np.abs(res1).max():.1f}")
h1rep("x+attn+mlp (correct)", res1 + mlp(n2))
h1rep("x+attn (no mlp)", res1)
h1rep("gate/up swapped", res1 + mlp(n2, swap=True))
h1rep("fold x2", res1 + mlp(n2, fold=2.0))
h1rep("no fold (w2 nowhere)", res1 + mlp(n2, fold=0.0))

# ---- 终极裁决：GE 自己的 m0 → 教科书全层 → k_l1，vs golden kvk_l1 ----
# ≈0% ⇒ GE 图 MLP 段唯一坏点；≈41% ⇒ 悖论加深（m0 槽与消费值不一致）
L1 = lm.layers[1]
w1v1 = L1.input_layernorm.weight.detach().float().cpu().numpy()
kw1 = L1.self_attn.k_proj.weight.detach().float().cpu().numpy()
res1_g = x0f + ge_m0 @ owv.T
h1_g = res1_g + mlp(norm2(res1_g))
nrm = lambda x: x / np.sqrt((x * x).mean(-1, keepdims=True) + 1e-6)
k_pre1 = nrm(h1_g) @ (kw1 * (1.0 + w1v1)[None, :]).T
k_l1_g = rope_perhead(k_pre1, 1)
k_l1_gold = g["kvk_l1"].astype(np.float64)
d = np.abs(k_l1_g - k_l1_gold).max() / np.abs(k_l1_gold).max()
print(f"[final] GE-m0→textbook-MLP→k_l1 vs golden kvk_l1: rel={d * 100:.2f}%  (GE 实测 41.1%)")

