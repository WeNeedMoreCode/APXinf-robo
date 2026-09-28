#!/usr/bin/env python3
"""golden_gen_v2calib.py — 校准 v2 的逐层真激活 dump（prefix 18 层 × 4 站点）。

校准 v1 的 a_k 是四截面包络（x0_vis∪res0∪m0_vis∪prefix_hidden_vis——混层
混域 proxy，2026-09-24 meta 如实记录该限制）。v2 = 每矩阵精确输入激活：
  nrm1_l{i} = input_layernorm 输出（q/k/v 输入，torch 域 = rms(x)·(1+g1)）
  m_l{i}    = o_proj 输入（attention 合并输出）
  nrm2_l{i} = post_attention_layernorm 输出（gate/up 输入）
  act_l{i}  = down_proj 输入（gelu(gate)·up）
单帧（frame0 同款一帧）——v2 修的是"层间分布错配"，多帧扩录仍留 v3。
产物 /data/apxinf/golden/frame0_calib_v2.safetensors（只含激活 dump，不重
复 v3b 的 golden 键）。
"""
import numpy as np
import torch
import torch_npu  # noqa: F401
from safetensors.numpy import load_file, save_file

torch_npu.npu.set_compile_mode(jit_compile=False)
import os
import sys

sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
OUT = "/data/apxinf/golden/frame0_calib_v2.safetensors"
DEPTH = 18

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
pwe.paligemma.language_model.config._attn_implementation = "eager"

g = load_file("/data/apxinf/golden/frame0.safetensors")
x0 = torch.from_numpy(g["x0"]).to(torch.float16)
NIMG_REAL = 512
x0_vis = torch.cat([x0[:NIMG_REAL], x0[768:]], 0).unsqueeze(0).npu()  # [1,712,2048]
Pv = x0_vis.shape[1]

lm0 = pwe.paligemma.model.language_model
cap = {}


def _post(name):
    def f(mod, args, output):
        if name not in cap and torch.is_tensor(output):
            cap[name] = output.detach().clone()
    return f


def _pre(name):
    def f(mod, args, kwargs):
        if name not in cap and args and torch.is_tensor(args[0]):
            cap[name] = args[0].detach().clone()
    return f


hooks = []
for i in range(DEPTH):
    lay = lm0.layers[i]
    # forward_hook 在该 torch_npu 环境全哑（实测 cap 只进 pre-hook 项）——
    # nrm1/nrm2 输出改从消费者输入侧取（数学同物）：
    #   nrm1 输出 = q_proj 输入；nrm2 输出 = gate_proj 输入
    hooks.append(lay.self_attn.q_proj.register_forward_pre_hook(_pre(f"nrm1_l{i}"), with_kwargs=True))
    hooks.append(lay.self_attn.o_proj.register_forward_pre_hook(_pre(f"m_l{i}"), with_kwargs=True))
    hooks.append(lay.mlp.gate_proj.register_forward_pre_hook(_pre(f"nrm2_l{i}"), with_kwargs=True))
    hooks.append(lay.mlp.down_proj.register_forward_pre_hook(_pre(f"act_l{i}"), with_kwargs=True))

with torch.no_grad():
    pos = torch.arange(Pv, device=x0_vis.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(torch.ones(1, Pv, Pv, dtype=torch.bool, device=x0_vis.device))
    pwe.paligemma.language_model.forward(
        inputs_embeds=x0_vis, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
for h in hooks:
    h.remove()
print(f"[dbg] cap={len(cap)} keys={sorted(cap)[:6]}")
print(f"[dbg] lm0 is called model: {lm0 is pwe.paligemma.language_model}")

golden = {}
for i in range(DEPTH):
    for tag in ("nrm1", "m", "nrm2", "act"):
        t = cap[f"{tag}_l{i}"]
        golden[f"{tag}_l{i}"] = t[0].float().reshape(-1, t.shape[-1]).cpu().numpy()
save_file(golden, OUT)
print(f"saved {OUT}: {len(golden)} tensors（{DEPTH} 层 × 4 站点）")
for i in (0, 17):
    for tag in ("nrm1", "m", "nrm2", "act"):
        v = golden[f"{tag}_l{i}"]
        print(f"  {tag}_l{i}: {v.shape} |max|={np.abs(v).max():.2f}")
