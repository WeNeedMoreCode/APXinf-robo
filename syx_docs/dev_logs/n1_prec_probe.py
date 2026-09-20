"""n1_prec_probe.py — AddRmsNorm f16 内部精度变体模拟（零 NPU 裁决实验）

签名（GE 图实测）：x0 输入→kvk_l0 0.4%；h1 输入(|max|≈1562)→kvk_l1 18.7%。
RMS norm 后各级幅度与输入基本无关（行 rms 归一）⇒ 幅度依赖的分岔只能产自
norm 内部的 f16 行为。本脚本在 CPU 上枚举 norm 的 f16 实现变体（平方饱和/
溢出/累加精度），经 f64 mm+rope 传播到 k，与 golden kvk 对拍：能同时复现
两侧签名的变体 = aclnnAddRmsNorm 在 310P 上的实际数值机制。
权重直读 checkpoint safetensors（engine 折叠约定：kw*(1+w) 后 f16 烤入，
g1=ones），无 torch 模型加载。运行：apxinf_npu 容器 CPU（numpy+torch）。
"""
import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
G = load_file("/data/apxinf/golden/frame0.safetensors")
PRE = "model.paligemma_with_expert.paligemma.model.language_model.layers."


def get_w(li, *names):
    with safe_open(CKPT, framework="pt") as f:
        out = [f.get_tensor(f"{PRE}{li}.{n}").float().numpy() for n in names]
    return out


def get(li):
    return get_w(li,
                 "self_attn.k_proj.weight", "input_layernorm.weight",
                 "self_attn.o_proj.weight", "post_attention_layernorm.weight",
                 "mlp.gate_proj.weight", "mlp.up_proj.weight", "mlp.down_proj.weight")


def gelu_tanh(x):
    return 0.5 * x * (1 + np.tanh(0.7978845608028654 * (x + 0.044715 * x ** 3)))


def layer0_out(x, m0, w):
    """f64 全块：x + o_proj(m0) + mlp——从 golden m0 重构 h1（m0_variants 同款）"""
    _, _, ow, w2, gw, uw, dw = w
    res = x + m0 @ ow.T
    sc = (1.0 + w2)[None, :]
    n2 = res / np.sqrt((res * res).mean(-1, keepdims=True) + EPS)
    return res + (gelu_tanh(n2 @ (gw * sc).T) * (n2 @ (uw * sc).T)) @ dw.T


f16 = lambda a: np.asarray(a, dtype=np.float16).astype(np.float64)
EPS, F16MAX = 1e-6, 65504.0
np.seterr(over="ignore", invalid="ignore")


def norm_A(x16):  # 全精度 rms（f16 输入）——对照组
    return x16 / np.sqrt((x16 * x16).mean(-1, keepdims=True) + EPS)


def norm_B(x16, clip=True):  # 平方在 f16（饱和 clip / 溢出 inf），均值 f64
    sq = x16 * x16
    sq = np.minimum(sq, F16MAX) if clip else f16(sq)
    return x16 / np.sqrt(sq.mean(-1, keepdims=True) + EPS)


def norm_C(x16):  # 平方 f64、部分和 f16 累加（沿 2048 顺序）
    sq = (x16 * x16).astype(np.float16)
    acc = np.add.accumulate(sq, axis=-1, dtype=np.float16)
    return x16 / np.sqrt(acc[:, -1:].astype(np.float64) / x16.shape[1] + EPS)


def norm_C2(x16):  # 平方 f16 饱和 + 部分和 f16 累加
    sq = np.minimum(x16 * x16, F16MAX).astype(np.float16)
    acc = np.add.accumulate(sq, axis=-1, dtype=np.float16)
    return x16 / np.sqrt(acc[:, -1:].astype(np.float64) / x16.shape[1] + EPS)


P = G["x0"].shape[0]
INV16 = np.float64(np.float16(10000.0 ** (-np.arange(128) * 2.0 / 256.0)))
ANG = np.arange(P)[:, None] * INV16[None, :]
COS, SIN = np.cos(ANG), np.sin(ANG)


def rope_k(k):  # k 单 KV 头 256 维，rotate_half 128/128
    kk = k.reshape(P, 1, 256)
    a, b = kk[..., :128], kk[..., 128:]
    out = np.empty_like(kk)
    out[..., :128] = a * COS[:, None] - b * SIN[:, None]
    out[..., 128:] = b * COS[:, None] + a * SIN[:, None]
    return out.reshape(k.shape)


def k_of(n1, kw, w1):
    kwf = f16(kw * (1.0 + w1)[None, :])  # engine 折叠+f16 烤入
    return rope_k(n1 @ kwf.T)


def rel(a, gold):
    return np.abs(a - gold).max() / max(np.abs(gold).max(), 1e-9) * 100


for tag_in, key_in, li, key_out in (("x0", "x0", 0, "kvk_l0"), ("h1", "h1", 1, "kvk_l1")):
    x = G[key_in].astype(np.float64)
    x16 = f16(x)
    gold = G[key_out].astype(np.float64)
    kw, w1 = get_w(li, "self_attn.k_proj.weight", "input_layernorm.weight")
    # 网格检查：golden 值是否本来就在 f16 网格上（f16 模型中间量应在）
    qerr = np.abs(x16 - x).max() / np.abs(x).max() * 100
    print(f"\n[{tag_in}] |max|={np.abs(x16).max():.1f}  f16 网格偏差 {qerr:.4f}%  golden k |max|={np.abs(gold).max():.3f}")
    for name, n1 in (
        ("A0 纯 f64（原值直入）", x / np.sqrt((x * x).mean(-1, keepdims=True) + EPS)),
        ("A  f16 输入 + f64 链", norm_A(x16)),
        ("D  输出 f16 量化", f16(norm_A(x16))),
    ):
        print(f"  {name}: k rel={rel(k_of(n1, kw, w1), gold):.2f}%")

# ---- golden 内部自洽性裁决：h1 键 vs「x0+o_proj(m0)+mlp」重构 ----
w0 = get(0)
w1_ = get(1)
h1 = G["h1"].astype(np.float64)
x0 = G["x0"].astype(np.float64)
m0 = G["m0"].astype(np.float64)
h1_rec = layer0_out(x0, m0, w0)
print(f"\n[自洽] h1(键) vs x0+o_proj(m0)+mlp 重构: rel={rel(h1_rec, h1):.2f}%")
print(f"[自洽] |h1键| max={np.abs(h1).max():.1f}  |重构| max={np.abs(h1_rec).max():.1f}")
kw1, w11 = w1_[0], w1_[1]
gold1 = G["kvk_l1"].astype(np.float64)
n_rec = h1_rec / np.sqrt((h1_rec * h1_rec).mean(-1, keepdims=True) + EPS)
print(f"[自洽] chain(重构 h1) vs kvk_l1: rel={rel(k_of(n_rec, kw1, w11), gold1):.2f}%  （m0_variants 实测 0.14%）")
print("\n[判读] A0≈A ⇒ 与 f16 无关，golden h1↔kvk_l1 本就不自洽；重构≈h1键 则键全对、矛盾另寻。")
