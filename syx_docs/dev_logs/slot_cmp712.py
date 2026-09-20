"""slot_cmp712.py — t712dbg 图槽位 vs golden v3 层内真值判读

问题：kvk_l0 0.3% 干净、kvk_l1 24.7%（dbg 图）/45.2%（净图）——分岔在
引擎图层 0 块内（attention 段 vs MLP 段）。槽值可能被图内复用覆写，
按「值匹配哪一级」判读：m0_vis/h1_vis 是 torch f16 同 forward 真值，
f64 教科书从 m0_vis 续算 res/norm2/cur(=h1) 各级。
"""
import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
G = load_file("/data/apxinf/golden/frame0_v3.safetensors")
PRE = "model.paligemma_with_expert.paligemma.model.language_model.layers."
EPS = 1e-6
P = 712

x0 = G["x0_vis"].astype(np.float64)
m0 = G["m0_vis"].astype(np.float64)
h1 = G["h1_vis"].astype(np.float64)
kvk1 = G["kvk_l1"].astype(np.float64)

with safe_open(CKPT, framework="pt") as f:
    get = lambda li, n: f.get_tensor(f"{PRE}{li}.{n}").float().numpy()
    ow, w2 = get(0, "self_attn.o_proj.weight"), get(0, "post_attention_layernorm.weight")
    gw, uw, dw = get(0, "mlp.gate_proj.weight"), get(0, "mlp.up_proj.weight"), get(0, "mlp.down_proj.weight")
    kw1, w11 = get(1, "self_attn.k_proj.weight"), get(1, "input_layernorm.weight")


def gelu_tanh(x):
    return 0.5 * x * (1 + np.tanh(0.7978845608028654 * (x + 0.044715 * x ** 3)))


res = x0 + m0 @ ow.T
sc = (1.0 + w2)[None, :]
n2 = res / np.sqrt((res * res).mean(-1, keepdims=True) + EPS)
gate = n2 @ (gw * sc).T
up = n2 @ (uw * sc).T
gact = gelu_tanh(gate)
act = gact * up
down = act @ dw.T
h1_f = res + down

f16q = lambda a: np.asarray(a, dtype=np.float16).astype(np.float64)
print(f"[幅值] gate |max|={np.abs(gate).max():.1f} up |max|={np.abs(up).max():.1f}"
      f" act |max|={np.abs(act).max():.1f}（f16 上限 65504）")
n_big = (np.abs(act) > 30000).mean() * 100
print(f"[幅值] |act|>30000 占比 {n_big:.4f}%  |act|>65504（溢出）{(np.abs(act) > 65504).sum()} 个")

INV16 = np.float64(np.float16(10000.0 ** (-np.arange(128) * 2.0 / 256.0)))
ANG = np.arange(P)[:, None] * INV16[None, :]
COS, SIN = np.cos(ANG), np.sin(ANG)


def rope_k(k):
    kk = k.reshape(P, 1, 256)
    a, b = kk[..., :128], kk[..., 128:]
    out = np.empty_like(kk)
    out[..., :128] = a * COS[:, None] - b * SIN[:, None]
    out[..., 128:] = b * COS[:, None] + a * SIN[:, None]
    return out.reshape(k.shape)


def k_l1_of(h):
    n1 = h / np.sqrt((h * h).mean(-1, keepdims=True) + EPS)
    return rope_k(n1 @ (kw1 * (1.0 + w11)[None, :]).T)


rel = lambda a, b: np.abs(a - b).max() / max(np.abs(b).max(), 1e-9) * 100
print(f"[torch 自洽] h1_f(m0_vis 续算) vs h1_vis: {rel(h1_f, h1):.2f}%")
print(f"[链核对] k_l1(h1_vis) vs golden kvk_l1: {rel(k_l1_of(h1), kvk1):.2f}%")

cands = {
    "x0": (x0, 2048), "m0": (m0, 2048), "res": (res, 2048), "norm2": (n2, 2048),
    "gate": (gate, 16384), "up": (up, 16384), "gact": (gact, 16384), "act": (act, 16384),
    "down": (down, 2048), "h1": (h1_f, 2048), "h1_vis": (h1, 2048),
}
print("\n[槽位判读] 全级匹配（每槽最好的三级）：")
for i in range(36, 55):
    try:
        v = np.fromfile(f"/data/apxinf/dump712/ge_slot{i}.f16", dtype=np.float16).astype(np.float64)
    except OSError:
        break
    matches = []
    for n, (ref, w) in cands.items():
        if v.size != P * w:
            continue
        matches.append((rel(v.reshape(P, w), ref), n))
    if not matches:
        print(f"  slot{i}: size {v.size} 无匹配宽度")
        continue
    matches.sort()
    top = "  ".join(f"{n}:{d:.2f}%" for d, n in matches[:3])
    print(f"  slot{i} [{v.size // 712} 宽]: {top}")
