#!/usr/bin/env python3
"""校准 v1 等效性验证：npz 离线 s_k（四截面包络）vs probe 在线 s_k
（res0 单截面）的 W8A8 host 模拟执行差对照。

host 模拟与 GEB_OPTEST=qmd 同数学：per-token 激活量化 + 权重
per-output-row int8 + 双 scale。矩阵 = paligemma L00 mlp.gate，
激活 = golden res0（probe 同款）。期望：包络因子执行差与单截面
（probe 实测 0.678%）同量级（包络更保守，方向 = 不溢出）。
"""
import numpy as np
import torch
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
GOLDEN = "/data/apxinf/golden/frame0_v3.safetensors"
NPZ = "/data/apxinf/pyo3_check/smooth_calib_v1.npz"
KEY = "model.paligemma_with_expert.paligemma.model.language_model.layers.0.mlp.gate_proj.weight"


def sim_w8a8(x: np.ndarray, w: np.ndarray, s_k: np.ndarray) -> np.ndarray:
    """x[m,k] f32, w[n,k] f32, s_k[k] → y[m,n]（W8A8 host 模拟）"""
    xs = x / s_k  # 激活平滑
    ws = w * s_k  # 权重吸收
    # per-token 激活 int8
    sx = np.maximum(np.abs(xs).max(axis=1, keepdims=True), 1e-12) / 127.0
    xq = np.clip(np.round(xs / sx), -127, 127)
    # 权重 per-output-row int8
    sw = np.maximum(np.abs(ws).max(axis=1, keepdims=True), 1e-12) / 127.0
    wq = np.clip(np.round(ws / sw), -127, 127)
    yq = (xq.astype(np.int32) @ wq.astype(np.int32).T).astype(np.float64)
    return yq * sx * sw.T  # per-token × per-out-channel scale 网格


def main():
    with safe_open(GOLDEN, framework="pt", device="cpu") as f:
        x = f.get_tensor("res0").float().numpy()
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        w = f.get_tensor(KEY).float().numpy()  # [out=16384, in=2048]（gate+up 拼接前单 gate）
    y_ref = x.astype(np.float64) @ w.T.astype(np.float64)
    denom = np.abs(y_ref).max()

    # 朴素（无 smooth）
    y0 = sim_w8a8(x, w, np.ones(x.shape[1], dtype=np.float32))
    # 在线单截面 s_k（probe 同式：res0 的 per-channel max）
    a_k = np.abs(x).max(axis=0)
    w_k = np.abs(w).max(axis=0)
    s_inline = np.power(np.maximum(a_k, 1e-8) / np.maximum(w_k, 1e-8), 0.5).astype(np.float32)
    y1 = sim_w8a8(x, w, s_inline)
    # npz 离线包络 s_k
    s_npz = np.load(NPZ)["prefix/L00/gate"][: x.shape[1]]
    y2 = sim_w8a8(x, w, s_npz)

    for tag, y in (("朴素无 smooth", y0), ("在线单截面 s_k", y1), ("npz 四截面包络 s_k", y2)):
        rel = np.abs(y - y_ref).max() / denom * 100
        print(f"{tag:<22} 执行差 rel={rel:.3f}%")
    print(f"|y|max={denom:.1f}，矩阵 {w.shape}，激活 {x.shape}")
    # alpha 扫描（同在线单截面公式）：下轮 alpha 选择的直接依据
    for alpha in (0.3, 0.4, 0.5, 0.6, 0.7):
        s_a = np.power(np.maximum(a_k, 1e-8) / np.maximum(w_k, 1e-8), alpha).astype(np.float32)
        ya = sim_w8a8(x, w, s_a)
        rel = np.abs(ya - y_ref).max() / denom * 100
        print(f"alpha={alpha:.1f}（在线截面）   执行差 rel={rel:.3f}%")


if __name__ == "__main__":
    main()
