#!/usr/bin/env python3
# wmm5_check.py — 机制判别：M[mm输出→addrms] vs G[mm输出→gather拷贝→addrms]。
# ref = f64: y = res0 @ Wout.T; n = y/rms(y); k = n @ Wk1fold.T
import glob
import numpy as np
import torch
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = '/data/apxinf/weights/pi05_libero_finetuned'
LP = 'model.paligemma_with_expert.paligemma.model.language_model.layers.0'
L1 = 'model.paligemma_with_expert.paligemma.model.language_model.layers.1'


def ckpt_get(key):
    for f in sorted(glob.glob(f'{CKPT}/**/*.safetensors', recursive=True)):
        with safe_open(f, framework='torch') as h:
            if key in h.keys():
                return h.get_tensor(key).double()
    raise KeyError(key)


G = load_file('/data/apxinf/golden/frame0_v3.safetensors')
res0 = G['res0'].astype(np.float64).reshape(712, 2048)
win1 = (1.0 + ckpt_get(f'{L1}.input_layernorm.weight')).numpy().reshape(-1)
Wout = ckpt_get(f'{LP}.self_attn.o_proj.weight').numpy()
Wk1 = ckpt_get(f'{L1}.self_attn.k_proj.weight').numpy() * win1[None, :]

y64 = res0 @ Wout.T
n64 = y64 / np.sqrt((y64 ** 2).mean(-1, keepdims=True) + 1e-6)
k_ref = n64 @ Wk1.T
for nm in ['M', 'G']:
    a = np.fromfile(f'/data/apxinf/wmm/wmm5_{nm}.f16', dtype='<f2').astype(np.float32).reshape(712, 256)
    e = np.abs(a - k_ref)
    print(f'链{nm}: rel={e.max() / np.abs(k_ref).max() * 100:8.3f}%  '
          f'视觉行 {e[:512].max() / np.abs(k_ref[:512]).max() * 100:7.2f}%  '
          f'文本行 {e[512:].max() / np.abs(k_ref[512:]).max() * 100:7.2f}%')
