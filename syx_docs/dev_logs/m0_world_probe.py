"""m0_world_probe.py — golden 各键的 attention 语义世界裁决

n1_prec_probe 已证：chain(h1键) 偏 kvk_l1 18.7%（纯 f64，与 f16 无关），
而 m0_variants 从 ge_m0.f16 重构同链 = 0.14%。小扰动无放大 ⇒ 两处 m0 来源
分属不同 attention 语义（全开 mask vs causal）。本脚本构造四方矩阵：
  m0_full  = q0i/k0i/v0i 全开 attention（引擎语义）
  m0_causal = 同输入 causal attention（GemmaModel None-mask 默认语义）
  m0_gold  = frame0 m0 键    ge_m0 = /data/apxinf/ge_m0.f16（GE 图槽 dump）
并从各 m0 重构 h1 → chain → vs kvk_l1，钉死每个键属于哪个世界。
"""
import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
G = load_file("/data/apxinf/golden/frame0.safetensors")
PRE = "model.paligemma_with_expert.paligemma.model.language_model.layers."
EPS = 1e-6
np.seterr(over="ignore", invalid="ignore")
f16 = lambda a: np.asarray(a, dtype=np.float16).astype(np.float64)

P = 968
x0 = G["x0"].astype(np.float64)
q0i, k0i, v0i = (G[k].astype(np.float64) for k in ("q0i", "k0i", "v0i"))
m0_gold = G["m0"].astype(np.float64)
ge_m0 = np.fromfile("/data/apxinf/ge_m0.f16", dtype=np.float16).astype(np.float64).reshape(P, 2048)


def get(li, *names):
    with safe_open(CKPT, framework="pt") as f:
        return [f.get_tensor(f"{PRE}{li}.{n}").float().numpy() for n in names]


(kw0, w10, ow, w2, gw, uw, dw) = get(0, "self_attn.k_proj.weight", "input_layernorm.weight",
                                     "self_attn.o_proj.weight", "post_attention_layernorm.weight",
                                     "mlp.gate_proj.weight", "mlp.up_proj.weight", "mlp.down_proj.weight")
(kw1, w11) = get(1, "self_attn.k_proj.weight", "input_layernorm.weight")

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


def m0_from(q_r, k_r, scale=256 ** -0.5, causal=False):
    out = np.empty((P, 2048))
    for h in range(8):
        qh = q_r[:, h * 256:(h + 1) * 256] * scale
        sc = qh @ k_r.T
        sc = sc - sc.max(-1, keepdims=True)
        e = np.exp(sc)
        if causal:
            e *= np.tril(np.ones((P, P)))
        p = e / e.sum(-1, keepdims=True)
        out[:, h * 256:(h + 1) * 256] = p @ v0i
    return out


def rp8(x):  # 8 头 per-head rope
    kk = x.reshape(P, 8, 256)
    a, b = kk[..., :128], kk[..., 128:]
    out = np.empty_like(kk)
    out[..., :128] = a * COS[:, None] - b * SIN[:, None]
    out[..., 128:] = b * COS[:, None] + a * SIN[:, None]
    return out.reshape(x.shape)


m0_full = m0_from(rp8(q0i), rope_k(k0i))
m0_cau = m0_from(rp8(q0i), rope_k(k0i), causal=True)
print("[m0 四方] 两两 rel%（以分母=被比较方的 max）:")
for n, m in (("m0_gold", m0_gold), ("ge_m0", ge_m0), ("m0_full", m0_full), ("m0_causal", m0_cau)):
    print(f"  {n}: vs_gold={np.abs(m - m0_gold).max() / np.abs(m0_gold).max() * 100:.2f}%"
          f"  vs_ge={np.abs(m - ge_m0).max() / max(np.abs(ge_m0).max(), 1e-9) * 100:.2f}%"
          f"  vs_full={np.abs(m - m0_full).max() / max(np.abs(m0_full).max(), 1e-9) * 100:.2f}%"
          f"  vs_causal={np.abs(m - m0_cau).max() / max(np.abs(m0_cau).max(), 1e-9) * 100:.2f}%")


def gelu_tanh(x):
    return 0.5 * x * (1 + np.tanh(0.7978845608028654 * (x + 0.044715 * x ** 3)))


def h1_of(m0):
    res = x0 + m0 @ ow.T
    sc = (1.0 + w2)[None, :]
    n2 = res / np.sqrt((res * res).mean(-1, keepdims=True) + EPS)
    return res + (gelu_tanh(n2 @ (gw * sc).T) * (n2 @ (uw * sc).T)) @ dw.T


gold1 = G["kvk_l1"].astype(np.float64)
kwf1 = f16(kw1 * (1.0 + w11)[None, :])


def k_rel(h1):
    n1 = h1 / np.sqrt((h1 * h1).mean(-1, keepdims=True) + EPS)
    return np.abs(rope_k(n1 @ kwf1.T) - gold1).max() / np.abs(gold1).max() * 100


print("\n[chain] 各世界 h1 → L1 k vs kvk_l1:")
for n, m in (("h1键", None), ("m0_gold", m0_gold), ("ge_m0", ge_m0), ("m0_full", m0_full), ("m0_causal", m0_cau)):
    h1 = G["h1"].astype(np.float64) if n == "h1键" else h1_of(m)
    print(f"  {n}: k rel={k_rel(h1):.2f}%  (h1 vs h1键 {np.abs(h1 - G['h1'].astype(np.float64)).max() / np.abs(G['h1']).max() * 100:.2f}%)")
print("\n[判读] ≈0% 的那行 = kvk_l1 的真实语义世界；h1键/m0键属于哪行一目了然。")
