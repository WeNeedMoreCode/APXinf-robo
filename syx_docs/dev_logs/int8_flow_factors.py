#!/usr/bin/env python3
"""int8_flow_factors.py — flow 侧 smooth 因子 + int8 权重金标准（一步出两 npz）。

输入 = golden_gen_v2calib_flow.py 的 per-channel amax 包络（10 步同矩阵包络）
+ checkpoint expert 权重（action 层无 Gemma fold，torch 域直取——与 prefix
的 (1+g) 回图不同，s_eff = s_npz）：
  s_k = (a_k / w_k)^0.5（α=0.5 沿用 prefix 定案）
  smooth npz：flow/L{nn}/{proj} → s（供 convert_smooth_engine_flow.py）
  权重 npz ：flow/L{nn}/{proj}/wq|scale（金标准，对拍 GEB_INT8_DUMP 的
             F{nn}_{proj} dump；q 投影的 fscale=1/√256 由引擎侧折，npz 是
             原权面 → compare 脚本按比值钉）
"""
import numpy as np
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
ACT = "/data/apxinf/golden/frame0_calib_v2_flow.safetensors"
OUT_SMOOTH = "/data/apxinf/pyo3_check/smooth_calib_v2_flow.npz"
OUT_W = "/data/apxinf/pyo3_check/int8_weights_flow_v1.npz"
ROOT = "model.paligemma_with_expert.gemma_expert.model"
ALPHA = 0.5
DEPTH = 18
SRC = {
    "q": ("fq", "self_attn.q_proj"),
    "k": ("fq", "self_attn.k_proj"),
    "v": ("fq", "self_attn.v_proj"),
    "o": ("fm", "self_attn.o_proj"),
    "gate": ("fn", "mlp.gate_proj"),
    "up": ("fn", "mlp.up_proj"),
    "down": ("fact", "mlp.down_proj"),
}


def main():
    with safe_open(ACT, framework="pt", device="cpu") as af:
        acts = {k: af.get_tensor(k).float().numpy() for k in
                [f"{tag}_l{i}" for i in range(DEPTH) for tag in ("fq", "fm", "fn", "fact")]}
    factors = {}
    wout = {}
    bytes_q = bytes_f16 = 0
    errs = []
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        first = f"{ROOT}.layers.0.self_attn.q_proj.weight"
        assert f.get_tensor(first).shape[0] == 2048, "expert 权重键面不符（先核 ROOT）"
        for i in range(DEPTH):
            for proj, (tag, suf) in SRC.items():
                a_k = acts[f"{tag}_l{i}"]
                w = f.get_tensor(f"{ROOT}.layers.{i}.{suf}.weight").float().numpy()  # [out,in]
                w_k = np.abs(w).max(axis=0)  # [in]
                assert len(a_k) == w_k.shape[0], (i, proj, len(a_k), w_k.shape[0])
                s = np.power(np.maximum(a_k, 1e-8) / np.maximum(w_k, 1e-8), ALPHA).astype(np.float32)
                factors[f"flow/L{i:02}/{proj}"] = s
                # 金标准权重面（与 int8_bake_weights.py 同数学）
                ws = w * s
                sw = np.maximum(np.abs(ws).max(axis=1, keepdims=True), 1e-12) / 127.0
                wq = np.clip(np.round(ws / sw), -127, 127).astype(np.int8)
                wout[f"flow/L{i:02}/{proj}/wq"] = wq
                wout[f"flow/L{i:02}/{proj}/scale"] = sw.astype(np.float32).ravel()
                bytes_q += wq.nbytes
                bytes_f16 += w.shape[0] * w.shape[1] * 2
                back = wq.astype(np.float32) * sw
                errs.append(float(np.sqrt(((back - ws) ** 2).mean()) / max(np.sqrt((ws**2).mean()), 1e-12)))
    np.savez(OUT_SMOOTH, **factors)
    np.savez(OUT_W, **wout)
    smax = max(float(v.max()) for v in factors.values())
    smin = min(float(v.min()) for v in factors.values())
    imax = max(float((1.0 / v).max()) for v in factors.values())
    imin = min(float((1.0 / v).min()) for v in factors.values())
    errs = np.array(errs)
    print(f"smooth npz → {OUT_SMOOTH}：{len(factors)} 矩阵，s ∈ [{smin:.4g},{smax:.4g}]")
    print(f"权重 npz → {OUT_W}：int8 {bytes_q/1e6:.0f}MB vs f16 {bytes_f16/1e6:.0f}MB（{bytes_f16/bytes_q:.1f}×）")
    print(f"smooth 行（=1/s，乘法约定）∈ [{imin:.4g},{imax:.4g}]（f16 正规域 (6e-5, 65504)）")
    assert imin > 6e-5, "smooth 下溢 f16 次正规域"
    assert imax < 65504, "smooth 上溢 f16"
    print(f"反量化 rel_rms：中位 {np.median(errs):.3%} 最差 {errs.max():.3%}（prefix L1 谱 0.87-1.04% 对照位）")


if __name__ == "__main__":
    main()
