#!/usr/bin/env python3
"""convert_smooth_engine_flow.py — flow smooth npz → 引擎 safetensors。

与 prefix 版（convert_smooth_engine.py）的关键差异：action 层 loader 无
Gemma (1+g) fold（weights.rs 只 take）——引擎图内激活天然 torch 域，
**s_eff = s_npz 直取**，无 g 表、无 unfold（prefix 的两域回图不适用）。

键（对齐 load_int8_smooth 消费面）：
  flow/L{nn}/{proj}/s_eff   f32[k]  = s_npz（权重侧吸收因子）
  flow/L{nn}/{proj}/smooth  f32[k]  = 1/s_npz（算子乘法约定，NSM=3 定案）
  flow/L{nn}/{proj}/inv     f32[k]  = 1/s_npz（GEB_INT8_NATIVE=0 回退行）

⚠ v1 事故教训（2026-09-28）：smooth 恒为 1/s_npz 并打印实值断言域——
漏 invert 的静默错配代价是 s² 放大 ~1300×。
"""
import numpy as np
import torch
from safetensors.torch import save_file

NPZ = "/data/apxinf/pyo3_check/smooth_calib_v2_flow.npz"
OUT = "/data/apxinf/pyo3_check/smooth_calib_v2_flow_engine.safetensors"


def main():
    npz = np.load(NPZ)
    out = {}
    n_mat = 0
    s_min, s_max = 1e30, 0.0
    for key in sorted(npz.files):
        if not key.startswith("flow/"):
            continue
        s_npz = npz[key]
        inv = (1.0 / s_npz).astype(np.float32)
        out[f"{key}/s_eff"] = torch.from_numpy(s_npz.astype(np.float32).copy())
        out[f"{key}/smooth"] = torch.from_numpy(inv.copy())  # 乘法约定：1/s
        out[f"{key}/inv"] = torch.from_numpy(inv.copy())
        n_mat += 1
        s_min = min(s_min, float(inv.min()))
        s_max = max(s_max, float(inv.max()))
    save_file(out, OUT)
    print(f"写出 {OUT}：{n_mat} 矩阵 ×3 键（flow，无 g 表——action 层无 fold）")
    print(f"smooth 行（=1/s_npz，乘法约定）∈ [{s_min:.4g},{s_max:.4g}]")
    assert s_min > 6e-5, "smooth 下溢 f16 次正规域——行精度塌缩，回查包络"
    assert s_max < 65504, "smooth 上溢 f16"


if __name__ == "__main__":
    main()
