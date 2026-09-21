"""golden_gen_v3.py — 修正语义的 golden 一帧（空视图剔除，712 prefix）

v2 教训（2026-09-21 定位）：v2 的 kvk/step0_x1 来自 968 全开 replay——把
empty_camera 的 256 个 pad token 当一等公民（可见 key + 位置 512..767），
而 infer 真值（9/10 语义）里它们 pad_mask=0 被遮蔽、文本位置 512..711。
数学等价（theory_check.py 实证 h1 0.128%）：infer ≡ 712 可见 token 全开
+ arange(712)。v3 保留 v2 的 infer 侧键（patches/token_ids/noise/actions/
vision_out/x0/m0/h1/q0i/k0i/v0i 原样搬运），重放部分改 712 语义：
  x0_vis[712,2048]（gather 真视图 512 行 + 语言 200 行，与引擎剔除同序）/
  kvk_l*/kvv_l*[712,256] / prefix_hidden_vis / step0_x1（712 起的 suffix）
产物 /data/apxinf/golden/frame0_v3.safetensors。
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
OUT = "/data/apxinf/golden/frame0_v3b.safetensors"

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
pwe.paligemma.language_model.config._attn_implementation = "eager"
pwe.gemma_expert.model.config._attn_implementation = "eager"  # denoise_step L918 同款（sdpa 吃不了 f32 mask + f16 q）

g = load_file("/data/apxinf/golden/frame0.safetensors")
golden = {k: v for k, v in g.items() if not (k.startswith("kvk_l") or k.startswith("kvv_l")
                                             or k in ("prefix_hidden", "step0_x1", "x0_vis"))}
x0 = torch.from_numpy(g["x0"]).to(torch.float16)
NIMG_REAL = 512  # 2 真实视图 × 256
x0_vis = torch.cat([x0[:NIMG_REAL], x0[768:]], 0).unsqueeze(0).npu()  # [1,712,2048]
Pv = x0_vis.shape[1]
golden["x0_vis"] = x0_vis[0].float().cpu().numpy()

# 712 replay 侧层内中间量（引擎 DBG_FULL 槽位对拍用——与 cache 同 forward，
# 自洽）：m0_vis = 层0 attention 合并输出（o_proj 前）、h1_vis = 层0 完整输出
lm0 = pwe.paligemma.model.language_model
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
    pmask = model._prepare_attention_masks_4d(torch.ones(1, Pv, Pv, dtype=torch.bool, device=x0_vis.device))
    pv_out = pwe.paligemma.language_model.forward(
        inputs_embeds=x0_vis, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
for x in hh:
    x.remove()
for k in ("m0_vis", "h1_vis", "res0"):
    golden[k] = capv[k][0].float().reshape(-1, 2048).cpu().numpy()
    print(f"[v3] {k}", golden[k].shape)
pkv = pv_out.past_key_values
kcs = pkv.key_cache if hasattr(pkv, "key_cache") else [kv[0] for kv in pkv]
vcs = pkv.value_cache if hasattr(pkv, "value_cache") else [kv[1] for kv in pkv]
print("[v3] prefix 712 replay cache layers:", len(kcs), "k0", tuple(kcs[0].shape))
for i, (k, v) in enumerate(zip(kcs, vcs)):
    golden[f"kvk_l{i}"] = k.float().reshape(-1, k.shape[-1]).cpu().numpy()
    golden[f"kvv_l{i}"] = v.float().reshape(-1, v.shape[-1]).cpu().numpy()
golden["prefix_hidden_vis"] = pv_out.last_hidden_state.float().reshape(-1, 2048).cpu().numpy()

# ---- flow step0：suffix 语义重放（prefix 可见 712，位置 712..761）----
noise = torch.from_numpy(g["noise"]).to(torch.float16).unsqueeze(0).npu()  # [1,50,32]
chunk = model.config.chunk_size
dt = -1.0 / model.config.num_inference_steps
with torch.no_grad():
    time0 = torch.tensor([1.0], dtype=torch.float16, device=noise.device)
    suffix_embs, suffix_pad, suffix_att, cond = model.embed_suffix(noise, time0)
    suffix_len = suffix_pad.shape[1]
    prefix_pad = torch.ones(1, Pv, dtype=torch.bool, device=noise.device)
    from lerobot.policies.pi05.modeling_pi05 import make_att_2d_masks  # noqa: E402

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
    x1 = noise + dt * v_t
golden["step0_x1"] = x1.float().reshape(-1, x1.shape[-1]).cpu().numpy()
print("[v3] step0_x1 |max|", float(np.abs(golden["step0_x1"]).max()),
      " x0_vis", golden["x0_vis"].shape, " kvk_l0", golden["kvk_l0"].shape)

# ---- v3b 增补：per-step cond（styles bisect 用）----
# sample_actions 的 time 调度 = 1.0 + step·dt（上面已实证源码）；embed_suffix
# 返回的 adarms_cond 是 time_mlp 之后的 conditioning（f16 链路——te 在 mlp 前
# 就 .to(timestep.dtype) 量化成 f16，与引擎 host f32 链是真实语义差）。
for s in range(int(-1.0 / dt)):
    with torch.no_grad():
        t_s = torch.tensor(1.0 + s * dt, dtype=torch.float16, device=noise.device).expand(1)
        _, _, _, cond_s = model.embed_suffix(noise, t_s)
        golden[f"cond_s{s}"] = cond_s.float().reshape(-1).cpu().numpy()
print("[v3b] cond_s0", golden["cond_s0"].shape, "cond_s9", golden["cond_s9"].shape)
save_file(golden, OUT)
print("saved:", OUT)
