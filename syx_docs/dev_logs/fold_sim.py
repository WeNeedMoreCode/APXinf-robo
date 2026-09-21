#!/usr/bin/env python3
# fold_sim.py — 裁决"Gemma 1+w 权重折叠 vs 真 gamma"在 f16 下是否为
# kvk_l1 45% 漂移根因（2026-09-21 最小图已把漂移定位到 L0 MLP 尾）。
# 方法：golden res0（712×2048）出发，f64 教科书链与 f16 模拟链（unfolded
# = 真 (1+w_post) gamma + 原始权重 / folded = 图约定：ones gamma + 折叠
# f16 权重）双路径推到 h1，对拍 golden h1_vis。折叠溢出（>65504→inf）
# 单独统计。
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
                return h.get_tensor(key).float()
    raise KeyError(key)


G = load_file('/data/apxinf/golden/frame0_v3.safetensors')
res0 = torch.from_numpy(G['res0'].astype(np.float64)).reshape(712, 2048)
h1_vis = G['h1_vis'].astype(np.float32).reshape(712, 2048)
h1v = torch.from_numpy(h1_vis.astype(np.float64))

wp = (1.0 + ckpt_get(f'{LP}.post_attention_layernorm.weight')).double()  # [2048]
win = (1.0 + ckpt_get(f'{L1}.input_layernorm.weight')).double()
Wg = ckpt_get(f'{LP}.mlp.gate_proj.weight').double()  # [16384, 2048]
Wu = ckpt_get(f'{LP}.mlp.up_proj.weight').double()
Wd = ckpt_get(f'{LP}.mlp.down_proj.weight').double()  # [2048, 16384]
Wk1 = ckpt_get(f'{L1}.self_attn.k_proj.weight').double()  # [256, 2048]
print(f'(1+w_post): max={wp.max():.1f} min={wp.min():.3f} std={wp.std():.2f}')
print(f'(1+w_in_l1): max={win.max():.1f} std={win.std():.2f}')
print(f'|Wg|max={Wg.abs().max():.1f} |Wu|max={Wu.abs().max():.1f} |Wd|max={Wd.abs().max():.1f}')

def gelu_tanh(x):
    return 0.5 * x * (1.0 + torch.tanh(0.7978845608028654 * (x + 0.044715 * x ** 3)))

def rel(a, b):
    return (a - b).abs().max().item() / b.abs().max().item() * 100

# ---- f64 教科书（unfolded 语义）----
n2 = res0 / res0.pow(2).mean(-1, keepdim=True).sqrt().add(1e-6).double()
gate = n2 * wp @ Wg.T
up = n2 * wp @ Wu.T
act = gelu_tanh(gate) * up
down = act @ Wd.T
h1_u = res0 + down
print(f'f64 unfolded:  h1 vs golden = {rel(h1_u, h1v):.3f}%')

# ---- f16 模拟（unfolded：真 gamma 乘激活，原始 f16 权重）----
n2s = torch.from_numpy((res0.numpy() / np.sqrt((res0.numpy() ** 2).mean(-1, keepdims=True) + 1e-6) * wp.numpy()).astype(np.float16))
Wg16, Wu16, Wd16 = Wg.to(torch.float16), Wu.to(torch.float16), Wd.to(torch.float16)
g = (n2s.float() @ Wg16.float().T).to(torch.float16)
u = (n2s.float() @ Wu16.float().T).to(torch.float16)
a = (gelu_tanh(g.double()).to(torch.float16).float() * u.float()).to(torch.float16)
d = (a.float() @ Wd16.float().T).to(torch.float16)
h1_f16u = (torch.from_numpy(G['res0'].astype(np.float32)).reshape(712, 2048) + d.float()).to(torch.float16)
print(f'f16 unfolded:  h1 vs golden = {rel(h1_f16u.double(), h1v):.3f}%')

# ---- f16 模拟（folded：ones gamma，权重行乘 (1+w) 后 f16）----
WgF = (Wg * wp[None, :]).to(torch.float16)
WuF = (Wu * wp[None, :]).to(torch.float16)
inf_ct = int(torch.isinf(WgF.float()).sum() + torch.isinf(WuF.float()).sum())
ovf_ct = int(((Wg * wp[None, :]).abs() > 65504).sum() + ((Wu * wp[None, :]).abs() > 65504).sum())
print(f'折叠溢出: |w*(1+wp)|>65504 计数 = {ovf_ct}（inf 后 {inf_ct}）')
n2o = torch.from_numpy((res0.numpy() / np.sqrt((res0.numpy() ** 2).mean(-1, keepdims=True) + 1e-6)).astype(np.float16))
g2 = (n2o.float() @ WgF.float().T).to(torch.float16)
u2 = (n2o.float() @ WuF.float().T).to(torch.float16)
a2 = (gelu_tanh(g2.double()).to(torch.float16).float() * u2.float()).to(torch.float16)
d2 = (a2.float() @ Wd16.float().T).to(torch.float16)
h1_f16f = (torch.from_numpy(G['res0'].astype(np.float32)).reshape(712, 2048) + d2.float()).to(torch.float16)
print(f'f16 folded:    h1 vs golden = {rel(h1_f16f.double(), h1v):.3f}%')

# ---- 通道结构对照（folded 模拟 vs 图实测槽 out9）----
a9 = np.fromfile('/data/apxinf/attnmin/attnmin_out9.f16', dtype='<f2').astype(np.float32).reshape(712, 2048)
ch_sim = (h1_f16f.double() - h1v).abs().amax(0).numpy()
ch_g = np.abs(a9 - h1_vis).max(0)
top_sim = np.argsort(ch_sim)[-5:][::-1]
top_g = np.argsort(ch_g)[-5:][::-1]
print(f'f16 folded 模拟通道 top5: {top_sim} (err {np.sort(ch_sim)[-5:][::-1].round(1)})')
print(f'图槽 out9 实测通道 top5: {top_g} (err {np.sort(ch_g)[-5:][::-1].round(1)})')
print(f'f16 folded vs unfolded 的 h1 差: {rel(h1_f16f.double(), h1_f16u.double()):.3f}%')
