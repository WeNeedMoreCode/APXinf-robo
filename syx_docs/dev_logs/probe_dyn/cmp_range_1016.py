#!/usr/bin/env python3
"""cmp_range_1016.py — range padding 桶版 dump（P 行）vs 精确版（真 L 行）互差

用法: cmp_range_1016.py <exact_dir> <range_dir> <Pv_true> <Pb_bucket>
真行 = 每槽前 Pv_true 行（行主序前缀：视觉 ‖ 真语言，pad 恒在尾）。
判据：mask 数学精确 ⇒ 真行互差 ≈0（近 bit 级）；actions 直接全量比。
"""
import sys

import numpy as np

da, db = sys.argv[1], sys.argv[2]
pv, pb = int(sys.argv[3]), int(sys.argv[4])
DEPTH = 18


def slot(d, i, rows):
    a = np.fromfile(f"{d}/ge_slot{i}.f16", dtype="<f2").astype(np.float32)
    return a[: rows * 256].reshape(rows, 256)


def stat(tag, a, b):
    d = np.abs(a - b)
    denom = max(np.abs(a).max(), 1e-9)
    cos = float(np.dot(a.ravel(), b.ravel())
                / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    print(f"{tag:10s} max={d.max():.6f} rel={d.max() / denom * 100:7.3f}% cos={cos:.8f}")


print(f"== range-padding mutual (exact {da} vs bucket {db}), true {pv} / bucket {pb} ==")
for li in range(DEPTH):
    stat(f"kvk_l{li}", slot(da, 2 * li, pv), slot(db, 2 * li, pv))
for li in range(DEPTH):
    stat(f"kvv_l{li}", slot(da, 2 * li + 1, pv), slot(db, 2 * li + 1, pv))
a1 = np.fromfile(f"{da}/ge_actions.f16", dtype="<f2").astype(np.float32)
a2 = np.fromfile(f"{db}/ge_actions.f16", dtype="<f2").astype(np.float32)
stat("actions", a1, a2)
