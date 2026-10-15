#!/usr/bin/env python3
"""I10 预检：vision 段全投影权重 int8 量化误差谱（纯 host，无 NPU）。

与 C2 时代的 int8_weight_errspec.py 同数学（per-output-row 对称 int8，
s_n = max_k|w[n,:]|/127，与 GEB_OPTEST=qmd probe 一致）；差异：
  1. vision regex 纳入 q/k/v（旧版只匹配 fc\d|out_proj —— handoff "vision 谱
     未测过"即指此缺口）；
  2. vision 按 7 类投影分别聚合（各 27 层），与 prefix/flow 对照组同表打印；
  3. 补 multi_modal_projector（若在册）。
判读门槛（prefix 先例，smoothquant v3 后行为过关）：权重侧 rel_rms ~1%
量级、worst_row 两位数百分比且集中在个别行 → 权重侧无障碍。
"""
import re

import numpy as np
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
f16_rms = 2.0**-11 / np.sqrt(3)


def errspec(w: np.ndarray) -> dict:
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


def classify(k: str):
    """ckpt key -> (组名, 明细名) 或 None。"""
    m = re.search(r"layers\.(\d+)\.", k)
    lay = f"L{int(m.group(1)):02d}" if m else "L--"
    if "vision_tower" in k or "vision_model" in k:
        g = re.search(
            r"self_attn\.(q|k|v|out)_proj|mlp\.(fc1|fc2)", k
        )
        if g is None:
            return None
        proj = g.group(1) or g.group(2)
        return (f"vision.{proj}", f"vision.{lay}.{proj}")
    if "multi_modal_projector" in k:
        return ("vision.mmproj", "vision.mmproj")
    if "gemma_expert" in k:
        g = re.search(r"(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)", k)
        if g is None:
            return None
        return ("flow(对照)", f"flow.{lay}.{g.group(1)}")
    if "paligemma" in k and "vision" not in k and "multi_modal" not in k:
        g = re.search(r"(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)", k)
        if g is None:
            return None
        return ("prefix(对照)", f"prefix.{lay}.{g.group(1)}")
    return None


def main():
    groups = {}
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        keys = [k for k in f.keys() if k.endswith(".weight")]
        print(f"total .weight keys = {len(keys)}")
        for k in keys:
            w = f.get_tensor(k).float().numpy()
            if w.ndim != 2 or min(w.shape) < 64:
                continue
            cls = classify(k)
            if cls is None:
                continue
            gkey, name = cls
            groups.setdefault(gkey, []).append((name, errspec(w.astype(np.float32))))

    print(
        f"{'group':<16} {'n':>3} {'rel_rms med':>11} {'rel_rms max':>11}"
        f" {'worst_row max':>13} {'rel_max max':>11}"
    )
    worst_all = []
    for g in sorted(groups):
        items = groups[g]
        rr = sorted(x[1]["rel_rms"] for x in items)
        wr = max(x[1]["worst_row"] for x in items)
        rm = max(x[1]["rel_max"] for x in items)
        print(
            f"{g:<16} {len(items):>3} {rr[len(rr)//2]:>11.4%} {rr[-1]:>11.4%}"
            f" {wr:>13.4%} {rm:>11.4%}"
        )
        worst_all.extend(items)

    # vision 总体（去 mmproj 单件）
    vis = [s for name, s in worst_all if name.startswith("vision.") and "mmproj" not in name]
    if vis:
        rr = sorted(x["rel_rms"] for x in vis)
        print(
            f"\nvision 总体: n={len(vis)} rel_rms med={rr[len(rr)//2]:.4%} "
            f"p90={rr[int(len(rr)*0.9)]:.4%} max={rr[-1]:.4%} "
            f"worst_row max={max(x['worst_row'] for x in vis):.4%}"
        )

    worst_all.sort(key=lambda x: -x[1]["worst_row"])
    print("\nworst_row top12（outlier 通道检查）:")
    for name, spec in worst_all[:12]:
        print(
            f"  {name:<24} rel_rms={spec['rel_rms']:.4%} "
            f"worst_row={spec['worst_row']:.4%} row_med={spec['row_ratio_med']:.4%}"
        )
    print(f"\n对照下限：f16 表示噪声 rel_rms ≈ {f16_rms:.4%}；理论均匀量化 ≈ 0.454%")


if __name__ == "__main__":
    main()
