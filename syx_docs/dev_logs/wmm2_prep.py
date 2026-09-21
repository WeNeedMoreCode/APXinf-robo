#!/usr/bin/env python3
# wmm2_prep.py — down mm 隔离的输入准备：golden res0 → f64 MLP 前段
# （norm2/gate/up/gelu·up）→ act16 落盘（Rust wmm2 的 Data 输入）。
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

n2 = res0 / np.sqrt((res0 ** 2).mean(-1, keepdims=True) + 1e-6)
g = torch.from_numpy(n2 @ Wg.T)
u = torch.from_numpy(n2 @ Wu.T)
gelu = 0.5 * g * (1.0 + torch.tanh(0.7978845608028654 * (g + 0.044715 * g ** 3)))
act64 = (gelu * u).numpy()
act16 = act64.astype('<f2')
act16.tofile('/data/apxinf/wmm/act_in.f16')
print(f'act_in.f16 落盘: {act16.size} 元素 |act64|max={np.abs(act64).max():.2f}')
