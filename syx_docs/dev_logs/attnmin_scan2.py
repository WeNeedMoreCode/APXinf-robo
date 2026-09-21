#!/usr/bin/env python3
# attnmin_scan2.py — GEB_ATTN_MLP_PAD=1 版 dump 判读：垫 M 后 act 是否
# 干净（→ 剩余 24.7% 在 down K=16384）/ 仍脏（→ gate/up 还有第二层问题）。
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
res0 = torch.from_numpy(G['res0'].astype(np.float64)).reshape(712, 2048)
wp = (1.0 + ckpt_get(f'{LP}.post_attention_layernorm.weight')).double()
Wg = ckpt_get(f'{LP}.mlp.gate_proj.weight').double()
Wu = ckpt_get(f'{LP}.mlp.up_proj.weight').double()
Wd = ckpt_get(f'{LP}.mlp.down_proj.weight').double()
h1_vis = G['h1_vis'].astype(np.float32).reshape(712, 2048)


def gelu_tanh(x):
    return 0.5 * x * (1.0 + torch.tanh(0.7978845608028654 * (x + 0.044715 * x ** 3)))


def rel_np(a, b):
    return np.abs(a - b).max() / np.abs(b).max() * 100


n2 = res0 / res0.pow(2).mean(-1, keepdim=True).sqrt().add(1e-6)
act64 = (gelu_tanh(n2 * wp @ Wg.T) * (n2 * wp @ Wu.T)).numpy()

a8 = np.fromfile('/data/apxinf/attnmin/attnmin_out8.f16', dtype='<f2').astype(np.float32).reshape(720, 16384)[:712]
E = np.abs(a8 - act64)
print(f'垫M后 act(out8 前712行) vs f64: rel={E.max() / np.abs(act64).max() * 100:.3f}%')
print(f'  行画像: 视觉行 {E[:512].max() / np.abs(act64[:512]).max() * 100:.2f}%  '
      f'文本行 {E[512:].max() / np.abs(act64[512:]).max() * 100:.2f}%')
ch = E.max(0)
print(f'  通道误差 top5: {np.argsort(ch)[-5:][::-1]} err={np.sort(ch)[-5:][::-1].round(1)} 中位={np.median(ch):.4f}')

# down 段 f64 参考下的 h1（用图 act 行不行？—— 先看图 act 干净与否再定）
# h1 槽识别（[712,2048] 各槽 vs h1_vis）
for i in [0, 2, 3, 4, 5, 7, 9]:
    try:
        a = np.fromfile(f'/data/apxinf/attnmin/attnmin_out{i}.f16', dtype='<f2').astype(np.float32).reshape(-1)
    except ValueError:
        continue
    if a.size != 712 * 2048:
        continue
    print(f'out{i}: vs h1_vis={rel_np(a.reshape(712, 2048), h1_vis):9.3f}%')
kv = np.fromfile('/data/apxinf/attnmin/attnmin_out10.f16', dtype='<f2').astype(np.float32)
print(f'kvk1(out10): rel={rel_np(kv, G["kvk_l1"].reshape(-1)):.3f}%')
