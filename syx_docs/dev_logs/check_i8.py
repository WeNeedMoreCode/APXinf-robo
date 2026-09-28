"""int8 桶直调验证（check.py 的 int8 变体，rust 容器）：
tl144_i8 桶 + GEB_PREFIX_INT8 三件 env（fusion off / smooth 文件 / 开关），
对拍 nact（f16 spool 桶的 t0 frame0 参考——int8 漂移预期 ~13% actions 级）。
"""
import os
import time

# ⚠ 必须在 import apxinf_py / open 之前设置（seg 构造读 env）
os.environ.setdefault("GEB_PREFIX_INT8", "1")
os.environ.setdefault("GEB_INIT_OPT_ge.fusionSwitchFile", "/data/apxinf/fusion_off_inplace.json")
os.environ.setdefault("GEB_INT8_SMOOTH", "/data/apxinf/pyo3_check/smooth_calib_v1_engine.safetensors")

import sys

sys.path.insert(0, "/data/apxinf/pyo3_check")
import numpy as np
import apxinf_py

assert hasattr(apxinf_py, "GeServeModel"), "GeServeModel 缺失（ascend feature 没编进来？）"
print("import OK", apxinf_py.__version__, "| GEB_PREFIX_INT8 =", os.environ.get("GEB_PREFIX_INT8"))

p = np.load("/data/apxinf/pyo3_check/patches.npy")
ids = np.load("/data/apxinf/pyo3_check/ids.npy")
noise = np.load("/data/apxinf/pyo3_check/noise.npy")
nact = np.load("/data/apxinf/pyo3_check/nact.npy")
print(f"frame: patches{p.shape} ids{ids.shape} noise{noise.shape} nact|max|={np.abs(nact).max():.3f}")

t0 = time.time()
m = apxinf_py.GeServeModel.open(
    "/data/apxinf/om_cache/tl144_i8", 144,
    "/data/apxinf/weights/pi05_libero_finetuned", True,
)
print(f"open {time.time() - t0:.1f}s {m!r}")

for i in range(3):
    t1 = time.time()
    acts, ms = m.infer(p, ids, noise)
    wall = (time.time() - t1) * 1e3
    md = float(np.abs(acts - nact[:, :7]).max())
    rm = float(np.abs(nact).max())
    print(
        f"try{i}: vision={ms[0]:.1f} prefix={ms[1]:.1f} flow={ms[2]:.1f} "
        f"sum={ms[0] + ms[1] + ms[2]:.1f} wall={wall:.1f}ms "
        f"max_diff={md:.4f} rel={md / rm * 100:.1f}%",
        flush=True,
    )
