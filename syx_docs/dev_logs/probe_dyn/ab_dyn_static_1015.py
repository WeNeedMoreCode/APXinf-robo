#!/usr/bin/env python3
"""ab_dyn_static_1015.py — 动态 OM vs 静态 OM 数值分歧 A/B（root-cause 第一步）。

同一条确定性请求（seed 7：patches/ids/noise 全定死，同 L）打给多个 spool
serve，收集 actions 做两两相对差。用法（apxinf_npu 或任意 python3）：
  python3 ab_dyn_static_1015.py <name1>=<spool1>:<L1> [<name2>=<spool2>:<L2> ...]
例：
  python3 ab_dyn_static_1015.py dyn=/data/apxinf/serve_gear/chip4:152 \
      sta=/data/apxinf/serve/tl152:152
判读：跨进程代际噪声地板 ~0.3%（见 memory ge-numerical-cohort-phenomenon）；
 dyn-vs-sta 若 L=152 ≫ L=144 → 动态 OM 高 L 档 bug 实锤。
"""
import os
import struct
import sys
import time

import numpy as np

REQ_MAGIC = 0x47514531
RESP_MAGIC = 0x47525331


def request(spool, L, seq=777):
    rng = np.random.default_rng(7)  # 与 send_gear_req 同 seed：全链确定性
    patches = rng.standard_normal((768, 588)).astype(np.float32)
    ids = rng.integers(1000, 100000, size=L).astype(np.uint32)
    noise = rng.standard_normal((50, 32)).astype(np.float32)
    body = struct.pack("<II", REQ_MAGIC, L)
    body += patches.tobytes() + ids.tobytes() + noise.tobytes()
    with open(f"{spool}/.req_{seq:06d}.tmp", "wb") as f:
        f.write(body)
    os.replace(f"{spool}/.req_{seq:06d}.tmp", f"{spool}/req_{seq:06d}.bin")
    t0 = time.time()
    while not os.path.exists(f"{spool}/resp_{seq:06d}.bin"):
        if time.time() - t0 > 120:
            raise SystemExit(f"TIMEOUT {spool}")
        time.sleep(0.02)
    raw = open(f"{spool}/resp_{seq:06d}.bin", "rb").read()
    os.remove(f"{spool}/req_{seq:06d}.bin") if os.path.exists(f"{spool}/req_{seq:06d}.bin") else None
    os.remove(f"{spool}/resp_{seq:06d}.bin") if os.path.exists(f"{spool}/resp_{seq:06d}.bin") else None
    magic, status = struct.unpack_from("<II", raw, 0)
    assert magic == RESP_MAGIC and status == 0, (magic, status)
    tv, tp, tf = struct.unpack_from("<fff", raw, 8)
    acts = np.frombuffer(raw, dtype=np.float32, count=50 * 7, offset=20).copy()
    return acts, (tv, tp, tf)


def main():
    entries = {}
    for a in sys.argv[1:]:
        name, rest = a.split("=", 1)
        spool, L = rest.rsplit(":", 1)
        entries[name] = (spool, int(L))
    acts = {}
    for name, (spool, L) in entries.items():
        a, seg = request(spool, L)
        acts[name] = a
        print(f"{name:8} L={L} v/p/f={seg[0]:.1f}/{seg[1]:.1f}/{seg[2]:.1f} "
              f"|x|max={np.abs(a).max():.4f}")
    names = list(acts)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            x, y = acts[names[i]], acts[names[j]]
            rel = float(np.linalg.norm(x - y) / max(np.linalg.norm(x), 1e-9))
            md = float(np.abs(x - y).max())
            print(f"DIFF {names[i]} vs {names[j]}: rel={rel:.4%} max_abs={md:.5f}")


if __name__ == "__main__":
    main()
