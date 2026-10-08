#!/usr/bin/env python3
"""convert_smooth_flow_npz.py — flow smooth npz → 引擎 safetensors（参数化版）。

convert_smooth_engine_flow.py 的 argv 化副本（v2 原版 NPZ/OUT 路径硬编码，
校准 v3 起需要多版本并存）：
  python3 convert_smooth_flow_npz.py /data/apxinf/pyo3_check/smooth_calib_v3_flow.npz
键语义同原版：s_eff = s_npz 直取（action 层无 Gemma fold）、smooth = inv
= 1/s_npz（算子乘法约定，NSM=3 定案）。断言 f16 正规域（v1 溢出事故防线）。
"""
import sys

import numpy as np
import torch
from safetensors.torch import save_file

NPZ = sys.argv[1] if len(sys.argv) > 1 else "/data/apxinf/pyo3_check/smooth_calib_v2_flow.npz"
OUT = NPZ.replace(".npz", "_engine.safetensors")


def main():
    npz = np.load(NPZ)
    out = {}
    n_mat = 0
    s_min, s_max = 1e30, 0.0
    inv_min, inv_max = 1e30, 0.0
    for key in sorted(npz.files):
        if not key.startswith("flow/"):
            continue
        s = torch.from_numpy(npz[key].astype(np.float32))
        assert s.dim() == 1, f"{key} 非 1-D"
        inv = torch.ones_like(s) / s
        out[key + "/s_eff"] = s
        out[key + "/smooth"] = inv.clone()
        out[key + "/inv"] = inv
        n_mat += 1
        s_min = min(s_min, float(s.min()))
        s_max = max(s_max, float(s.max()))
        inv_min = min(inv_min, float(inv.min()))
        inv_max = max(inv_max, float(inv.max()))
    save_file(out, OUT)
    print(f"写出 {OUT}：{n_mat} 矩阵 ×3 键（flow，无 g 表——action 层无 fold）")
    print(f"  s ∈ [{s_min:.4g},{s_max:.4g}] smooth=1/s ∈ [{inv_min:.4g},{inv_max:.4g}]")
    assert inv_min > 6e-5, "smooth 下溢 f16 次正规域"
    assert inv_max < 65504, "smooth 上溢 f16"


if __name__ == "__main__":
    main()
