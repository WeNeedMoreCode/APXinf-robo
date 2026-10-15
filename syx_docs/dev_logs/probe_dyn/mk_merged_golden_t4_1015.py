#!/usr/bin/env python3
"""mk_merged_golden_t4_1015.py — static dump → 合并 golden（T4R 互差协议）

用法: mk_merged_golden_t4_1015.py <dump_dir> <out_safetensors>
读 ge_model_probe 的 GEB_E2E_DUMP_MID 产物（slot{2i}=k_l{i} / slot{2i+1}=v_l{i}
f16 raw + ge_actions.f16），把 t4 真帧 golden 的 kvk_l*/kvv_l*/actions（及存在
时的 m0_vis/h1_vis）替换成 static 引擎值 → dyn 跑这份 golden 时 cmp_mid /
GOLDEN PARITY 打的即逐层 dyn-vs-static 互差。
"""
import os
import sys

import numpy as np
from safetensors.numpy import load_file, save_file

GOLDEN = "/data/apxinf/golden/frame0_t4v1b.safetensors"
DEPTH = 18

dump_dir, out = sys.argv[1], sys.argv[2]
golden = load_file(GOLDEN)
Pv = golden["x0_vis"].shape[0]


def slot(i):
    return np.fromfile(f"{dump_dir}/ge_slot{i}.f16", dtype="<f2")


for li in range(DEPTH):
    k, v = slot(2 * li), slot(2 * li + 1)
    assert k.size == Pv * 256, f"slot{2*li} size {k.size} != Pv*256={Pv * 256}"
    assert v.size == Pv * 256, f"slot{2*li+1} size {v.size} != {Pv * 256}"
    golden[f"kvk_l{li}"] = k.reshape(Pv, 256).astype(np.float32)
    golden[f"kvv_l{li}"] = v.reshape(Pv, 256).astype(np.float32)
    # 919 行 x0/m0/h1（无剔除版）不再对——留给 drop_empty 分支的 _vis 键为准
for key, idx in (("m0_vis", 36), ("h1_vis", 37)):
    p = f"{dump_dir}/ge_slot{idx}.f16"
    if os.path.exists(p):
        golden[key] = np.fromfile(p, dtype="<f2").reshape(Pv, 2048).astype(np.float32)
a = np.fromfile(f"{dump_dir}/ge_actions.f16", dtype="<f2").astype(np.float32)
assert a.size % 50 == 0, f"actions size {a.size} 非 50 行"
golden["actions"] = a.reshape(50, -1)
save_file(golden, out)
print(f"merged: {out} Pv={Pv} actions={golden['actions'].shape} "
      f"kvk_l0|max|={np.abs(golden['kvk_l0']).max():.3f}")
