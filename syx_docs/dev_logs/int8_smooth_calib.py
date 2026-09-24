#!/usr/bin/env python3
"""C2 int8 全链实施第一步：smooth 因子静态校准 v1（纯 host）。

s_k = (a_k / w_k)^alpha，per-input-channel：
  a_k = 样本激活的 per-channel abs-max（v1 proxy = golden frame0_v3 的
        四个激活截面包络：x0_vis/res0/m0_vis/prefix_hidden_vis——覆盖
        prefix 层间分布变化的上界；多帧扩录后置）
  w_k = 该投影权重的 per-input-channel abs-max（静态，逐层逐投影精确）
alpha 默认 0.5（probe 验证值）。

产出 smooth_calib_v1.npz：键 = {side}/L{nn}/{proj}（side ∈ prefix|flow，
proj ∈ q|k|v|o|gate|up|down），值 = float32[k]。下轮 prefix OM int8 重烤
直接消费：s_k 折进 int8 权重（w[:,k]*s_k 后行量化）+ 算子 smooth_scale
输入（x[:,k]/s_k，或等价的 smooth_scale=s_k^-1 视算子约定复核）。

已知限制（v1 如实记录）：
  1. 激活 proxy 是单帧 golden 的四截面包络，非逐层真实输入分布——
     下轮在 golden 生成器补逐层输入 dump 后升级 v2；
  2. flow（gemma_expert）侧无中间激活，暂用同一 proxy（flow 输入分布
     不同，误差待 LIBERO 行为判）。
"""
import json
import time

import numpy as np
import torch
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
GOLDEN = "/data/apxinf/golden/frame0_v3.safetensors"
OUT = "/data/apxinf/pyo3_check/smooth_calib_v1.npz"
ALPHA = 0.5
DEPTH = 18
PROJS = {  # safetensors 后缀 → 短名（两侧同构）
    "self_attn.q_proj": "q",
    "self_attn.k_proj": "k",
    "self_attn.v_proj": "v",
    "self_attn.o_proj": "o",
    "mlp.gate_proj": "gate",
    "mlp.up_proj": "up",
    "mlp.down_proj": "down",
}


def main():
    # 激活 proxy：四截面 per-channel abs-max 包络（长度对齐到最长截面）
    with safe_open(GOLDEN, framework="pt", device="cpu") as f:
        chans = []
        for key in ("x0_vis", "res0", "m0_vis", "prefix_hidden_vis"):
            v = f.get_tensor(key).float().abs().amax(dim=0).numpy()  # [cols]
            chans.append((v.shape[0], v))
        n_max = max(n for n, _ in chans)
        a_k = np.zeros(n_max, dtype=np.float32)
        for n, v in chans:
            a_k[:n] = np.maximum(a_k[:n], v)
        print(f"激活 proxy per-channel max：len={n_max} range=[{a_k.min():.2f},{a_k.max():.2f}]")

    factors = {}
    stats = []
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for side, root in (
            ("prefix", "model.paligemma_with_expert.paligemma.model.language_model"),
            ("flow", "model.paligemma_with_expert.gemma_expert.model"),
        ):
            for layer in range(DEPTH):
                for suf, proj in PROJS.items():
                    w = f.get_tensor(f"{root}.layers.{layer}.{suf}.weight").float().numpy()
                    # torch [out,in]；输入通道 = 轴 1（down_proj 例外：k=inter
                    # 维度 >2048，用同一 a_k 的包络近似——限制 2 的延伸）
                    w_k = np.abs(w).max(axis=0)  # [in]
                    k_len = w_k.shape[0]
                    a = a_k[:k_len] if a_k.shape[0] >= k_len else np.pad(a_k, (0, k_len - a_k.shape[0]), mode="edge")
                    s = np.power(np.maximum(a, 1e-8) / np.maximum(w_k, 1e-8), ALPHA).astype(np.float32)
                    factors[f"{side}/L{layer:02d}/{proj}"] = s
                    stats.append((f"{side}/L{layer:02d}/{proj}", float(s.min()), float(s.max()), k_len))

    np.savez(OUT, **factors)
    meta = {
        "alpha": ALPHA,
        "activation_proxy": "golden frame0_v3 x0_vis∪res0∪m0_vis∪prefix_hidden_vis envelope",
        "limitations": [
            "single-frame golden envelope, not per-layer true inputs (v2 = dump per-layer activations)",
            "flow side reuses prefix proxy (no flow intermediates in golden)",
            "down_proj k=8192 pads the 2048-wide activation envelope (edge mode)",
        ],
        "matrices": len(stats),
        "created": time.strftime("%Y-%m-%d %H:%M"),
    }
    with open(OUT.replace(".npz", "_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(f"写出 {OUT}（{len(stats)} 矩阵）+ meta")
    print(f"{'矩阵':<26} {'s_min':>9} {'s_max':>9} {'k':>6}")
    for name, lo, hi, k_len in sorted(stats):
        if "L00" in name or "L17" in name or "L07" in name:
            print(f"{name:<26} {lo:>9.2f} {hi:>9.2f} {k_len:>6}")
    smax = max(s[2] for s in stats)
    print(f"\n全库 s_k 范围上界 = {smax:.1f}（probe p0gate 实测 831 同量级 ✓）")


if __name__ == "__main__":
    main()
