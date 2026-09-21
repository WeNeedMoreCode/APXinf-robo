#!/usr/bin/env python3
# addrms_hypo2.py — 核心假设：k-mm 消费了 addrms 的输入（pre-norm h1）
# 而非其输出。五个屏障变体 bit-identical + wmm4（Data 输入）干净的
# 唯一自洽解释。
import glob
import numpy as np
from safetensors import safe_open

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
kd = np.fromfile('/data/apxinf/attnmin/attnmin_l1norm.f16', dtype='<f2').astype(np.float64).reshape(712, 256)
normed = h1 / np.sqrt((h1 ** 2).mean(-1, keepdims=True) + 1e-6)


def rel(a, b):
    return np.abs(a - b).max() / np.abs(b).max() * 100


print(f'k_dirty vs f64 [rms(h1)·1]@Wk1 = {rel(kd, normed @ Wk1.T):.4f}%   （正确语义）')
print(f'k_dirty vs f64 [h1_raw]@Wk1    = {rel(kd, h1 @ Wk1.T):.4f}%   （未归一化——核心假设）')
# 混合假设：部分行归一化部分行未归一化？
e_norm = np.abs(kd - normed @ Wk1.T).max(1)
e_raw = np.abs(kd - h1 @ Wk1.T).max(1)
n_better = (e_norm < e_raw).sum()
print(f'行级判别: 归一化更优的行 {n_better}/712，未归一化更优 {712 - n_better}/712')
