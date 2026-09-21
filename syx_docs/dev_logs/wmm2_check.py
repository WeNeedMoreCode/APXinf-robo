#!/usr/bin/env python3
# wmm2_check.py — down mm（K=16384）隔离判读。
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
                return h.get_tensor(key).double()
    raise KeyError(key)


G = load_file('/data/apxinf/golden/frame0_v3.safetensors')
res0 = G['res0'].astype(np.float64).reshape(712, 2048)
wp = (1.0 + ckpt_get(f'{LP}.post_attention_layernorm.weight')).numpy().reshape(-1)
Wg = ckpt_get(f'{LP}.mlp.gate_proj.weight').numpy() * wp[None, :]
Wu = ckpt_get(f'{LP}.mlp.up_proj.weight').numpy() * wp[None, :]
Wd = ckpt_get(f'{LP}.mlp.down_proj.weight').numpy()  # [2048, 16384]

n2 = res0 / np.sqrt((res0 ** 2).mean(-1, keepdims=True) + 1e-6)
g = torch.from_numpy(n2 @ Wg.T)
u = torch.from_numpy(n2 @ Wu.T)
gelu = 0.5 * g * (1.0 + torch.tanh(0.7978845608028654 * (g + 0.044715 * g ** 3)))
act64 = (gelu * u).numpy()
down64 = act64 @ Wd.T
h1_64 = res0 + down64
h1_vis = G['h1_vis'].astype(np.float32).reshape(712, 2048)
print(f'f64 链自检: h1_64 vs golden h1_vis = {np.abs(h1_64 - h1_vis).max() / np.abs(h1_vis).max() * 100:.3f}%')


def ld(p_, rows, cols):
    a = np.fromfile(p_, dtype='<f2')
    assert a.size == rows * cols, (p_, a.size, rows * cols)
    return a.astype(np.float32).reshape(rows, cols)


def rep(name, a):
    e = np.abs(a - down64)
    print(f'{name:14s}: rel={e.max() / np.abs(down64).max() * 100:8.3f}%  '
          f'视觉行 {e[:512].max() / np.abs(down64[:512]).max() * 100:7.2f}%  '
          f'文本行 {e[512:].max() / np.abs(down64[512:]).max() * 100:7.2f}%  '
          f'inf={int(np.isinf(a).sum())}')


d712 = ld('/data/apxinf/wmm/wmm2_ge_0.f16', 712, 2048)
d720 = ld('/data/apxinf/wmm/wmm2_ge_1.f16', 720, 2048)[:712]
de = ld('/data/apxinf/wmm/wmm2_eager712.f16', 712, 2048)
rep('ge_dn712', d712)
rep('ge_dn720', d720)
rep('eager712', de)
# 通道结构（down 输出 = h1 空间）
for nm, a in [('ge712', d712), ('ge720', d720), ('eager', de)]:
    ch = np.abs(a - down64).max(0)
    print(f'  {nm} 通道 top5: {np.argsort(ch)[-5:][::-1]} err={np.sort(ch)[-5:][::-1].round(2)} 中位={np.median(ch):.3f}')
