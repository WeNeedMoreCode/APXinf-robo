"""replay_filter.py — replay 文件按真实 token 长度过滤（M3 静态 OM 约束）

record_rollout.py 录的 token_ids_{i} 是 tokenizer pad 到 max_length=200 的
（尾部 pad id=0，torch 侧 attention mask=0 被遮蔽）。引擎静态 OM 全可见
≠ 被遮蔽——精确对拍须：剔除 pad 行、按真实长度 L 重烤 prefix/flow OM
（GEB_TOKENS=L；vision 段与 token 无关可复用）。

用法（apxinf_npu 容器）：
  python3 replay_filter.py /data/apxinf/replay/replay_t0.safetensors [L]
L 缺省 = 全帧众数。产物 replay_t0_L{L}.safetensors（token_ids 截到 L 的
帧子集 + patches/noise/nact/img/state 原样），并打印长度分布与覆盖率。
"""
import sys
from collections import Counter

import numpy as np
from safetensors.numpy import load_file, save_file

SRC = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else None

t = load_file(SRC)
n = sum(1 for k in t if k.startswith("noise_"))
lens = []
for i in range(n):
    ids = t[f"token_ids_{i}"]
    real = int(np.count_nonzero(ids != 0))
    lens.append(real)
dist = Counter(lens)
print(f"[filter] {n} 帧 token 真实长度分布: {dist.most_common()}")
L = int(sys.argv[3]) if len(sys.argv) > 3 else dist.most_common(1)[0][0]
keep = [i for i in range(n) if lens[i] == L]
print(f"[filter] 选 L={L}: 保留 {len(keep)}/{n} 帧（其余 pad 行数不同，静态 OM 不等价）")
if len(keep) == 0:
    sys.exit(1)

out = {}
for j, i in enumerate(keep):
    out[f"patches_{j}"] = t[f"patches_{i}"]
    out[f"token_ids_{j}"] = t[f"token_ids_{i}"][:L]
    out[f"noise_{j}"] = t[f"noise_{i}"]
    out[f"nact_{j}"] = t[f"nact_{i}"]
    for opt in ("img0", "img1", "state"):
        k = f"{opt}_{i}"
        if k in t:
            out[f"{opt}_{j}"] = t[k]
for k in ("meta_success", "meta_steps"):
    if k in t:
        out[k] = t[k]
OUT = dst or SRC.replace(".safetensors", f"_L{L}.safetensors")
save_file(out, OUT)
print(f"saved: {OUT}")
