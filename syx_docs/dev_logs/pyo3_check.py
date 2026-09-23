"""PyO3 GeServeModel 进程内直调验证（rust 容器）：
1) import apxinf_py（cdylib 链 9.0.1 CANN）
2) open tl144 桶 + infer ×3（replay t0 frame0，与 smoke.py 同帧同参考）
3) 对拍 nact：期望与 spool 桶逐位同数字（max_diff=0.0244 / rel=1.0%）
"""
import sys
import time

sys.path.insert(0, "/data/apxinf/pyo3_check")
import numpy as np
import apxinf_py

assert hasattr(apxinf_py, "GeServeModel"), "GeServeModel 缺失（ascend feature 没编进来？）"
print("import OK", apxinf_py.__version__)

p = np.load("/data/apxinf/pyo3_check/patches.npy")
ids = np.load("/data/apxinf/pyo3_check/ids.npy")
noise = np.load("/data/apxinf/pyo3_check/noise.npy")
nact = np.load("/data/apxinf/pyo3_check/nact.npy")
print(f"frame: patches{p.shape} ids{ids.shape} noise{noise.shape} nact|max|={np.abs(nact).max():.3f}")

t0 = time.time()
m = apxinf_py.GeServeModel.open(
    "/data/apxinf/om_cache/tl144", 144,
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
print("PYO3_GESERVE_OK")
