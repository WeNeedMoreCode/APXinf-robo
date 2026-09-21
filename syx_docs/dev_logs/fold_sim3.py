#!/usr/bin/env python3
# fold_sim3.py — gate/up 段（N=16384 宽 mm + gelu + mul）执行层裁决。
# 已知：act(out8) vs f64 = 20.8%（分岔在 down 之前）；oproj（K=2048,
# N=2048）mm 与 golden 一致（res 0.089%）⇒ 嫌疑 = 宽 N tiling 的 f16
# 累加 / gelu / mul 大 shape 执行。本脚本：f16 分块累加模拟 gate/up
# （chunk 越小越接近逐元素 f16 累加），对齐图 act 的通道指纹。
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
res0f = G['res0'].astype(np.float32).reshape(712, 2048)
res0 = torch.from_numpy(res0f.astype(np.float64))

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
gate64 = n2 * wp @ Wg.T
up64 = n2 * wp @ Wu.T
act64 = (gelu_tanh(gate64) * up64).numpy()
a8 = np.fromfile('/data/apxinf/attnmin/attnmin_out8.f16', dtype='<f2').astype(np.float32).reshape(712, 16384)
WgF = (Wg * wp[None, :]).to(torch.float16)
WuF = (Wu * wp[None, :]).to(torch.float16)
n2o = torch.from_numpy(n2.numpy().astype(np.float16))

for C in [2048, 512, 128, 32, 16]:
    gacc = torch.zeros(712, 16384, dtype=torch.float16)
    uacc = torch.zeros(712, 16384, dtype=torch.float16)
    for s in range(0, 2048, C):
        gp = (n2o[:, s:s + C].float() @ WgF[:, s:s + C].float().T).to(torch.float16)
        up_ = (n2o[:, s:s + C].float() @ WuF[:, s:s + C].float().T).to(torch.float16)
        gacc = (gacc.float() + gp.float()).to(torch.float16)
        uacc = (uacc.float() + up_.float()).to(torch.float16)
    a_ = (gelu_tanh(gacc.double()).to(torch.float16).float() * uacc.float()).to(torch.float16).numpy()
    ch = np.abs(a_ - act64).max(0)
    top = np.argsort(ch)[-5:][::-1]
    print(f'chunk={C:4d}: act_sim vs f64 = {rel_np(a_, act64):8.3f}%   top5通道 {top} err={np.sort(ch)[-5:][::-1].round(1)}')
print(f'图实测:           act     vs f64 = {rel_np(a8, act64):8.3f}%   '
      f'top5通道 {np.argsort(np.abs(a8 - act64).max(0))[-5:][::-1]} '
      f'err={np.sort(np.abs(a8 - act64).max(0))[-5:][::-1].round(1)}')
# 行画像对照（图 act：视觉/文本行）
E = np.abs(a8 - act64)
vis = E[:512].max() / np.abs(act64[:512]).max() * 100
txt = E[512:].max() / np.abs(act64[512:]).max() * 100
print(f'图 act 行画像: 视觉行 {vis:.2f}%  文本行 {txt:.2f}%')
