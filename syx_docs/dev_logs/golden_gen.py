"""golden_gen.py — M3 e2e golden 一帧 dump（probe GEB_E2E_GOLDEN 对拍源）

npu 容器跑法：
  ASCEND_RT_VISIBLE_DEVICES=7 python3 /data/apxinf/golden_gen.py
产物 /data/apxinf/golden/frame0.safetensors（全 f32）：
  patches[768,588] / token_ids[N] / noise[50,32] / actions[50,32]
  段边界 bisect 中间量：vision_out[768,2048] / x0[968,2048] /
  kvk_l{0..17}[968,256] + kvv_l{0..17}（prefix k/v cache，post-rope）/
  prefix_hidden[968,2048] / step0_x1[50,32]（denoise step0 后 x）
注意：paligemma.language_model.forward / gemma_expert.model.forward 在
modeling_pi05 里是直接 .forward() 调用（绕过 __call__，模块 hook 不触发）——
x0 用 layer0.input_layernorm hook 抓；kv/step0 用模型自身方法手工重放。
"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401

torch_npu.npu.set_compile_mode(jit_compile=False)

sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
OUT = "/data/apxinf/golden/frame0.safetensors"

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model

# 9/10 语义：只喂 2 真实视图，empty_camera 缺省（_preprocess_images 填
# -1 pad 图 + mask=0）。默认 image_keys 可能含全部特征名——强制前 2。
print("[recon] image_features:", pol._image_features, "image_keys:", pol.image_keys)
pol.image_keys = tuple(pol._image_features[:2])
pol._empty_features = tuple(pol._image_features[2:])
print("[recon] effective image_keys:", pol.image_keys, "empty:", pol._empty_features)

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
        else:
            # ModelOutput（language_model/expert 的 forward 返回）——抓
            # last_hidden_state + past_key_values（DynamicCache 兼容）
            lh = getattr(out, "last_hidden_state", None)
            if lh is not None:
                entry["last_hidden"] = lh.detach().clone()
            pkv = getattr(out, "past_key_values", None)
            if pkv is not None and hasattr(pkv, "key_cache"):
                entry["kc"] = [k.detach().clone() for k in pkv.key_cache]
                entry["vc"] = [v.detach().clone() for v in pkv.value_cache]
        cap[name] = entry
    return f


targets = {}
for name, mod in model.named_modules():
    low = name.lower()
    if ("vision_tower" in low and "vision_model" not in low) or mod.__class__.__name__ == "SiglipVisionModel":
        targets.setdefault("vision_tower", name)
    if low.endswith("embed_tokens"):
        targets.setdefault("embed_tokens", name)
    # projector：链上的 linear，其输出 = probe 的 vision_out [768,2048]
    if "multi_modal_projector" in low and isinstance(mod, torch.nn.Linear):
        targets.setdefault("projector", name)
    # x0：paligemma.language_model.forward 是【直接 .forward() 调用】（绕过
    # __call__，模块 hook 不触发）。模块树真路径带 .model.（embed_tokens
    # 实证：paligemma.model.language_model.embed_tokens）；层内 input_layernorm
    # 经 __call__ 调用（modeling_gemma L358）——挂 layer0 抓首个 hidden_states
    if low.endswith("paligemma.model.language_model.layers.0.input_layernorm"):
        targets.setdefault("x0_ln0", name)
if len(targets) < 2:  # 没命中就打全量模块名，下次修
    print("[recon] MISS targets:", targets)
    for name, _ in model.named_modules():
        print("[mod]", name)
handles = []
for key, name in targets.items():
    handles.append(model.get_submodule(name).register_forward_hook(make_hook(key), with_kwargs=True))
print("[recon] hooks:", targets)


# 图内中间量 pre-hook（GE 图调试对拍）：m0 = 层0 o_proj 输入（attention
# 合并输出，o_proj 前）；h1 = layers[1].input_layernorm 输入（层0 完整输出）
def mk_pre(name):
    def f(mod, args, kwargs):
        if name in cap:
            return
        if args and torch.is_tensor(args[0]):
            cap[name] = {"in": args[0].detach().clone()}
    return f


lm0 = model.paligemma_with_expert.paligemma.model.language_model
handles.append(lm0.layers[0].self_attn.o_proj.register_forward_pre_hook(mk_pre("m0"), with_kwargs=True))
handles.append(lm0.layers[1].input_layernorm.register_forward_pre_hook(mk_pre("h1"), with_kwargs=True))
# q/k/v 投影输出（infer 侧真值——与手工重放/引擎对拍，裁决 m0 35% 分岔的输入差）
handles.append(lm0.layers[0].self_attn.q_proj.register_forward_hook(make_hook("q0i"), with_kwargs=True))
handles.append(lm0.layers[0].self_attn.k_proj.register_forward_hook(make_hook("k0i"), with_kwargs=True))
handles.append(lm0.layers[0].self_attn.v_proj.register_forward_hook(make_hook("v0i"), with_kwargs=True))


# 确定性合成帧（对拍只要求两路同张量；真 LIBERO 渲染非必需）
rng = np.random.default_rng(20260920)
obs = {
    pol.image_keys[0]: rng.integers(0, 256, (256, 256, 3), dtype=np.uint8),
    pol.image_keys[1]: rng.integers(0, 256, (256, 256, 3), dtype=np.uint8),
    pol.state_key: rng.uniform(-1, 1, 8).astype(np.float32),
    # 任务文本填满：tokenizer pad 到 max_length=200（截断超出）——重复短语
    # 让 200 个全为真 token、无 pad（引擎 prefix 无 attention mask，pad 不能进）
    "prompt": ("pick up the black bowl and place it on the stove. " * 30),
}
noise = rng.standard_normal((50, 32)).astype(np.float32)

res = pol.infer(obs, noise=noise)
for h in handles:
    h.remove()

print("[recon] captured:", {k: {i: tuple(t.shape) for i, t in v.items()} for k, v in cap.items()})
norm_actions = res["normalized_actions"]
print("[recon] normalized_actions", norm_actions.shape, "|max|", float(np.abs(norm_actions).max()))

# patches：vision_tower 输入 = SigLIP 归一化后的 pixel_values → unfold
pv = cap["vision_tower"][0].float().cpu()
print("[recon] pixel_values", tuple(pv.shape), "min/max", float(pv.min()), float(pv.max()))
import torch.nn.functional as F  # noqa: E402

flat = pv.reshape(-1, 3, pv.shape[-2], pv.shape[-1])
u = F.unfold(flat, kernel_size=14, stride=14)               # [V, 588, 256]
patches = u.permute(0, 2, 1).reshape(-1, u.shape[1]).numpy()  # 行 (c,kh,kw)
print("[recon] patches", patches.shape)

ids = cap["embed_tokens"][0].reshape(-1).cpu()
from collections import Counter  # noqa: E402

cnt = Counter(ids.tolist())
print("[recon] input_ids len", ids.numel(), "head", ids[:24].tolist())
print("[recon] top id counts:", cnt.most_common(3))  # 占比过高 = 仍有 pad

from safetensors.numpy import save_file  # noqa: E402

os.makedirs(os.path.dirname(OUT), exist_ok=True)
golden = {
    "patches": patches.astype(np.float32),
    "token_ids": ids.numpy().astype(np.float32),
    "noise": noise,
    "actions": np.asarray(norm_actions, dtype=np.float32),
}
# 中间量（probe 段边界 bisect 用）：projector 输出 = vision_out [768,2048]
golden["vision_out"] = cap["projector"]["out"].float().reshape(-1, 2048).cpu().numpy()
print("[recon] vision_out", golden["vision_out"].shape)

# ---- x0（layer0 input_layernorm 首参 = prefix hidden 进层前 = x0）----
if "x0_ln0" in cap:
    x0_t = cap["x0_ln0"][0].detach()
else:
    # 回退：按引擎同式组装（embed_tokens hook 输出 ×√2048 ‖ vision_out）
    print("[recon] WARN x0_ln0 未命中，用 embed_tokens+vision_out 组装回退")
    lang = cap["embed_tokens"]["out"][0]
    x0_t = torch.cat(
        [cap["projector"]["out"].reshape(-1, 2048)[:768].to(lang.dtype),
         (lang.double() * 2048 ** 0.5).to(lang.dtype)], 0
    ).unsqueeze(0)
print("[recon] x0", tuple(x0_t.shape), "dtype", x0_t.dtype)
golden["x0"] = x0_t.float().reshape(-1, 2048).cpu().numpy()
golden["m0"] = cap["m0"]["in"][0].float().reshape(-1, 2048).cpu().numpy()
golden["h1"] = cap["h1"]["in"][0].float().reshape(-1, 2048).cpu().numpy()
for k, key in (("q0i", "q0i"), ("k0i", "k0i"), ("v0i", "v0i")):
    golden[key] = cap[k]["out"][0].float().reshape(-1, cap[k]["out"].shape[-1]).cpu().numpy()
print("[recon] m0", golden["m0"].shape, "h1", golden["h1"].shape,
      "q0i", golden["q0i"].shape, "k0i", golden["k0i"].shape)


# ---- prefix kv：手工重放 prefix pass（同 x0/同权重/全开 4D 零 mask——与
# sample_actions 内部 use_cache=True 路径数学等价，拿全部层 k/v cache）。
# ⚠ GemmaModel.forward 对 attention_mask=None 会 create_causal_mask（因果）
# ——必须显式传 4D 全零（= _prepare_attention_masks_4d(全 True 2D)）----
pwe = model.paligemma_with_expert
dev = x0_t.device
P = x0_t.shape[1]
with torch.no_grad():
    pos = torch.arange(P, device=dev).unsqueeze(0)
    # _prepare_attention_masks_4d 吃 3D [B,Q,K]（make_att_2d_masks 同形）
    pmask = model._prepare_attention_masks_4d(torch.ones(1, P, P, dtype=torch.bool, device=dev))
    pv_out = pwe.paligemma.language_model.forward(
        inputs_embeds=x0_t.to(torch.float16),
        attention_mask=pmask,
        position_ids=pos,
        past_key_values=None,
        use_cache=True,
        adarms_cond=None,
    )
pkv = pv_out.past_key_values
if hasattr(pkv, "key_cache"):
    kcs, vcs = pkv.key_cache, pkv.value_cache
else:
    kcs = [kv[0] for kv in pkv]
    vcs = [kv[1] for kv in pkv]
print("[recon] prefix cache layers:", len(kcs), "k0", tuple(kcs[0].shape))
for i, (k, v) in enumerate(zip(kcs, vcs)):
    golden[f"kvk_l{i}"] = k.float().reshape(-1, k.shape[-1]).cpu().numpy()
    golden[f"kvv_l{i}"] = v.float().reshape(-1, v.shape[-1]).cpu().numpy()
golden["prefix_hidden"] = pv_out.last_hidden_state.float().reshape(-1, 2048).cpu().numpy()

# ---- flow step0：手工重放 denoise_step（t=1.0, x_t=noise, dt=-0.1）----
chunk = model.config.chunk_size
dt = -1.0 / model.config.num_inference_steps
x_t = torch.from_numpy(noise).to(dev, torch.float16).unsqueeze(0)  # [1,50,32]
with torch.no_grad():
    time0 = torch.tensor([1.0], dtype=torch.float16, device=dev)
    suffix_embs, suffix_pad, suffix_att, cond = model.embed_suffix(x_t, time0)
    suffix_len = suffix_pad.shape[1]
    prefix_pad = torch.ones(1, P, dtype=torch.bool, device=dev)
    from lerobot.policies.pi05.modeling_pi05 import make_att_2d_masks  # noqa: E402

    pre2d = prefix_pad[:, None, :].expand(1, suffix_len, P)
    suf2d = make_att_2d_masks(suffix_pad, suffix_att)
    full = torch.cat([pre2d, suf2d], dim=2)
    mask4d = model._prepare_attention_masks_4d(full)
    pwe.paligemma.language_model.config._attn_implementation = "eager"
    pos_s = torch.sum(prefix_pad, dim=-1)[:, None] + torch.cumsum(suffix_pad, dim=1) - 1
    outs, _ = pwe.forward(
        attention_mask=mask4d,
        position_ids=pos_s,
        past_key_values=pkv,
        inputs_embeds=[None, suffix_embs.to(torch.float16)],
        use_cache=False,
        adarms_cond=[None, cond],
    )
    v_t = model.action_out_proj(outs[1][:, -chunk:])
    x1 = x_t + dt * v_t
golden["step0_x1"] = x1.float().reshape(-1, x1.shape[-1]).cpu().numpy()
print("[recon] kvk_l0", golden["kvk_l0"].shape, "prefix_hidden", golden["prefix_hidden"].shape,
      "step0_x1", golden["step0_x1"].shape, "|max|", float(np.abs(golden["step0_x1"]).max()))
save_file(golden, OUT)
print("saved:", OUT)
