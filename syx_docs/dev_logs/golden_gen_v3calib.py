#!/usr/bin/env python3
"""golden_gen_v3calib.py — 校准 v3 数据面（多帧 prefix + flow per-step 包络 + 代表帧激活采样）。

v2 局限（2026-09-28 战报留档"多帧扩录留 v3"）：prefix 单帧、flow 单帧跨步
max 折叠包络。v3 数据面三件套（供 int8_factors_v3_sweep.py 离线扫描
α×envelope，免烤先筛）：
  1) prefix 多帧 per-channel amax 包络：replay_t{0..3} 全 160 帧（真 env
     rollout 录制资产；patches fold 逆变换 → SigLIP eager → embed_prefix →
     x0_vis → prefix replay；站点同 v2calib 全 pre-hook：nrm1/m/nrm2/act
     ×18 层，跨帧 max）
  2) flow per-step 包络：每帧 10 步 euler（recorded noise），expert 4 站点
     （fq/fm/fn/fact）per-step 分立 amax [10,C]——跨帧 max 但保留步结构
     （per-step s 因权重静态耦合不可行——int8_factors_v3_sweep 的
     importance 加权包络才是 v3 "感知"的落地形态）
  3) sim 采样：4 个指定帧激活真值（prefix 每 ROW_EVERY 行抽样 + flow
     指定步全量 [50,C]）——离线量化误差模拟原料（amax 只能拟合不能模拟）
产物 /data/apxinf/golden/calib_v3.safetensors。
跑法（apxinf_npu 容器）：
  ASCEND_RT_VISIBLE_DEVICES=3 python3 /data/apxinf/golden/golden_gen_v3calib.py
  （FRAME_EVERY=2 可减半帧数；首帧自带 smoke 断言）
"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401
import torch.nn.functional as F
from safetensors.numpy import load_file, save_file

torch_npu.npu.set_compile_mode(jit_compile=False)
sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402
from lerobot.policies.pi05.modeling_pi05 import make_att_2d_masks  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
# 谱系参数化（spatial 扩录：CALIB_OUT=.../calib_v3_spatial.safetensors
# REPLAY_FMT=.../replay_s{}.safetensors——勿覆盖 object 谱系产物）
OUT = os.environ.get("CALIB_OUT", "/data/apxinf/golden/calib_v3.safetensors")
REPLAY = os.environ.get("REPLAY_FMT", "/data/apxinf/replay/replay_t{}.safetensors")
DEPTH = 18
NSTEPS = 10
FRAME_EVERY = int(os.environ.get("FRAME_EVERY", "4"))
ROW_EVERY = 4  # prefix sim 行抽样（量化 sim 的统计量足够）
# 采样帧（任务,帧序）→ tag；帧序须落在 FRAME_EVERY 网格上（默认 4）
SIM_FRAMES = {(0, 0): "a", (1, 20): "b", (2, 32): "c", (3, 8): "d"}
SIM_FLOW_STEPS = (0, 4, 9)

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
pwe.paligemma.language_model.config._attn_implementation = "eager"
pwe.gemma_expert.model.config._attn_implementation = "eager"
try:
    del pwe.forward  # 绕 torchair 实例级编译（v2calib_flow 取证：钩子 amax 无 converter）
except AttributeError:
    pass

lm0 = pwe.paligemma.model.language_model
exp = pwe.gemma_expert.model
assert hasattr(lm0, "layers") and hasattr(exp, "layers")

PSITES = {"self_attn.q_proj": "nrm1", "self_attn.o_proj": "m",
          "mlp.gate_proj": "nrm2", "mlp.down_proj": "act"}
FSITES = {"self_attn.q_proj": "fq", "self_attn.o_proj": "fm",
          "mlp.gate_proj": "fn", "mlp.down_proj": "fact"}

# ---- hook 状态机：stage[site]=本次调用 amax；ctx 标记当前段/帧/步 ----
stage = {}
simstore = {}
ctx = {"mode": None, "tag": "", "step": -1}


def _hook(name, keep_sim):
    def f(mod, args, kwargs):
        if not args or not torch.is_tensor(args[0]):
            return
        t = args[0].detach()
        stage[name] = t.float().abs().amax(dim=tuple(range(t.dim() - 1)))
        if keep_sim and ctx["tag"]:
            if ctx["mode"] == "prefix":
                simstore[f"sim_p_{ctx['tag']}_{name}"] = t[::ROW_EVERY].to(torch.float16).cpu().numpy()
            elif ctx["mode"] == "flow" and ctx["step"] in SIM_FLOW_STEPS:
                simstore[f"sim_f_{ctx['tag']}_s{ctx['step']}_{name}"] = t.to(torch.float16).cpu().numpy()
    return f


hooks = []
for i in range(DEPTH):
    for suf, tag in PSITES.items():
        mod = lm0.layers[i]
        for part in suf.split("."):
            mod = getattr(mod, part)
        hooks.append(mod.register_forward_pre_hook(_hook(f"{tag}_l{i}", True), with_kwargs=True))
    for suf, tag in FSITES.items():
        mod = exp.layers[i]
        for part in suf.split("."):
            mod = getattr(mod, part)
        hooks.append(mod.register_forward_pre_hook(_hook(f"{tag}_l{i}", True), with_kwargs=True))

penv = {}   # prefix 跨帧包络 {site: [C]}
fenv = {}   # flow per-step 跨帧包络 {site: [10, C]}
nframes = 0

for task in range(4):
    path = REPLAY.format(task)
    d = load_file(path)
    n = len([k for k in d if k.startswith("patches_")])
    print(f"[t{task}] {n} 帧", flush=True)
    for fi in range(0, n, FRAME_EVERY):
        patches = d[f"patches_{fi}"]
        ids_real = d[f"token_ids_{fi}"].astype(np.int64)
        noise = d[f"noise_{fi}"]
        tag = SIM_FRAMES.get((task, fi), "")
        do_sim = bool(tag)
        # 1) patches fold 逆变换（k=s=14 非重叠 = 精确可逆）→ embed_prefix → x0_vis
        u = torch.from_numpy(patches).float().reshape(3, 256, 588).permute(0, 2, 1)  # [3,588,256]
        px = F.fold(u, output_size=(224, 224), kernel_size=14, stride=14)  # [3,3,224,224]
        images = [px[v:v + 1].to(torch.float16).npu() for v in range(3)]
        L = int(np.count_nonzero(ids_real))
        ids = torch.from_numpy(ids_real[:L]).unsqueeze(0).npu()
        masks = torch.ones_like(ids)
        imgm = [torch.ones(1, dtype=torch.bool, device=ids.device)] * 3
        with torch.no_grad():
            embs, _, _ = model.embed_prefix(images, imgm, ids, masks)
        x0 = embs[0]
        if nframes == 0:
            # smoke 断言：SigLIP eager 链与 frame0_v3b 的 x0_vis 同量级（重建
            # 正确性的第一道闸；逐位对拍另由 sweep 脚本的 sim 利用）
            print(f"[smoke] x0 {tuple(x0.shape)} |max|={float(x0.abs().max()):.2f} "
                  f"vis512|max|={float(x0[:512].abs().max()):.2f} L={L}", flush=True)
        x0_vis = torch.cat([x0[:512], x0[768:]], 0).unsqueeze(0)
        Pv = x0_vis.shape[1]
        # 2) prefix replay（跨帧包络收割）
        ctx.update(mode="prefix", tag=tag, step=-1)
        with torch.no_grad():
            pos = torch.arange(Pv, device=x0_vis.device).unsqueeze(0)
            pmask = model._prepare_attention_masks_4d(
                torch.ones(1, Pv, Pv, dtype=torch.bool, device=x0_vis.device))
            pv_out = pwe.paligemma.language_model.forward(
                inputs_embeds=x0_vis, attention_mask=pmask, position_ids=pos,
                past_key_values=None, use_cache=True, adarms_cond=None)
        for site, m in stage.items():
            if site.startswith(("nrm1", "m_l", "nrm2", "act")):
                mv = m.cpu().numpy()
                penv[site] = np.maximum(penv[site], mv) if site in penv else mv
        stage.clear()
        pkv = pv_out.past_key_values
        # 3) 10 步 euler（recorded noise；per-step 包络收割）
        x = torch.from_numpy(noise).to(torch.float16).unsqueeze(0).npu()
        chunk = model.config.chunk_size
        dt = -1.0 / model.config.num_inference_steps
        prefix_pad = torch.ones(1, Pv, dtype=torch.bool, device=x.device)
        ctx.update(mode="flow", tag=tag)
        with torch.no_grad():
            for s in range(NSTEPS):
                ctx["step"] = s
                t_s = torch.tensor(1.0 + s * dt, dtype=torch.float16, device=x.device).expand(1)
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
                for site, m in stage.items():
                    if site.startswith(("fq", "fm", "fn", "fact")):
                        mv = m.cpu().numpy()
                        if site not in fenv:
                            fenv[site] = np.zeros((NSTEPS, mv.shape[0]), dtype=np.float32)
                        np.maximum(fenv[site][s], mv, out=fenv[site][s])
                stage.clear()
        nframes += 1
        if nframes % 20 == 0:
            print(f"[prog] {nframes} 帧完成（sim keys={len(simstore)}）", flush=True)

for h in hooks:
    h.remove()

out = {}
for site, v in penv.items():
    out[f"penv_{site}"] = v.astype(np.float32)
for site, v in fenv.items():
    out[f"fenv_{site}"] = v.astype(np.float32)
out.update(simstore)
out["meta_nframes"] = np.array([float(nframes)], dtype=np.float32)
save_file(out, OUT)
print(f"saved {OUT}: penv={len(penv)} fenv={len(fenv)} sim={len(simstore)} frames={nframes}")
for site in ("penv_nrm1_l0", "penv_act_l17", "fenv_fq_l0", "fenv_fact_l17"):
    v = out[site]
    print(f"  {site}: shape={v.shape} max={v.max():.2f} min={v.min():.5g}")
