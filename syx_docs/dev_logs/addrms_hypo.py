#!/usr/bin/env python3
# addrms_hypo.py — norm 模式脏 k 的错误公式穷举（纯离线）。
# 已知：图 h1 值净（0.032%）；f64 rms(h1)@Wk1 与图输出差 12.9%；wmm4
# 同值 Data 输入干净。对 dump 试各错误假设，找 0 误差匹配。
import glob
import numpy as np
import torch
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = '/data/apxinf/weights/pi05_libero_finetuned'
L1 = 'model.paligemma_with_expert.paligemma.model.language_model.layers.1'


def ckpt_get(key):
    for f in sorted(glob.glob(f'{CKPT}/**/*.safetensors', recursive=True)):
        with safe_open(f, framework='torch') as h:
            if key in h.keys():
                return h.get_tensor(key).double()
    raise KeyError(key)


win1 = (1.0 + ckpt_get(f'{L1}.input_layernorm.weight')).numpy().reshape(-1)
Wk1 = ckpt_get(f'{L1}.self_attn.k_proj.weight').numpy() * win1[None, :]

h1 = np.fromfile('/data/apxinf/attnmin/graph_h1.f16', dtype='<f2').astype(np.float64).reshape(712, 2048)
k_dirty = np.fromfile('/data/apxinf/attnmin/attnmin_l1norm.f16', dtype='<f2').astype(np.float64).reshape(712, 256)


def rel(a, b):
    return np.abs(a - b).max() / np.abs(b).max() * 100


base = (h1 / np.sqrt((h1 ** 2).mean(-1, keepdims=True) + 1e-6)) @ Wk1.T
print(f'基线（f64 行 rms）: rel vs 图脏输出 = {rel(k_dirty, base):.3f}%')

hyp = {}
# 1. 全局 rms
grms = np.sqrt((h1 ** 2).mean() + 1e-6)
hyp['全局rms'] = (h1 / grms) @ Wk1.T
# 2. mean 代替 rms（减均值）
mu = h1.mean(-1, keepdims=True)
hyp['(x-mean)/rms'] = ((h1 - mu) / np.sqrt(((h1 - mu) ** 2).mean(-1, keepdims=True) + 1e-6)) @ Wk1.T
# 3. eps 变体
for eps in [1e-5, 1e-3, 1e-1, 1.0]:
    hyp[f'eps={eps}'] = (h1 / np.sqrt((h1 ** 2).mean(-1, keepdims=True) + eps)) @ Wk1.T
# 4. 行宽 2047/2049（错步长）
for w in [2047, 2049, 4096]:
    if w == 4096:
        h2 = np.concatenate([h1, h1[:, :2048]], 1)
        hyp[f'宽{w}'] = (h2 / np.sqrt((h2 ** 2).mean(-1, keepdims=True) + 1e-6))[:, :2048] @ Wk1.T
    else:
        m = (h1 ** 2)[:, :w].mean(-1, keepdims=True) if w < 2048 else None
        if m is not None:
            hyp[f'前{w}列rms'] = (h1 / np.sqrt(m + 1e-6)) @ Wk1.T
# 5. f16 平方饱和（saturate 到 ±65504 再求和）
h1sat = np.clip(h1, -np.sqrt(65504.0), np.sqrt(65504.0))  # 平方饱和的等价 clamp
# 真正语义：x² 计算结果 clamp 到 65504
sq = np.clip(h1 ** 2, None, 65504.0)
hyp['平方饱和'] = (h1 / np.sqrt(sq.mean(-1, keepdims=True) + 1e-6)) @ Wk1.T
# 6. bf16 输入舍入后 rms
h1bf = torch.from_numpy(h1.astype(np.float32)).to(torch.bfloat16).to(torch.float32).numpy().astype(np.float64)
hyp['bf16入rms'] = (h1bf / np.sqrt((h1bf ** 2).mean(-1, keepdims=True) + 1e-6)) @ Wk1.T
# 7. f16 累加（分块 128）
sq16 = (h1 ** 2)
acc = np.zeros(712)
for s in range(0, 2048, 128):
    acc = (acc + sq16[:, s:s + 128].sum(-1)).astype(np.float16).astype(np.float64)
hyp['f16累加rms'] = (h1 / np.sqrt(acc[:, None] / 2048 + 1e-6)) @ Wk1.T
# 8. 跳行读（stride 2048 的 2 倍 = 取偶数行拼）
h1p = h1.reshape(1424, 1024)  # 错位解释假想
hyp['reshape1424'] = None
for nm, v in hyp.items():
    if v is not None:
        print(f'{nm:14s}: rel = {rel(k_dirty, v):10.4f}%')
# 9. 比值诊断：k_dirty 与 base 的逐元素比值分布（若为常数缩放可见）
r = k_dirty / base
print(f'逐元素比值: p5={np.percentile(r,5):.4f} p50={np.percentile(r,50):.4f} p95={np.percentile(r,95):.4f}')
d = np.abs(k_dirty - base)
print(f'误差行 top5 行号: {np.argsort(d.max(1))[-5:][::-1]}, 误差通道 top5: {np.argsort(d.max(0))[-5:][::-1]}')
# 10. 零行检测（addrms 输出若有整行 0 = inf rms）
zr = (np.abs(k_dirty).max(1) == 0).sum()
print(f'图脏输出全零行数: {zr}')
