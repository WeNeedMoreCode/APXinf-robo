#!/usr/bin/env python3
# wmm_check.py — 宽 N mm 隔离矩阵判读（gate 单算，M/cst-nd/拆半/eager）。
import glob
import numpy as np
import torch
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = '/data/apxinf/weights/pi05_libero_finetuned'
LP = 'model.paligemma_with_expert.paligemma.model.language_model.layers.0'


def ckpt_get(key):
    for f in sorted(glob.glob(f'{CKPT}/**/*.safetensors', recursive=True)):
        with safe_open(f, framework='torch') as h:
            if key in h.keys():
                return h.get_tensor(key).float()
    raise KeyError(key)


G = load_file('/data/apxinf/golden/frame0_v3.safetensors')
res0 = G['res0'].astype(np.float64).reshape(712, 2048)
wp = (1.0 + ckpt_get(f'{LP}.post_attention_layernorm.weight')).double().numpy().reshape(-1)
WgF = ckpt_get(f'{LP}.mlp.gate_proj.weight').double().numpy() * wp[None, :]  # [16384,2048]
n2 = res0 / np.sqrt((res0 ** 2).mean(-1, keepdims=True) + 1e-6)
gate64 = n2 @ WgF.T


def ld(name, rows, cols):
    a = np.fromfile(f'/data/apxinf/wmm/{name}', dtype='<f2')
    assert a.size == rows * cols, (name, a.size, rows * cols)
    return a.astype(np.float32).reshape(rows, cols)


def rep(name, a):
    e = np.abs(a - gate64)
    print(f'{name:12s}: rel={e.max() / np.abs(gate64).max() * 100:8.3f}%  '
          f'视觉行 {e[:512].max() / np.abs(gate64[:512]).max() * 100:7.2f}%  '
          f'文本行 {e[512:].max() / np.abs(gate64[512:]).max() * 100:7.2f}%')


rep('ge_cst712', ld('wmm_ge_cst712.f16', 712, 16384))
rep('ge_nd712', ld('wmm_ge_nd712.f16', 712, 16384))
rep('ge_cst720', ld('wmm_ge_cst720.f16', 720, 16384)[:712])
lo = ld('wmm_ge_lo712.f16', 712, 8192)
hi = ld('wmm_ge_hi712.f16', 712, 8192)
rep('ge_split712', np.concatenate([lo, hi], axis=1))
rep('eager712', ld('wmm_eager712.f16', 712, 16384))
# 拆半各自的通道结构
for nm, a in [('lo', lo), ('hi', hi)]:
    e = np.abs(a - gate64[:, :8192] if nm == 'lo' else gate64[:, 8192:])
    ch = e.max(0)
    print(f'  ge_{nm}712 通道 top5: {np.argsort(ch)[-5:][::-1]} err={np.sort(ch)[-5:][::-1].round(2)} 中位={np.median(ch):.4f}')
