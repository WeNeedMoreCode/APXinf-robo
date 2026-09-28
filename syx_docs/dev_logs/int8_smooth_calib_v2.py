#!/usr/bin/env python3
"""smooth 校准 v2：per-matrix 真激活（golden_gen_v2calib.py 的逐层 dump）
替换 v1 的四截面包络。

  s_k = (a_k / w_k)^0.5（α=0.5 沿用 v1 定案）
  a_k = 该矩阵精确输入激活的 per-channel abs-max（torch 域）
        ——q/k/v ← nrm1_l{i}；o ← m_l{i}；gate/up ← nrm2_l{i}；down ← act_l{i}
  w_k = checkpoint 权重 per-channel abs-max（静态精确）
键格式同 v1（prefix/L{nn}/{proj}），直供 convert_smooth_engine.py。
单帧（frame0）——多帧扩录留 v3。
"""
import numpy as np
import torch
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
ACT = "/data/apxinf/golden/frame0_calib_v2.safetensors"
OUT = "/data/apxinf/pyo3_check/smooth_calib_v2.npz"
ROOT = "model.paligemma_with_expert.paligemma.model.language_model"
ALPHA = 0.5
DEPTH = 18
# proj → (激活键 tag, safetensors 后缀)
SRC = {
    "q": ("nrm1", "self_attn.q_proj"),
    "k": ("nrm1", "self_attn.k_proj"),
    "v": ("nrm1", "self_attn.v_proj"),
    "o": ("m", "self_attn.o_proj"),
    "gate": ("nrm2", "mlp.gate_proj"),
    "up": ("nrm2", "mlp.up_proj"),
    "down": ("act", "mlp.down_proj"),
}


def main():
    with safe_open(ACT, framework="pt", device="cpu") as af:
        acts = {k: af.get_tensor(k).float().abs().amax(dim=0).numpy() for k in
                [f"{tag}_l{i}" for i in range(DEPTH) for tag in ("nrm1", "m", "nrm2", "act")]}
    factors = {}
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for i in range(DEPTH):
            for proj, (tag, suf) in SRC.items():
                a_k = acts[f"{tag}_l{i}"]
                w = f.get_tensor(f"{ROOT}.layers.{i}.{suf}.weight").float().numpy()  # [out,in]
                w_k = np.abs(w).max(axis=0)  # [in]
                k_len = w_k.shape[0]
                assert len(a_k) == k_len, (i, proj, len(a_k), k_len)  # down: act_l 的 k=16384 ✓
                s = np.power(np.maximum(a_k, 1e-8) / np.maximum(w_k, 1e-8), ALPHA).astype(np.float32)
                factors[f"prefix/L{i:02}/{proj}"] = s
    np.savez(OUT, **factors)
    smax = max(float(v.max()) for v in factors.values())
    smin = min(float(v.min()) for v in factors.values())
    print(f"写出 {OUT}：{len(factors)} 矩阵，s ∈ [{smin:.4g},{smax:.2f}]（f16 行安全性 > 6e-5）")


if __name__ == "__main__":
    main()
