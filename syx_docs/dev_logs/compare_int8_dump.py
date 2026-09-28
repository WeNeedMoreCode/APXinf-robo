#!/usr/bin/env python3
"""Rust int8 量化 dump（GEB_INT8_DUMP）vs int8_weights_v1.npz 金标准对拍。

Rust 面域：引擎 f32 权重（= torch 域 w·(1+g)）× s_eff（= s_npz/(1+g)）
——与 npz（w×s_npz）只差 f32 结合律 ulp；round 边界翻转计数量。
q 投影：manual attention 的 pscale=1/√2048 折进权重 → wq 逐字节应仍一致
（行量化对整体常数不变），scale 比 = pscale。

用法：python3 compare_int8_dump.py <dump_dir> [projs]
（projs 缺省全 7；用于 GEB_INT8_PROJS 子集运行时对应缩小）
"""
import sys

import numpy as np

NPZ = "/data/apxinf/pyo3_check/int8_weights_v1.npz"
DUMP = sys.argv[1]
PROJS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["q", "k", "v", "o", "gate", "up", "down"]
PSCALE = 256**-0.5  # manual attention pscale = 1/√HD（HD=256，折进 q 权重/bias）
# 判决阈：wq 边界翻转 ulp 级（33M 元素/矩阵的 1e-6 以下）+ scale ulp 级
WQ_TOL = 64
SC_TOL = 1e-4


def main():
    npz = np.load(NPZ)
    n_bad = 0
    tot_diff = 0
    for layer in range(18):
        for proj in PROJS:
            if layer == 17 and proj in ("o", "gate", "up", "down"):
                continue  # 末层图无 o/mlp（kv 输出即终点）——无 dump 亦无意义
            key = f"prefix/L{layer:02d}/{proj}"
            wq_r = np.fromfile(f"{DUMP}/L{layer:02d}_{proj}.wq", dtype=np.int8)
            sc_r = np.fromfile(f"{DUMP}/L{layer:02d}_{proj}.scale", dtype=np.float32)
            wq_g = npz[f"{key}/wq"]
            sc_g = npz[f"{key}/scale"]
            assert wq_r.size == wq_g.size and sc_r.size == sc_g.size, (
                key, wq_r.size, wq_g.size, sc_r.size, sc_g.size)
            dq = int(np.count_nonzero(wq_r != wq_g.ravel()))
            dmax = int(np.abs(wq_r.astype(np.int32) - wq_g.astype(np.int32).ravel()).max()) if dq else 0
            if proj == "q":  # pscale 折入 → scale 同比缩小，比值应钉在 pscale
                ratio = float(np.median(sc_r / sc_g))
                ds = abs(ratio - PSCALE) / PSCALE
                ds_desc = f"ratio={ratio:.6f} (pscale={PSCALE:.6f})"
            else:
                ds = float(np.max(np.abs(sc_r - sc_g) / np.maximum(np.abs(sc_g), 1e-12)))
                ds_desc = f"rel={ds:.2e}"
            ok = dq <= WQ_TOL and dmax <= 1 and ds < SC_TOL
            n_bad += not ok
            tot_diff += dq
            print(f"{'OK ' if ok else 'BAD'} {key}: wq 翻转 {dq}/{wq_g.size}（maxΔ{dmax}），scale {ds_desc}")
    print(f"合计 wq 翻转 {tot_diff}；{'ALL_OK' if n_bad == 0 else f'{n_bad} BAD'}")


if __name__ == "__main__":
    main()
