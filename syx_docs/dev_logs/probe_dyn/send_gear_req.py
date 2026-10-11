#!/usr/bin/env python3
# send_gear_req.py — 手工发一条 gear serve 请求（L 可调；复现首请求崩溃用）
# 用法：python3 send_gear_req.py <chip_dir> <L> [seq]
import struct, sys, time
import numpy as np

chip, L = sys.argv[1], int(sys.argv[2])
seq = int(sys.argv[3]) if len(sys.argv) > 3 else 999
rng = np.random.default_rng(7)
patches = rng.standard_normal((768, 588)).astype(np.float32)
ids = rng.integers(1000, 100000, size=L).astype(np.uint32)
noise = rng.standard_normal((50, 32)).astype(np.float32)
body = struct.pack("<II", 0x47514531, L)
body += patches.tobytes() + ids.tobytes() + noise.tobytes()
# 原子交接（与生产客户端同式）：直写会被 serve 轮询读到半文件
with open(f"{chip}/.req_{seq:06d}.tmp", "wb") as f:
    f.write(body)
import os
os.replace(f"{chip}/.req_{seq:06d}.tmp", f"{chip}/req_{seq:06d}.bin")
print(f"req written: {chip}/req_{seq:06d}.bin L={L} bytes={len(body)}")
t0 = time.time()
while not __import__("os").path.exists(f"{chip}/resp_{seq:06d}.bin"):
    if time.time() - t0 > 60:
        print("TIMEOUT no resp")
        sys.exit(1)
    time.sleep(0.05)
raw = open(f"{chip}/resp_{seq:06d}.bin", "rb").read()
magic, status, tv, tp, tf = struct.unpack_from("<IIfff", raw, 0)
acts = np.frombuffer(raw, dtype=np.float32, count=50 * 7, offset=20)
print(f"resp magic={magic:#x} status={status} tv={tv:.1f} tp={tp:.1f} tf={tf:.1f}")
print(f"actions head={acts[:4]} |max|={np.abs(acts).max():.3f} elapsed={time.time()-t0:.2f}s")
