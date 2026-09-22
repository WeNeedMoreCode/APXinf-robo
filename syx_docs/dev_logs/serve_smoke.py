"""serve 冒烟：replay 帧（已知 torch 参考）直发 GEB_E2E_SERVE 桶，
对拍 normalized_actions——期望 rel 落在 replay 对拍带（task0 L=144 ≈194%）
= serve 链路与 replay 链路数值等价的证据。跑在 apxinf_npu（无需 torch 模型）。
"""
import sys
import time

sys.path.insert(0, "/data/apxinf/robo_src")
import numpy as np
from safetensors.numpy import load_file

from apxinf_robo.npu_ge import _BucketClient

TASK = int(sys.argv[1]) if len(sys.argv) > 1 else 0
t = load_file(f"/data/apxinf/replay/replay_t{TASK}.safetensors")

# 第一帧 + 该帧真实长度（此文件存 pad 后 200——截非零前缀取真 ids，
# 生产闭环 preprocess 直出真长，无此步骤）
i = 0
ids_full = t[f"token_ids_{i}"]
L = int((ids_full != 0).sum())
ids = ids_full[:L].astype(np.uint32)
patches = t[f"patches_{i}"].astype(np.float32)
noise = t[f"noise_{i}"].astype(np.float32)
nact = t[f"nact_{i}"].astype(np.float32)
print(f"[smoke] t{TASK} frame{i}: L={L} patches{patches.shape} noise{noise.shape} "
      f"nact|max|={np.abs(nact).max():.3f}", flush=True)

t0 = time.time()
c = _BucketClient(L)
print(f"[smoke] tl{L} ready in {time.time() - t0:.0f}s", flush=True)

for k in range(3):
    acts, (tv, tp, tf) = c.request(patches, ids, noise)
    md = float(np.abs(acts - nact).max())
    rel = md / float(np.abs(nact).max()) * 100
    print(f"[smoke] try{k}: vision={tv:.1f} prefix={tp:.1f} flow={tf:.1f}ms "
          f"max_diff={md:.4f} rel={rel:.1f}%", flush=True)
print("SMOKE_OK")
