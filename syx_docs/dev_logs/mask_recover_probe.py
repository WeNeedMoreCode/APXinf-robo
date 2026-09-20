"""mask_recover_probe.py — 从 m0_gold 数据反推真实 attention 可见性结构

源码链（sample_actions→embed_prefix 全 0→make_att_2d 全 True→全零加性）说
prefix 应为全开，但 m0_gold 偏全开世界 35.31%。本脚本按行剖析偏差分布
（768 图像行 vs 200 文本行）并枚举候选 mask，钉死第三世界的结构。
"""
import numpy as np
from safetensors.numpy import load_file

G = load_file("/data/apxinf/golden/frame0.safetensors")
P, NIMG = 968, 768
np.seterr(over="ignore", invalid="ignore")

q0i, k0i, v0i = (G[k].astype(np.float64) for k in ("q0i", "k0i", "v0i"))
m0_gold = G["m0"].astype(np.float64)

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


def rp8(x):
    kk = x.reshape(P, 8, 256)
    a, b = kk[..., :128], kk[..., 128:]
    out = np.empty_like(kk)
    out[..., :128] = a * COS[:, None] - b * SIN[:, None]
    out[..., 128:] = b * COS[:, None] + a * SIN[:, None]
    return out.reshape(x.shape)


q_r, k_r = rp8(q0i), rope_k(k0i)
# 每头 scores（softmax 前后），供各 mask 变体复用
SC = [q_r[:, h * 256:(h + 1) * 256] * (256 ** -0.5) @ k_r.T for h in range(8)]


def m0_with(mask):
    out = np.empty((P, 2048))
    for h in range(8):
        sc = SC[h] - SC[h].max(-1, keepdims=True)
        e = np.exp(sc) * mask
        p = e / e.sum(-1, keepdims=True)
        out[:, h * 256:(h + 1) * 256] = p @ v0i
    return out


full = np.ones((P, P))
cau = np.tril(np.ones((P, P)))
# 图像全双向 + 文本可看图像 + 文本间 causal（经典 PaliGemma AR）
pali = cau.copy()
pali[:NIMG, :NIMG] = 1.0
# 图像全双向 + 文本全开（=全开，对照）
# 图像分 3 视图各 256 双向、不互相可见 + 文本全开
views = np.zeros((P, P))
for v_ in range(3):
    s = v_ * 256
    views[s:s + 256, s:s + 256] = 1.0
views[:, NIMG:] = 1.0
views[NIMG:, NIMG:] = 1.0
# 文本不可见图像（图像全双向 + 文本只见文本全开）
notxt2img = np.zeros((P, P))
notxt2img[:NIMG, :NIMG] = 1.0
notxt2img[NIMG:, NIMG:] = 1.0

m_full = m0_with(full)
print("[候选] vs m0_gold（max-rel%）+ 分行块平均偏差（|diff|行max 的均值/全局max）")
gm = np.abs(m0_gold).max()
for name, m in (("full 全开", m_full), ("causal", m0_with(cau)),
                ("pali 图全双向+文本causal", m0_with(pali)),
                ("views 3视图隔离", m0_with(views)),
                ("文本不可见图像", m0_with(notxt2img))):
    d = np.abs(m - m0_gold)
    rowmax = d.max(-1)
    print(f"  {name}: {d.max() / gm * 100:.2f}%  行偏差均值 img={rowmax[:NIMG].mean() / gm * 100:.2f}% txt={rowmax[NIMG:].mean() / gm * 100:.2f}%")

# m0_gold vs m0_full 的逐行画像：找出坏行的分布
d = np.abs(m_full - m0_gold)
rowmax = d.max(-1) / gm * 100
print(f"\n[画像] m0_full vs gold 逐行 max 偏差%（按 64 行分桶平均）:")
for s in range(0, P, 64):
    seg = rowmax[s:s + 64]
    print(f"  行 {s:4d}-{min(s + 63, P - 1):4d}: {seg.mean():6.2f}%  max {seg.max():6.2f}%")

# ---- score 尖锐度 + f16 数值变体：图像行偏离是否为 argmax 型注意力对
# 数学等价实现的 f16 差异敏感（赢家翻转）----
print("\n[尖锐度] 每行 top1-top2 score 差（越大越接近 argmax）：")
for h in range(2):
    sc = SC[h]
    top2 = np.sort(sc, axis=-1)[:, -2:]
    gap = top2[:, 1] - top2[:, 0]
    print(f"  head{h}: img 行 gap 中位 {np.median(gap[:NIMG]):.2f}  txt 行 gap 中位 {np.median(gap[NIMG:]):.2f}"
          f"  |sc| 量级 img={np.abs(sc[:NIMG]).max():.1f} txt={np.abs(sc[NIMG:]).max():.1f}")

f16a = lambda a: np.asarray(a, dtype=np.float16).astype(np.float64)


def m0_num(sc_f, softmax_f16):
    out = np.empty((P, 2048))
    for h in range(8):
        sc = sc_f(SC[h])
        sc = sc - sc.max(-1, keepdims=True)
        if softmax_f16:
            e = np.exp(sc).astype(np.float16).astype(np.float64)
            p = (e / e.sum(-1, keepdims=True).astype(np.float16).astype(np.float64))
        else:
            e = np.exp(sc)
            p = e / e.sum(-1, keepdims=True)
        out[:, h * 256:(h + 1) * 256] = p @ v0i
    return out


print("\n[数值变体] vs m0_gold（full mask）:")
for name, m in (
    ("S1 f64 全程（基线）", m0_num(lambda s: s, False)),
    ("S2 score f16 舍入", m0_num(lambda s: f16a(s), False)),
    ("S4 softmax f16", m0_num(lambda s: s, True)),
    ("S5 score f16 + softmax f16", m0_num(lambda s: f16a(s), True)),
):
    dd = np.abs(m - m0_gold)
    rm = dd.max(-1)
    print(f"  {name}: {dd.max() / gm * 100:.2f}%  行均值 img={rm[:NIMG].mean() / gm * 100:.2f}% txt={rm[NIMG:].mean() / gm * 100:.2f}%")

# 补测：图像行看不到文本（文本行全开）——画像驱动的新候选
imgblind = np.zeros((P, P))
imgblind[:NIMG, :NIMG] = 1.0
imgblind[NIMG:, :] = 1.0
m_ib = m0_with(imgblind)
dd = np.abs(m_ib - m0_gold)
rm = dd.max(-1)
print(f"  [mask] 图像行不可见文本: {dd.max() / gm * 100:.2f}%  行均值 img={rm[:NIMG].mean() / gm * 100:.2f}% txt={rm[NIMG:].mean() / gm * 100:.2f}%")
