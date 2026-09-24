#!/usr/bin/env python3
"""int8 权重烘焙 v1：w·s_k → per-output-row int8 + scale（prefix 侧 18 层
×7 投影），产出 int8_weights_v1.npz。

用途：① 下轮 prefix OM int8 重烤的 Rust 实现对拍金标准；② 体积/误差
预览。数学与 GEB_OPTEST=qmd 一致（QuantMatmulDequant 契约：int8 ND
[n,k] + weight_scale f32 [n]）。
"""
import numpy as np
import torch
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
SMOOTH = "/data/apxinf/pyo3_check/smooth_calib_v1.npz"
OUT = "/data/apxinf/pyo3_check/int8_weights_v1.npz"
ROOT = "model.paligemma_with_expert.paligemma.model.language_model"
PROJS = {
    "self_attn.q_proj": "q",
    "self_attn.k_proj": "k",
    "self_attn.v_proj": "v",
    "self_attn.o_proj": "o",
    "mlp.gate_proj": "gate",
    "mlp.up_proj": "up",
    "mlp.down_proj": "down",
}


def main():
    smooth = np.load(SMOOTH)
    out = {}
    bytes_q = bytes_f16 = 0
    errs = []
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for layer in range(18):
            for suf, proj in PROJS.items():
                w = f.get_tensor(f"{ROOT}.layers.{layer}.{suf}.weight").float().numpy()  # [out,in]
                s_k = smooth[f"prefix/L{layer:02d}/{proj}"][: w.shape[1]]
                ws = w * s_k  # smooth 吸收（数学恒等 y=Σ(x/s_k)(w·s_k)）
                sw = np.maximum(np.abs(ws).max(axis=1, keepdims=True), 1e-12) / 127.0
                wq = np.clip(np.round(ws / sw), -127, 127).astype(np.int8)
                key = f"prefix/L{layer:02d}/{proj}"
                out[f"{key}/wq"] = wq
                out[f"{key}/scale"] = sw.astype(np.float32).ravel()
                bytes_q += wq.nbytes
                bytes_f16 += w.shape[0] * w.shape[1] * 2  # f16 = 2B/元素
                # 反量化误差（vs smooth 后权重，即设备将执行的权重面）
                back = wq.astype(np.float32) * sw
                errs.append(
                    float(np.sqrt(((back - ws) ** 2).mean()) / max(np.sqrt((ws**2).mean()), 1e-12))
                )
    np.savez(OUT, **out)
    errs = np.array(errs)
    print(f"写出 {OUT}")
    print(f"权重体积：int8 {bytes_q/1e6:.0f}MB vs f16 {bytes_f16/1e6:.0f}MB（{bytes_f16/bytes_q:.1f}×）")
    print(f"反量化 rel_rms：中位 {np.median(errs):.3%} 最差 {errs.max():.3%}（L1 无 smooth 谱 0.87-1.04% 的对照位）")


if __name__ == "__main__":
    main()
