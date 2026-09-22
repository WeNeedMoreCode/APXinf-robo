#!/usr/bin/env python3
"""Replay 动作刑侦：engine actions vs torch nact 的偏差结构判别.

读 ge_model_probe GEB_REPLAY_DUMP 的原始二进制：
  u32 帧数；每帧 u32 gd + 50*32 f32 actions(padded, 前 gd 列有效) + 50*gd f32 nact

判别目标：系统性偏差（bias/scale 型——实现 bug，可修） vs 去相关噪声
（fp16 执行序差——精度天花板）。维度分解 + horizon 早期行（eval 实际执行
的前 5 行）单独统计。
"""
import sys
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "/data/apxinf/replay/dump_t0n32.bin"
raw = open(path, "rb").read()
off = 0
n = int.from_bytes(raw[off:off + 4], "little"); off += 4
acts, nacts = [], []
for _ in range(n):
    gd = int.from_bytes(raw[off:off + 4], "little"); off += 4
    a = np.frombuffer(raw, dtype="<f4", count=50 * 32, offset=off).reshape(50, 32); off += 50 * 32 * 4
    b = np.frombuffer(raw, dtype="<f4", count=50 * gd, offset=off).reshape(50, gd); off += 50 * gd * 4
    acts.append(a[:, :gd]); nacts.append(b)
A = np.concatenate(acts, 0)   # [n*50, gd]
B = np.concatenate(nacts, 0)
print(f"frames={n} gd={A.shape[1]} elems={A.size}")
print(f"engine: mean|a|={np.abs(A).mean():.4f} max|a|={np.abs(A).max():.3f} std={A.std():.4f}")
print(f"torch : mean|b|={np.abs(B).mean():.4f} max|b|={np.abs(B).max():.3f} std={B.std():.4f}")

D = A - B
print(f"\n[全局] diff mean={D.mean():+.5f} std={D.std():.5f} max={np.abs(D).max():.4f}")
print(f"[全局] corr(A,B)={np.corrcoef(A.ravel(), B.ravel())[0,1]:.4f}")
print(f"[全局] R^2={np.corrcoef(A.ravel(), B.ravel())[0,1]**2:.4f}")
# 线性回归 B ~ αA+β（系统性尺度/偏移检验）
alpha, beta = np.polyfit(A.ravel(), B.ravel(), 1)
resid = B.ravel() - (alpha * A.ravel() + beta)
print(f"[线性拟合] alpha={alpha:.4f} beta={beta:+.5f} resid_std={resid.std():.5f}"
      f" (std(B)={B.std():.5f} → 残差占比 {resid.std()/B.std()*100:.1f}%)")

print("\n[per-dim] dim: corr | bias(mean diff) | scale(std_A/std_B) | std_diff")
for c in range(A.shape[1]):
    cc = np.corrcoef(A[:, c], B[:, c])[0, 1] if A[:, c].std() > 0 else float("nan")
    print(f"  dim{c}: corr={cc:+.4f} bias={D[:, c].mean():+.5f} "
          f"scale={A[:, c].std()/max(B[:, c].std(),1e-9):.4f} "
          f"stdB={B[:, c].std():.4f} stdD={D[:, c].std():.5f}")

print("\n[horizon profile] 行 0-4（eval 每 chunk 实际执行）vs 5-49")
for lo, hi, tag in [(0, 5, "rows0-4"), (5, 20, "rows5-19"), (20, 50, "rows20-49")]:
    a2 = np.concatenate([x[lo:hi] for x in acts], 0)
    b2 = np.concatenate([x[lo:hi] for x in nacts], 0)
    cc = np.corrcoef(a2.ravel(), b2.ravel())[0, 1]
    md = np.abs(a2 - b2).max()
    rm = np.abs(b2).max()
    print(f"  {tag}: corr={cc:+.4f} max_diff={md:.4f} rel={md/rm*100:.1f}% "
          f"(|b|max={rm:.3f})")

print("\n[帧间] 逐帧 corr 与 rel：")
for i in range(min(n, 8)):
    cc = np.corrcoef(acts[i].ravel(), nacts[i].ravel())[0, 1]
    md = np.abs(acts[i] - nacts[i]).max()
    rm = np.abs(nacts[i]).max()
    print(f"  frame{i}: corr={cc:+.4f} rel={md/rm*100:.1f}%")
