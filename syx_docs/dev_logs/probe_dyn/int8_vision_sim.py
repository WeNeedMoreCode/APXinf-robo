#!/usr/bin/env python3
"""int8_vision_sim.py — I10 L2-lite：vision 段 W8A8+smooth 离线量化模拟判决。

原料 = golden_gen_visioncalib.py 的 calib_vision_v1.safetensors（venv 包络
+ sim 采样）× ckpt 真权重。模拟数学与 C2 probe 判定的 QuantMatmulDequant
语义对齐（x_quant_mode=pertoken + smooth s_k 折权重）：
    x' = x / s_k；sx_row = max|x'_row|/127；xq = round(x'/sx_row)
    W' = W * s_k[None,:]；sw = max|W'_out|/127；Wq = round(W'/sw)
    y_q = (xq @ Wq.T) · sx_row · sw   vs   y_ref = x @ W.T
α ∈ {0, 0.5} 双消融：α=0 即无 smooth（s_k≡1）——若可行则省整条因子链。
纯 host（容器 CPU 即可，不占 NPU）。
"""
import re

import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
CAL = "/data/apxinf/golden/calib_vision_v1.safetensors"
ALPHAS = (0.5,)
# smooth 因子下限消融：s 下探死通道（fc2 gelu 死通道 envelope≈0 → x/s 放爆
# per-token scale）。floor = s 的绝对下限（prefix 生产因子同概念，v2 工具
# 曾打印 f16 行安全性下限）。100 = 无 floor 现状对照。
S_FLOOR = (0.0, 0.02, 0.05, 0.1, 0.2)
VROOT = "model.paligemma_with_expert.paligemma.model.vision_tower.vision_model.encoder.layers"
MMKEY = "model.paligemma_with_expert.paligemma.model.multi_modal_projector"


def quant_mm(x, w, s):
    """x [m,in] f32, w [out,in] f32, s [in] —— qmd+smooth 数学模拟。"""
    xs = x / s[None, :]
    sx = np.maximum(np.abs(xs).max(axis=1, keepdims=True) / 127.0, 1e-12)
    xq = np.clip(np.round(xs / sx), -127, 127)
    ws = w * s[None, :]
    sw = np.maximum(np.abs(ws).max(axis=1, keepdims=True) / 127.0, 1e-12)
    wq = np.clip(np.round(ws / sw), -127, 127)
    return (xq @ wq.T) * sx * sw.T


def main():
    cal = load_file(CAL)
    venv = {k[5:]: v for k, v in cal.items() if k.startswith("venv_")}
    sims = {}
    for k, v in cal.items():
        if k.startswith("simv_"):
            rest = k[5:]
            tag, site = rest.split("_", 1)
            sims.setdefault(site, []).append(v.astype(np.float32))
    projs = sorted({re.sub(r"_l\d+$", "", s) for s in venv})

    results = {fl: {} for fl in S_FLOOR}
    srange = {}
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for site in sorted(venv):
            proj = re.sub(r"_l\d+$", "", site)
            m = re.search(r"_l(\d+)$", site)
            li = int(m.group(1))
            if site.startswith("vm_"):
                wkey = MMKEY
                # projector wrapper 可能带 .linear
                try:
                    w = f.get_tensor(wkey + ".weight").float().numpy()
                except Exception:
                    w = f.get_tensor(wkey + ".linear.weight").float().numpy()
            else:
                suf = {
                    "vq": "self_attn.q_proj", "vk": "self_attn.k_proj",
                    "vv": "self_attn.v_proj", "vo": "self_attn.out_proj",
                    "vfc1": "mlp.fc1", "vfc2": "mlp.fc2",
                }[proj]
                wkey = f"{VROOT}.{li}.{suf}.weight"
                w = f.get_tensor(wkey).float().numpy()  # [out,in]
            a_k = venv[site]  # [in]
            w_k = np.abs(w).max(axis=0)
            ratio = np.maximum(a_k, 1e-8) / np.maximum(w_k, 1e-8)
            s05 = np.power(ratio, 0.5).astype(np.float32)
            srange.setdefault(proj, []).append((float(s05.min()), float(s05.max())))
            xsm = sims.get(site)
            if xsm is None:
                continue
            for fl in S_FLOOR:
                s = np.maximum(s05, fl) if fl > 0 else s05  # α=0.5 定案
                rels = []
                for x in xsm:
                    x = x.reshape(-1, x.shape[-1])  # [1,r,C] → [r,C]
                    y_ref = x @ w.T
                    y_q = quant_mm(x, w, s)
                    rels.append(
                        float(np.linalg.norm(y_q - y_ref) / np.maximum(np.linalg.norm(y_ref), 1e-9))
                    )
                results[fl].setdefault(proj, []).append((li, max(rels), float(np.mean(rels))))

    print(f"{'proj':<6}", "".join(f"{'floor'+str(fl)+' med/max':>22}" for fl in S_FLOOR),
          f"{'s05 range':>24}")
    verdict = {}
    for proj in projs:
        cols = []
        for fl in S_FLOOR:
            vals = [mx for _, mx, _ in results[fl].get(proj, [])]
            if vals:
                cols.append(f"{np.median(vals):>10.4%}/{max(vals):>9.4%}")
                verdict.setdefault(fl, []).extend(vals)
            else:
                cols.append(f"{'—':>22}")
        sr = srange.get(proj, [])
        smin = min(x[0] for x in sr) if sr else 0
        smax = max(x[1] for x in sr) if sr else 0
        print(f"{proj:<6}", "".join(f"{c:>22}" for c in cols), f"[{smin:.3g},{smax:.3g}]")

    print("\n== 总体判决（α=0.5；对照：prefix smoothquant 先例 0.66-1.42%/层，行为过关）==")
    for fl in S_FLOOR:
        v = verdict.get(fl, [])
        if v:
            print(f"floor={fl}: 层矩阵 med={np.median(v):.4%} p90={np.percentile(v,90):.4%} "
                  f"max={max(v):.4%} (n={len(v)})")


if __name__ == "__main__":
    main()
