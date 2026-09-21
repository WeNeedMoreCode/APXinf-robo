#!/usr/bin/env python3
# wmm3_check.py — MLP 尾组合阶梯判读：A_gate / B_gelu / C_act / D_h1 各 vs f64。
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
Wd = ckpt_get(f'{LP}.mlp.down_proj.weight').numpy()

n2 = res0 / np.sqrt((res0 ** 2).mean(-1, keepdims=True) + 1e-6)
gate64 = n2 @ Wg.T
g = torch.from_numpy(gate64)
gelu64 = (0.5 * g * (1.0 + torch.tanh(0.7978845608028654 * (g + 0.044715 * g ** 3)))).numpy()
act64 = gelu64 * (n2 @ Wu.T)
h1_64 = res0 + act64 @ Wd.T
h1_vis = G['h1_vis'].astype(np.float32).reshape(712, 2048)


def rep(name, f, ref, rows=712):
    a = np.fromfile(f'/data/apxinf/wmm/{f}', dtype='<f2').astype(np.float32).reshape(rows, -1)
    e = np.abs(a - ref)
    print(f'{name:8s}: rel={e.max() / np.abs(ref).max() * 100:8.3f}%  '
          f'视觉行 {e[:512].max() / np.abs(ref[:512]).max() * 100:7.2f}%  '
          f'文本行 {e[512:].max() / np.abs(ref[512:]).max() * 100:7.2f}%')


rep('A_gate', 'wmm3_A_gate.f16', gate64)
rep('B_gelu', 'wmm3_B_gelu.f16', gelu64)
rep('C_act', 'wmm3_C_act.f16', act64)
rep('D_h1', 'wmm3_D_h1.f16', h1_vis)
print(f'(f64 自检 h1_64 vs golden: {np.abs(h1_64 - h1_vis).max() / np.abs(h1_vis).max() * 100:.3f}%)')
