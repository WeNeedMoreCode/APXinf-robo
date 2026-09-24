#!/usr/bin/env python3
"""C2 int8 立项 L1：真权重 per-channel int8 量化误差谱（纯 host，无 NPU）。

对 Gemma expert 全部投影 + action 投影 + SigLIP proj 做 per-output-row
int8 量化（s_n = max_k|w[n,:]|/127，与 GEB_OPTEST=qmd probe 同数学），
报每矩阵的量化噪声能量比（rel_rms ≈ 输出相对误差的直接外推：
Δy/y 的 std 比 ≈ ΔW 行 rms / W 行 rms）。对照下限 = f16 表示误差。
"""
import glob
import re

import numpy as np
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
f16_rms = 2.0**-11 / np.sqrt(3)  # f16 表示噪声能量比下限（对照）


def errspec(w: np.ndarray) -> dict:
    """w [out, in] f32，per-output-row int8 量化误差。"""
    amax = np.abs(w).max(axis=1, keepdims=True)
    s = np.maximum(amax / 127.0, 1e-12)
    wq = np.clip(np.round(w / s), -127, 127) * s
    err = wq - w
    row_rms_ratio = np.sqrt((err**2).mean(axis=1)) / np.maximum(
        np.sqrt((w**2).mean(axis=1)), 1e-12
    )
    return {
        "rel_rms": float(np.sqrt((err**2).mean()) / np.sqrt((w**2).mean())),
        "rel_max": float(np.abs(err).max() / np.abs(w).max()),
        "worst_row": float(row_rms_ratio.max()),
        "row_ratio_med": float(np.median(row_rms_ratio)),
    }


def main():
    groups = {}  # 组名 -> [ (矩阵名, errspec) ]
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        keys = [k for k in f.keys() if k.endswith(".weight")]
        for k in keys:
            w = f.get_tensor(k).float().numpy()
            if w.ndim != 2 or min(w.shape) < 64:
                continue
            m = re.search(r"layers\.(\d+)\.", k)
            lay = f"L{int(m.group(1)):02d}" if m else "L--"
            if "gemma_expert" in k:
                g = re.search(r"(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)", k)
                if g is None:
                    continue
                name = f"gemma.{lay}.{g.group(1)}"
            elif "action_" in k:
                name = f"action.{k.split('action_')[1].split('.')[0]}"
            elif "paligemma" in k and "vision" not in k and "multi_modal" not in k:
                name = f"paligemma.{lay}.{k.rsplit('.', 2)[-2]}"
            elif "vision_tower" in k or ("vision_model" in k):
                g2 = re.search(r"(\d+)\.(fc\d|out_proj)", k)
                name = f"siglip.L{g2.group(1)}.{g2.group(2)}" if g2 else None
            else:
                name = None
            if name is None:
                continue
            spec = errspec(w.astype(np.float32))
            # 分组键保留前缀（prefix=paligemma 主干 / flow=gemma_expert 分开）
            gkey = ".".join(name.split(".")[:2]) if "siglip" not in name else name.rsplit(".", 1)[0]
            groups.setdefault(gkey, []).append((name, spec))

    # 汇总打印：组级 worst + 明细 top 坏件
    print(f"{'group':<28} {'n':>3} {'rel_rms med':>11} {'rel_rms max':>11} {'worst_row max':>13} {'rel_max max':>11}")
    worst_all = []
    for g in sorted(groups):
        items = groups[g]
        rr = sorted(x[1]["rel_rms"] for x in items)
        wr = max(x[1]["worst_row"] for x in items)
        rm = max(x[1]["rel_max"] for x in items)
        print(f"{g:<28} {len(items):>3} {rr[len(rr)//2]:>11.4%} {rr[-1]:>11.4%} {wr:>13.4%} {rm:>11.4%}")
        worst_all.extend(items)
    worst_all.sort(key=lambda x: -x[1]["worst_row"])
    print("\nworst_row top10（outlier 通道检查）:")
    for name, spec in worst_all[:10]:
        print(f"  {name:<44} rel_rms={spec['rel_rms']:.4%} worst_row={spec['worst_row']:.4%} row_med={spec['row_ratio_med']:.4%}")
    print(f"\n对照下限：f16 表示噪声 rel_rms ≈ {f16_rms:.4%}；理论均匀量化 ≈ 0.454%")


if __name__ == "__main__":
    main()
