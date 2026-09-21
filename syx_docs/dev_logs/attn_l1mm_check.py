#!/usr/bin/env python3
# attn_l1mm_check.py — GEB_ATTN_MIN+L1=mm 的 dump 判读：pre-rope k vs
# f64(h1_64 @ Wk_l1_folded)。干净 ⇒ [h1→mm] 无罪，病在 L1 addrms；
# 脏 ⇒ h1 值在 L1 读取时已坏（上游/别名）。
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
wp = (1.0 + ckpt_get(f'{LP}.post_attention_layernorm.weight')).numpy().reshape(-1)
win1 = (1.0 + ckpt_get(f'{L1}.input_layernorm.weight')).numpy().reshape(-1)
Wg = ckpt_get(f'{LP}.mlp.gate_proj.weight').numpy() * wp[None, :]
Wu = ckpt_get(f'{LP}.mlp.up_proj.weight').numpy() * wp[None, :]
Wd = ckpt_get(f'{LP}.mlp.down_proj.weight').numpy()
Wk1 = ckpt_get(f'{L1}.self_attn.k_proj.weight').numpy() * win1[None, :]

n2 = res0 / np.sqrt((res0 ** 2).mean(-1, keepdims=True) + 1e-6)
g = torch.from_numpy(n2 @ Wg.T)
gelu = 0.5 * g * (1.0 + torch.tanh(0.7978845608028654 * (g + 0.044715 * g ** 3)))
act64 = (gelu * (n2 @ Wu.T)).numpy()
h1_64 = res0 + act64 @ Wd.T
h1_vis = G['h1_vis'].astype(np.float32).reshape(712, 2048)
k_ref = h1_64 @ Wk1.T  # f64 pre-rope k（图 mm 模式的语义）
print(f'f64 自检: h1_64 vs h1_vis = {np.abs(h1_64 - h1_vis).max() / np.abs(h1_vis).max() * 100:.3f}%')

a = np.fromfile('/data/apxinf/attnmin/attnmin_out0.f16', dtype='<f2').astype(np.float32).reshape(712, 256)
e = np.abs(a - k_ref)
print(f'图[h1→k mm→bias] vs f64 k_ref: rel={e.max() / np.abs(k_ref).max() * 100:.3f}%  '
      f'视觉行 {e[:512].max() / np.abs(k_ref[:512]).max() * 100:.2f}%  '
      f'文本行 {e[512:].max() / np.abs(k_ref[512:]).max() * 100:.2f}%')
ch = e.max(0)
print(f'通道 top5: {np.argsort(ch)[-5:][::-1]} err={np.sort(ch)[-5:][::-1].round(2)} 中位={np.median(ch):.4f}')
