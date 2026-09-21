#!/usr/bin/env python3
# attnmin_scan.py — 最小图（GEB_OPTEST=attn，2 层延伸版）逐槽离线判读。
# 背景：最小图复现全净图 kvk_l1 45.2%（out11=45.224%）——漂移定位到
# L0 MLP 尾（gate/up N=16384 / down K=16384 的宽 mm，M=712 非 16 倍数）。
# 本脚本：模型 introspection 全量 dump 的槽对号（值匹配 golden）、
# inf/nan 扫描、kvk1 行画像、h1 通道误差结构。
import numpy as np
from safetensors.numpy import load_file

G = load_file('/data/apxinf/golden/frame0_v3.safetensors')
p, PW, KVD, INTER = 712, 2048, 256, 16384

def ld(i, n):
    a = np.fromfile(f'/data/apxinf/attnmin/attnmin_out{i}.f16', dtype='<f2')
    assert a.size == n, (i, a.size, n)
    return a.astype(np.float32)

targets = {}
for k in ['x0_vis', 'm0_vis', 'res0', 'h1_vis']:
    v = G[k].astype(np.float32).reshape(-1)
    assert v.size == p * PW, (k, v.size)
    targets[k] = v
kvk1 = G['kvk_l1'].astype(np.float32).reshape(p, KVD)

def rel(a, b):
    return np.abs(a - b).max() / np.abs(b).max() * 100

print('== [712,2048] 槽对号（rel% vs golden，升序前 3）==')
slots = {}
for i in [0, 2, 3, 4, 5, 7, 9, 10]:
    a = ld(i, p * PW)
    nan = int(np.isnan(a).sum()); inf = int(np.isinf(a).sum())
    best = sorted(((rel(a, t), k) for k, t in targets.items()))[:3]
    print(f'out{i}: nan={nan} inf={inf} ' + '  '.join(f'{k}={r:.3f}%' for r, k in best))
    slots[i] = a
print('重复槽检查: out2==out7', np.array_equal(slots[2], slots[7]),
      '| out4==out5', np.array_equal(slots[4], slots[5]))

print('== act(out8) [712,16384] inf/nan ==')
a8 = ld(8, p * INTER)
print(f'nan={int(np.isnan(a8).sum())} inf={int(np.isinf(a8).sum())} |max|={np.abs(a8).max():.1f}')

print('== kvk1(out11) vs golden kvk_l1 ==')
a11 = ld(11, p * KVD).reshape(p, KVD)
print(f'rel={rel(a11.reshape(-1), kvk1.reshape(-1)):.3f}% '
      f'nan={int(np.isnan(a11).sum())} inf={int(np.isinf(a11).sum())}')
E = np.abs(a11 - kvk1)
print('行画像（64 行一桶 max|err|/该桶 max|k|）：')
for s in range(0, p, 64):
    sl = slice(s, min(s + 64, p))
    print(f'  rows {s:3d}-{min(s + 64, p) - 1:3d}: {E[sl].max() / np.abs(kvk1[sl]).max() * 100:8.2f}%')

# h1 槽（vs h1_vis 最小的那个）通道误差结构
hi = min(slots, key=lambda i: rel(slots[i], targets['h1_vis']))
h = slots[hi].reshape(p, PW); H = targets['h1_vis'].reshape(p, PW)
ch = np.abs(h - H).max(0)
chmag = np.abs(H).max(0)
top = np.argsort(ch)[-10:][::-1]
print(f'== h1 候选槽 out{hi}: 行画像 + 通道结构 ==')
Eh = np.abs(h - H)
for s in range(0, p, 128):
    sl = slice(s, min(s + 128, p))
    print(f'  rows {s:3d}-{min(s + 128, p) - 1:3d}: {Eh[sl].max() / np.abs(H[sl]).max() * 100:8.2f}%')
print('通道误差 top10（err, |golden|max, 通道号）:')
for c in top:
    print(f'  ch{c:4d}: err={ch[c]:9.2f} |H|max={chmag[c]:9.2f} 比值={ch[c] / max(chmag[c], 1e-9):7.2f}')
print(f'通道误差中位={np.median(ch):.3f}  top10/中位倍数={np.sort(ch)[-10:].mean() / max(np.median(ch), 1e-9):.1f}')
