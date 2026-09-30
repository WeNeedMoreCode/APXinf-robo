#!/usr/bin/env python3
"""golden_gen_v2calib_flow.py — flow 侧逐层真激活 dump（校准 v2 的 flow 扩展）。

prefix 侧 v2（golden_gen_v2calib.py）= 语言塔单帧 4 站点；flow 侧 = 10 步
euler 全程（激活随步演化，而 smooth s 是静态 per-channel ⇒ 取跨步同矩阵
per-channel abs-max 包络——同矩阵同域，与 v1 的混层包络性质不同）：
  fq_l{i}   = q/k/v 输入（attention ada-ln 输出，torch 域）
  fm_l{i}   = o_proj 输入（attention 合并输出）
  fn_l{i}   = gate/up 输入（post-attn ada-ln 输出）
  fact_l{i} = down_proj 输入（gelu(gate)·up）
站点全走 pre-hook（forward_hook 在该 torch_npu 环境全哑——v2 已取证）。
重放机制同 golden_gen_v3.py：prefix 712 replay 得 pkv → embed_suffix(x,t)
+ pwe.forward 10 步，x 逐步更新（t_s = 1.0 + s·dt，v3b 实证源码调度）。
产物 /data/apxinf/golden/frame0_calib_v2_flow.safetensors（只存 per-channel
amax 向量 [C]，不存全激活）。
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
from lerobot.policies.pi05.modeling_pi05 import make_att_2d_masks  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
GOLD = "/data/apxinf/golden/frame0_v3b.safetensors"
OUT = "/data/apxinf/golden/frame0_calib_v2_flow.safetensors"
DEPTH = 18
NSTEPS = 10

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
pwe.paligemma.language_model.config._attn_implementation = "eager"
pwe.gemma_expert.model.config._attn_implementation = "eager"  # v3 同款（f32 mask + f16 q）

g = load_file(GOLD)
x0 = torch.from_numpy(g["x0"]).to(torch.float16)
NIMG_REAL = 512
x0_vis = torch.cat([x0[:NIMG_REAL], x0[768:]], 0).unsqueeze(0).npu()  # [1,712,2048]
Pv = x0_vis.shape[1]

# ⚠ 绕 torchair：modeling_pi05 L606 把 pwe.forward 换成 torch.compile
# (fullgraph=True, npu_backend)——钩子里的 amax 无 fx2ge converter
# （NotImplementedError 取证）。删实例属性恢复类原方法：eager 参考链，
# 正是校准想要的 torch 域激活（v3 的 golden 键经编译链产出，f16 融合序
# 差对 per-channel amax 包络是噪声级）。
try:
    del pwe.forward
    print("[flow] pwe.forward 实例级 torchair 编译已移除（eager 链）")
except AttributeError:
    print("[flow] pwe.forward 无实例级编译（compile_model 未开）")

# ---- prefix 712 replay 得 pkv（v3 同款）----
with torch.no_grad():
    pos = torch.arange(Pv, device=x0_vis.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(torch.ones(1, Pv, Pv, dtype=torch.bool, device=x0_vis.device))
    pv_out = pwe.paligemma.language_model.forward(
        inputs_embeds=x0_vis, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
pkv = pv_out.past_key_values
kcs = pkv.key_cache if hasattr(pkv, "key_cache") else [kv[0] for kv in pkv]
vcs = pkv.value_cache if hasattr(pkv, "value_cache") else [kv[1] for kv in pkv]
print(f"[flow] prefix replay cache: {len(kcs)} 层 k0={tuple(kcs[0].shape)}")

# ---- expert 层 pre-hook（跨步 amax 累积）----
exp = pwe.gemma_expert.model
assert hasattr(exp, "layers"), f"expert .model 无 layers：{type(exp)}"
amax = {}
SITES = {
    "self_attn.q_proj": "fq",
    "self_attn.o_proj": "fm",
    "mlp.gate_proj": "fn",
    "mlp.down_proj": "fact",
}


def _pre_amax(name):
    def f(mod, args, kwargs):
        if not args or not torch.is_tensor(args[0]):
            return
        t = args[0].detach().float()
        m = t.abs().amax(dim=tuple(range(t.dim() - 1)))  # per-channel（末维）
        if name in amax:
            torch.maximum(amax[name], m, out=amax[name])
        else:
            amax[name] = m.clone()
    return f


hooks = []
for i in range(DEPTH):
    lay = exp.layers[i]
    for suf, tag in SITES.items():
        mod = lay
        for part in suf.split("."):  # getattr 不认点路径——逐级解析
            mod = getattr(mod, part)
        hooks.append(mod.register_forward_pre_hook(_pre_amax(f"{tag}_l{i}"), with_kwargs=True))

# ---- 10 步 euler 重放（v3 step0 代码循环化）----
noise = torch.from_numpy(g["noise"]).to(torch.float16).unsqueeze(0).npu()  # [1,50,32]
chunk = model.config.chunk_size
dt = -1.0 / model.config.num_inference_steps
prefix_pad = torch.ones(1, Pv, dtype=torch.bool, device=noise.device)
x = noise.clone()
with torch.no_grad():
    for s in range(NSTEPS):
        t_s = torch.tensor(1.0 + s * dt, dtype=torch.float16, device=noise.device).expand(1)
        suffix_embs, suffix_pad, suffix_att, cond = model.embed_suffix(x, t_s)
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
        x = x + dt * v_t
        print(f"[flow] step {s}: t={1.0 + s * dt:+.2f} |x|max={float(x.abs().max()):.3f} |v|max={float(v_t.abs().max()):.3f}")
for h in hooks:
    h.remove()
print(f"[flow] capture keys={len(amax)}（期望 {DEPTH * 4}）")

golden = {k: v.cpu().numpy() for k, v in amax.items()}
save_file(golden, OUT)
print(f"saved {OUT}: {len(golden)} 向量（{DEPTH} 层 × 4 站点，跨 {NSTEPS} 步 amax 包络）")
for i in (0, 17):
    for tag in ("fq", "fm", "fn", "fact"):
        v = golden[f"{tag}_l{i}"]
        print(f"  {tag}_l{i}: C={v.shape[0]} max={v.max():.2f} min={v.min():.5g}")
