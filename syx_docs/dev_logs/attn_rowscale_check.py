#!/usr/bin/env python3
# attn_rowscale_check.py — norm 模式（l1n1 addrms 保留）的误差结构：
# 若 k_graph[r,:] ≈ α_r · k_ref[r,:]（纯行缩放）⇒ addrms 的 rms 分母错；
# 残差大 ⇒ 值乱（布局）。同时反推 addrms 实际用的 rms 与理论 rms 的比。
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
rms64 = np.sqrt((h1_64 ** 2).mean(-1, keepdims=True) + 1e-6)
k_ref = (h1_64 / rms64) @ Wk1.T

a = np.fromfile('/data/apxinf/attnmin/attnmin_l1norm.f16', dtype='<f2').astype(np.float32).reshape(712, 256)
# 每行最小二乘比值 α_r = <k_g, k_r>/<k_r, k_r>，残差 = ||k_g - α k_r||/||k_r||
num = (a.astype(np.float64) * k_ref).sum(1)
den = (k_ref ** 2).sum(1)
alpha = num / den
resid = np.linalg.norm(a.astype(np.float64) - alpha[:, None] * k_ref, axis=1) / np.linalg.norm(k_ref, axis=1)
print(f'行缩放检验: α 分位数 min={alpha.min():.5f} p25={np.percentile(alpha,25):.5f} '
      f'中位={np.median(alpha):.5f} p75={np.percentile(alpha,75):.5f} max={alpha.max():.5f}')
print(f'残差/||k_ref||: 中位={np.median(resid)*100:.3f}%  max={resid.max()*100:.3f}%')
# α ≈ rms_true/rms_used 反推：若 α>1 说明图 rms 偏大
impl_rms = rms64.squeeze(-1) / alpha
print(f'反推 rms_used/rms_true: 中位={np.median(1/alpha):.5f}  (rms_true 中位={np.median(rms64):.2f}, max={rms64.max():.2f})')
# h1 幅值与 α 的相关性（f16 溢出假设：|h1|²>65504 的行 α 异常）
big = (h1_64 ** 2).max(1) > 65504
print(f'|h1|²>65504 的行数: {big.sum()}/712；这些行 α 中位={np.median(alpha[big]) if big.any() else float("nan"):.5f} '
      f'vs 其余 {np.median(alpha[~big]):.5f}')
print(f'每行 max|h1|² 分位: p50={np.percentile((h1_64**2).max(1),50):.0f} p90={np.percentile((h1_64**2).max(1),90):.0f} '
      f'max={(h1_64**2).max():.0f}')
