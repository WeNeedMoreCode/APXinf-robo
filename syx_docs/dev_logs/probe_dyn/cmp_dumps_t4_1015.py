#!/usr/bin/env python3
"""cmp_dumps_t4_1015.py — static/dyn 两份 GEB_E2E_DUMP_MID 目录离线互差

用法: cmp_dumps_t4_1015.py <static_dir> <dyn_dir> [Pv]
统计面：逐层 kvk/kvv 的 max_diff / rel% / mean_abs / cosine + actions 互差。
⚠ 两个目录来自两次独立进程（代际噪声 ~0.3% 记忆在案）——权威互差以
run3（dyn vs 合并 golden，同进程内部计算）日志为准；本工具看分布形态。
"""
import sys

import numpy as np

da, db = sys.argv[1], sys.argv[2]
Pv = int(sys.argv[3]) if len(sys.argv) > 3 else 663
DEPTH = 18


def slot(d, i):
    return np.fromfile(f"{d}/ge_slot{i}.f16", dtype="<f2").astype(np.float32)


def stat(tag, a, b):
    d = np.abs(a - b)
    denom = max(np.abs(a).max(), 1e-9)
    cos = float(np.dot(a.ravel(), b.ravel())
                / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    print(f"{tag:12s} max={d.max():.5f} rel={d.max() / denom * 100:6.2f}% "
          f"mean={d.mean():.6f} cos={cos:.6f} @argmax={int(d.argmax())}")


print(f"== per-layer mutual diff (static {da} vs dyn {db}), Pv={Pv} ==")
for li in range(DEPTH):
    stat(f"kvk_l{li}", slot(da, 2 * li).reshape(Pv, 256), slot(db, 2 * li).reshape(Pv, 256))
for li in range(DEPTH):
    stat(f"kvv_l{li}", slot(da, 2 * li + 1).reshape(Pv, 256), slot(db, 2 * li + 1).reshape(Pv, 256))
for key, idx in (("m0_vis", 36), ("h1_vis", 37)):
    try:
        stat(key, slot(da, idx).reshape(Pv, 2048), slot(db, idx).reshape(Pv, 2048))
    except Exception:
        pass
a1 = np.fromfile(f"{da}/ge_actions.f16", dtype="<f2").astype(np.float32)
a2 = np.fromfile(f"{db}/ge_actions.f16", dtype="<f2").astype(np.float32)
stat("actions", a1.reshape(50, -1), a2.reshape(50, -1))
