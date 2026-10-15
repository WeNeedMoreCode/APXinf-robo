#!/usr/bin/env python3
"""golden_gen_t4_1015.py — T4R ①：spatial t4 真帧 golden（L=151 主档）

frame0 家族（v1/v3/v3b）是合成帧（随机图 + 重复文本凑 L=200）；2026-10-15
判决链确立「垃圾 payload 混沌地板 11-14%——A/B 数值分歧必须真帧」。
单进程一次加载三段（共享主机纪律：探针合并单进程）：
  1) 真帧采集：libero_spatial task4（0 基 = eval --tasks 4）、
     init_states[0]（= 失败 trial0 同源首帧）、make_env(task, seed 7)、
     set_init_state + 10 步 [0]*6+[-1] settle（= run_episode 同款）
  2) pol.infer(obs, noise=固定 rng) 全 hook 捕获（键面同 golden_gen.py：
     patches/token_ids/noise/actions + vision_out/x0/m0/h1/q0i/k0i/v0i）
  3) v3b 语义重放：x0_vis[512+L] → prefix replay（kvk/kvv×18 层 + m0_vis/
     res0/h1_vis + prefix_hidden_vis）→ flow step0（step0_x1）+ cond_s{0..9}
产物 /data/apxinf/golden/frame0_t4v1.safetensors
跑法（apxinf_npu 容器，chip 5 空卡）：
  bash /data/apxinf/golden/run_t4golden_1015.sh
"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401
import torch.nn.functional as F
from safetensors.numpy import save_file

torch_npu.npu.set_compile_mode(jit_compile=False)
sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402
from apxinf_robo.envs.libero import make_env, libero_images, libero_state_lerobot  # noqa: E402
from lerobot.policies.pi05.modeling_pi05 import make_att_2d_masks  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
OUT = "/data/apxinf/golden/frame0_t4v1.safetensors"
TASK_ID = 4          # libero_spatial 0 基（eval --tasks 4）
ENV_SEED = 7
WAIT_STEPS = 10
NEUTRAL_ACTION = [0.0] * 6 + [-1.0]

# ---------- 1) 真帧（与失败 trial0 同源的首帧）----------
from libero.libero import benchmark  # noqa: E402

suite = benchmark.get_benchmark_dict()["libero_spatial"]()
task = suite.get_task(TASK_ID)
prompt = str(task.language)
init_states = suite.get_task_init_states(TASK_ID)
print(f"[t4] task={getattr(task, 'name', TASK_ID)!r} prompt={prompt!r} "
      f"n_init={len(init_states)}", flush=True)

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
# 绕实例级 torchair fullgraph（embed_image/forward 被包——hook 进不了图）；
# v3/visioncalib 同款：del 实例属性 → 类级 eager 复现
for attr in ("embed_image", "forward"):
    try:
        delattr(pwe, attr)
    except AttributeError:
        pass
pwe.paligemma.language_model.config._attn_implementation = "eager"
pwe.gemma_expert.model.config._attn_implementation = "eager"
# 9/10 语义（golden_gen.py 同款）：只喂 2 真实视图，empty_camera 走 missing
# 路径（_preprocess_images 填 -1 pad 图 + mask=0）——不覆盖则 infer 要 4 键全喂
print("[t4] image_features:", pol._image_features, flush=True)
pol.image_keys = tuple(pol._image_features[:2])
pol._empty_features = tuple(pol._image_features[2:])
print("[t4] effective image_keys:", pol.image_keys, "empty:", pol._empty_features, flush=True)

env = make_env(task, ENV_SEED)
env.reset()
raw = env.set_init_state(init_states[0])
for _ in range(WAIT_STEPS):
    raw, _, _, _ = env.step(NEUTRAL_ACTION)
env.close()
# eval 同款预处理（eval_libero run_episode）：翻转帧 + LeRobot 8 维 state
# （npu-torch/npu-ge 系 ckpt = pos+axis-angle+双指；7 维 openpi 版会 ValueError）
images = libero_images(raw["agentview_image"], raw["robot0_eye_in_hand_image"])
obs = {
    pol.image_keys[0]: images[0],
    pol.image_keys[1]: images[1],
    pol.state_key: libero_state_lerobot(raw),
    pol.prompt_key: prompt,
}
print("[t4] obs:", {k: (f"str:{v[:36]}" if isinstance(v, str) else np.asarray(v).shape)
                    for k, v in obs.items()}, flush=True)

noise = np.random.default_rng(20261015).standard_normal((50, 32)).astype(np.float32)

# ---------- 2) infer 侧捕获（键面同 golden_gen.py）----------
cap = {}


def make_hook(name):
    def f(mod, args, kwargs, out):
        if name in cap:
            return
        entry = {i: a.detach().clone() for i, a in enumerate(args) if torch.is_tensor(a)}
        for k, v in kwargs.items():
            if torch.is_tensor(v):
                entry[("kw", k)] = v.detach().clone()
        if torch.is_tensor(out):
            entry["out"] = out.detach().clone()
        cap[name] = entry
    return f


def mk_pre(name):
    def f(mod, args, kwargs):
        if name in cap:
            return
        if args and torch.is_tensor(args[0]):
            cap[name] = {"in": args[0].detach().clone()}
    return f


targets = {}
for name, mod in model.named_modules():
    low = name.lower()
    if ("vision_tower" in low and "vision_model" not in low) or mod.__class__.__name__ == "SiglipVisionModel":
        targets.setdefault("vision_tower", name)
    if low.endswith("embed_tokens"):
        targets.setdefault("embed_tokens", name)
    if "multi_modal_projector" in low and isinstance(mod, torch.nn.Linear):
        targets.setdefault("projector", name)
    if low.endswith("paligemma.model.language_model.layers.0.input_layernorm"):
        targets.setdefault("x0_ln0", name)
handles = [model.get_submodule(n).register_forward_hook(make_hook(k), with_kwargs=True)
           for k, n in targets.items()]
lm0 = pwe.paligemma.model.language_model
handles.append(lm0.layers[0].self_attn.o_proj.register_forward_pre_hook(mk_pre("m0"), with_kwargs=True))
handles.append(lm0.layers[1].input_layernorm.register_forward_pre_hook(mk_pre("h1"), with_kwargs=True))
handles.append(lm0.layers[0].self_attn.q_proj.register_forward_hook(make_hook("q0i"), with_kwargs=True))
handles.append(lm0.layers[0].self_attn.k_proj.register_forward_hook(make_hook("k0i"), with_kwargs=True))
handles.append(lm0.layers[0].self_attn.v_proj.register_forward_hook(make_hook("v0i"), with_kwargs=True))
print("[t4] hooks:", targets, flush=True)

res = pol.infer(obs, noise=noise)
for h in handles:
    h.remove()

norm_actions = res["normalized_actions"]
print("[t4] normalized_actions", norm_actions.shape, "|max|",
      float(np.abs(norm_actions).max()), flush=True)

pv = cap["vision_tower"][0].float().cpu()
flat = pv.reshape(-1, 3, pv.shape[-2], pv.shape[-1])
u = F.unfold(flat, kernel_size=14, stride=14)
patches = u.permute(0, 2, 1).reshape(-1, u.shape[1]).numpy()
ids = cap["embed_tokens"][0].reshape(-1).cpu()
L = int(ids.numel())
golden = {
    "patches": patches.astype(np.float32),
    "token_ids": ids.numpy().astype(np.float32),
    "noise": noise,
    "actions": np.asarray(norm_actions, dtype=np.float32),
    "vision_out": cap["projector"]["out"].float().reshape(-1, 2048).cpu().numpy(),
    "x0": cap["x0_ln0"][0].detach().float().reshape(-1, 2048).cpu().numpy(),
    "m0": cap["m0"]["in"][0].float().reshape(-1, 2048).cpu().numpy(),
    "h1": cap["h1"]["in"][0].float().reshape(-1, 2048).cpu().numpy(),
    "q0i": cap["q0i"]["out"][0].float().reshape(-1, cap["q0i"]["out"].shape[-1]).cpu().numpy(),
    "k0i": cap["k0i"]["out"][0].float().reshape(-1, cap["k0i"]["out"].shape[-1]).cpu().numpy(),
    "v0i": cap["v0i"]["out"][0].float().reshape(-1, cap["v0i"]["out"].shape[-1]).cpu().numpy(),
}
print(f"[t4] patches {patches.shape} L={L} x0 {golden['x0'].shape}", flush=True)
assert 768 + L == golden["x0"].shape[0], \
    f"x0 行数 {golden['x0'].shape[0]} != 768+L={768 + L}"

# ---------- 3) v3b 语义重放（prefix kv + flow step0 + cond）----------
x0 = torch.from_numpy(golden["x0"]).to(torch.float16)
NIMG_REAL = 512
x0_vis = torch.cat([x0[:NIMG_REAL], x0[768:]], 0).unsqueeze(0).npu()
Pv = x0_vis.shape[1]
golden["x0_vis"] = x0_vis[0].float().cpu().numpy()

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
print("[t4] prefix replay layers:", len(kcs), "k0", tuple(kcs[0].shape), flush=True)
for i, (k, v) in enumerate(zip(kcs, vcs)):
    golden[f"kvk_l{i}"] = k.float().reshape(-1, k.shape[-1]).cpu().numpy()
    golden[f"kvv_l{i}"] = v.float().reshape(-1, v.shape[-1]).cpu().numpy()
golden["prefix_hidden_vis"] = pv_out.last_hidden_state.float().reshape(-1, 2048).cpu().numpy()

# flow step0（t=1.0, dt=-0.1）
noise_t = torch.from_numpy(noise).to(torch.float16).unsqueeze(0).npu()
chunk = model.config.chunk_size
dt = -1.0 / model.config.num_inference_steps
with torch.no_grad():
    time0 = torch.tensor([1.0], dtype=torch.float16, device=noise_t.device)
    suffix_embs, suffix_pad, suffix_att, cond = model.embed_suffix(noise_t, time0)
    suffix_len = suffix_pad.shape[1]
    prefix_pad = torch.ones(1, Pv, dtype=torch.bool, device=noise_t.device)
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
    x1 = noise_t + dt * v_t
golden["step0_x1"] = x1.float().reshape(-1, x1.shape[-1]).cpu().numpy()

# per-step cond（styles bisect 用，同 v3b）
for s in range(int(-1.0 / dt)):
    with torch.no_grad():
        t_s = torch.tensor(1.0 + s * dt, dtype=torch.float16, device=noise_t.device).expand(1)
        _, _, _, cond_s = model.embed_suffix(noise_t, t_s)
        golden[f"cond_s{s}"] = cond_s.float().reshape(-1).cpu().numpy()

save_file(golden, OUT)
print("[t4] saved:", OUT, "L=", L, "Pv=", Pv,
      "step0_x1|max|", float(np.abs(golden["step0_x1"]).max()), flush=True)
