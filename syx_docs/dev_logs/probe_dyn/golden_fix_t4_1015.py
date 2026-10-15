#!/usr/bin/env python3
"""golden_fix_t4_1015.py — T4R ①补：t4 golden 剥 pad 重放（L=真长主档）

golden_gen_t4_1015.py 的 pol.infer 走 processor 默认 pad 到 max_length=200
（pad_token_id=0 尾部）；生产 npu_ge 客户端是「截非零前缀按真长挑桶」
（npu_ge.py _frame_inputs 同式）。本脚本把捕获产物修到引擎真语义：
  1) L = token_ids 非零前缀长（预期 151）
  2) x0_vis = [x0[:512] 真视图, x0[768:768+L] 真文本]（663 行）
  3) prefix replay（全开 mask）→ kvk/kvv×18 + m0_vis/res0/h1_vis +
     prefix_hidden_vis
  4) flow 10 步 euler（固定 noise）→ actions=[50,7]（x[:, :7]）+ step0_x1
     + cond_s{0..9}
  5) 丢 968 行 infer 键（x0/m0/h1/q0i/k0i/v0i——L=151 下长度断言会炸），
     保 vision_out[768]（L 无关）
产物 /data/apxinf/golden/frame0_t4v1b.safetensors
跑法（apxinf_npu 容器，chip 5）：bash /data/apxinf/golden/run_t4fix_1015.sh
"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401
from safetensors.numpy import load_file, save_file

torch_npu.npu.set_compile_mode(jit_compile=False)
sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402
from lerobot.policies.pi05.modeling_pi05 import make_att_2d_masks  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
SRC = "/data/apxinf/golden/frame0_t4v1.safetensors"
OUT = "/data/apxinf/golden/frame0_t4v1b.safetensors"

g = load_file(SRC)
ids = g["token_ids"].astype(np.int64)
nz = int(np.count_nonzero(ids))
assert np.all(ids[nz:] == 0), "pad 不在尾部（非零前缀假设被破坏）"
L = nz
print(f"[fix] token 非零前缀 L={L}（pad {len(ids) - L} 个尾置 id=0）", flush=True)

x0 = torch.from_numpy(g["x0"]).to(torch.float16)
assert x0.shape[0] == 768 + len(ids)
x0_vis = torch.cat([x0[:512], x0[768:768 + L]], 0).unsqueeze(0).npu()
Pv = x0_vis.shape[1]
print(f"[fix] x0_vis {tuple(x0_vis.shape)}", flush=True)

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
for attr in ("embed_image", "forward"):
    try:
        delattr(pwe, attr)
    except AttributeError:
        pass
pwe.paligemma.language_model.config._attn_implementation = "eager"
pwe.gemma_expert.model.config._attn_implementation = "eager"
lm0 = pwe.paligemma.model.language_model

golden = {
    "patches": g["patches"],
    "token_ids": g["token_ids"][:L],
    "noise": g["noise"],
    "vision_out": g["vision_out"],
    "x0_vis": x0_vis[0].float().cpu().numpy(),
}

capv = {}


def _pre(name):
    def f(mod, args, kwargs):
        if name not in capv and args and torch.is_tensor(args[0]):
            capv[name] = args[0].detach().clone()
    return f


hh = [lm0.layers[0].self_attn.o_proj.register_forward_pre_hook(_pre("m0_vis"), with_kwargs=True),
      lm0.layers[0].post_attention_layernorm.register_forward_pre_hook(_pre("res0"), with_kwargs=True),
      lm0.layers[1].input_layernorm.register_forward_pre_hook(_pre("h1_vis"), with_kwargs=True)]
with torch.no_grad():
    pos = torch.arange(Pv, device=x0_vis.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(
        torch.ones(1, Pv, Pv, dtype=torch.bool, device=x0_vis.device))
    pv_out = pwe.paligemma.language_model.forward(
        inputs_embeds=x0_vis, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
for x in hh:
    x.remove()
for k in ("m0_vis", "h1_vis", "res0"):
    golden[k] = capv[k][0].float().reshape(-1, 2048).cpu().numpy()
pkv = pv_out.past_key_values
kcs = pkv.key_cache if hasattr(pkv, "key_cache") else [kv[0] for kv in pkv]
vcs = pkv.value_cache if hasattr(pkv, "value_cache") else [kv[1] for kv in pkv]
print("[fix] prefix replay layers:", len(kcs), "k0", tuple(kcs[0].shape), flush=True)
for i, (k, v) in enumerate(zip(kcs, vcs)):
    golden[f"kvk_l{i}"] = k.float().reshape(-1, k.shape[-1]).cpu().numpy()
    golden[f"kvv_l{i}"] = v.float().reshape(-1, v.shape[-1]).cpu().numpy()
golden["prefix_hidden_vis"] = pv_out.last_hidden_state.float().reshape(-1, 2048).cpu().numpy()

# flow 10 步 euler（同 noise）→ actions + step0_x1 + cond_s
noise_t = torch.from_numpy(g["noise"]).to(torch.float16).unsqueeze(0).npu()
chunk = model.config.chunk_size
dt = -1.0 / model.config.num_inference_steps
x = noise_t.clone()
prefix_pad = torch.ones(1, Pv, dtype=torch.bool, device=x.device)
with torch.no_grad():
    for s in range(int(-1.0 / dt)):
        t_s = torch.tensor(1.0 + s * dt, dtype=torch.float16, device=x.device).expand(1)
        suffix_embs, suffix_pad, suffix_att, cond = model.embed_suffix(x, t_s)
        golden[f"cond_s{s}"] = cond.float().reshape(-1).cpu().numpy()
        suffix_len = suffix_pad.shape[1]
        pre2d = prefix_pad[:, None, :].expand(1, suffix_len, Pv)
        suf2d = make_att_2d_masks(suffix_pad, suffix_att)
        full = torch.cat([pre2d, suf2d], dim=2)
        mask4d = model._prepare_attention_masks_4d(full)
        pos_s = torch.sum(prefix_pad, dim=-1)[:, None] + torch.cumsum(suffix_pad, dim=1) - 1
        outs, _ = pwe.forward(
            attention_mask=mask4d, position_ids=pos_s, past_key_values=pkv,
            inputs_embeds=[None, suffix_embs.to(torch.float16)], use_cache=False,
            adarms_cond=[None, cond])
        v_t = model.action_out_proj(outs[1][:, -chunk:])
        if s == 0:
            golden["step0_x1"] = (x + dt * v_t).float().reshape(-1, 32).cpu().numpy()
        x = x + dt * v_t
golden["actions"] = x[:, :7].float().cpu().numpy()

save_file(golden, OUT)
print(f"[fix] saved: {OUT} L={L} Pv={Pv} actions={golden['actions'].shape} "
      f"step0_x1|max|={float(np.abs(golden['step0_x1']).max()):.3f} "
      f"actions|max|={float(np.abs(golden['actions']).max()):.3f}", flush=True)
