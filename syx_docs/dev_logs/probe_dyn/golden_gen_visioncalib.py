#!/usr/bin/env python3
"""golden_gen_visioncalib.py — I10 校准数据面：vision 段真激活（多帧包络 + sim 采样）。

对齐 golden_gen_v3calib.py 的机制（replay_t{0..3} 真帧、fold 逆变换、
embed_prefix 驱动），差异 = hook 挂 SigLIP 塔（27 层 × q/k/v/out/fc1/fc2
+ multi_modal_projector 输入）而非 prefix/flow。空视图 -1 pad 行在
patches 里天然存在（768 行 = 3 视图）→ 包络自动覆盖。

产物 /data/apxinf/golden/calib_vision_v1.safetensors：
  venv_{site}   per-channel amax 跨帧包络 [C]
  simv_{tag}_{site}  指定帧激活采样（行抽样 fp16）
  meta_nframes
跑法（宿主）：
  docker exec -e ASCEND_RT_VISIBLE_DEVICES=4 apxinf_npu bash -c \
    'PYTHONPATH=/data/apxinf/robo_src:$PYTHONPATH exec python3 \
     /data/apxinf/pyo3_check/golden_gen_visioncalib.py'
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

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
OUT = os.environ.get("CALIB_OUT", "/data/apxinf/golden/calib_vision_v1.safetensors")
REPLAY = os.environ.get("REPLAY_FMT", "/data/apxinf/replay/replay_t{}.safetensors")
FRAME_EVERY = int(os.environ.get("FRAME_EVERY", "4"))
ROW_EVERY = 8  # sim 行抽样
# 采样帧（任务,帧序→tag）；帧序须落 FRAME_EVERY 网格
SIM_FRAMES = {(0, 0): "a", (2, 32): "b"}

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
pwe = model.paligemma_with_expert
vt = pwe.paligemma.vision_tower
# 绕实例级 torchair fullgraph 编译（embed_image 被包——hook 进不了图）；
# v3 同款手法：del 实例属性 → 类级 eager 方法复现
for attr in ("embed_image", "forward"):
    try:
        delattr(pwe, attr)
    except AttributeError:
        pass
try:
    vt.config._attn_implementation = "eager"
except Exception:
    pass
nlayers = len(vt.vision_model.encoder.layers)
print(f"vision tower layers={nlayers}", flush=True)

VSITES = {
    "self_attn.q_proj": "vq",
    "self_attn.k_proj": "vk",
    "self_attn.v_proj": "vv",
    "self_attn.out_proj": "vo",
    "mlp.fc1": "vfc1",
    "mlp.fc2": "vfc2",
}

stage = {}
simstore = {}
ctx = {"tag": ""}


def _hook(name, keep_sim):
    def f(mod, args, kwargs):
        if not args or not torch.is_tensor(args[0]):
            return
        t = args[0].detach()
        stage[name] = t.float().abs().amax(dim=tuple(range(t.dim() - 1))).cpu()
        if keep_sim and ctx["tag"]:
            simstore[f"simv_{ctx['tag']}_{name}"] = (
                t[::ROW_EVERY].to(torch.float16).cpu().numpy()
            )
    return f


hooks = []
for i in range(nlayers):
    layer = vt.vision_model.encoder.layers[i]
    for suf, tag in VSITES.items():
        mod = layer
        for part in suf.split("."):
            mod = getattr(mod, part)
        hooks.append(mod.register_forward_pre_hook(_hook(f"{tag}_l{i}", True), with_kwargs=True))
# mm projector 输入（vision 塔输出 [768, 1152]）；wrapper 包 linear 或裸 Linear
mmproj = getattr(pwe.paligemma, "multi_modal_projector", None)
if mmproj is not None:
    kids = list(mmproj.named_children())
    target = kids[0][1] if kids else mmproj
    hooks.append(target.register_forward_pre_hook(_hook("vm_l0", True), with_kwargs=True))

venv = {}
nframes = 0
for task in range(4):
    path = REPLAY.format(task)
    d = load_file(path)
    n = len([k for k in d if k.startswith("patches_")])
    print(f"[t{task}] {n} 帧", flush=True)
    for fi in range(0, n, FRAME_EVERY):
        patches = d[f"patches_{fi}"]
        ids_real = d[f"token_ids_{fi}"].astype(np.int64)
        tag = SIM_FRAMES.get((task, fi), "")
        ctx["tag"] = tag
        u = torch.from_numpy(patches).float().reshape(3, 256, 588).permute(0, 2, 1)
        px = F.fold(u, output_size=(224, 224), kernel_size=14, stride=14)
        images = [px[v:v + 1].to(torch.float16).npu() for v in range(3)]
        L = int(np.count_nonzero(ids_real))
        ids = torch.from_numpy(ids_real[:L]).unsqueeze(0).npu()
        masks = torch.ones_like(ids)
        imgm = [torch.ones(1, dtype=torch.bool, device=ids.device)] * 3
        with torch.no_grad():
            embs, _, _ = model.embed_prefix(images, imgm, ids, masks)
        if nframes == 0:
            x0 = embs[0]
            print(
                f"[smoke] x0 {tuple(x0.shape)} |max|={float(x0.abs().max()):.2f} "
                f"vis512|max|={float(x0[:512].abs().max()):.2f} L={L}",
                flush=True,
            )
        for site, m in stage.items():
            mv = m.numpy()
            venv[site] = np.maximum(venv[site], mv) if site in venv else mv
        stage.clear()
        nframes += 1
        if nframes % 40 == 0:
            print(f"[prog] {nframes} 帧（sim keys={len(simstore)}）", flush=True)

for h in hooks:
    h.remove()

out = {f"venv_{k}": v.astype(np.float32) for k, v in venv.items()}
out.update(simstore)
out["meta_nframes"] = np.array([float(nframes)], dtype=np.float32)
save_file(out, OUT)
print(f"saved {OUT}: venv={len(venv)} sim={len(simstore)} frames={nframes}")
for site in ("venv_vq_l0", "venv_vo_l0", "venv_vfc1_l0", "venv_vfc2_l0", "venv_vm_l0"):
    if site in out:
        v = out[site]
        print(f"  {site}: C={v.shape[0]} max={v.max():.3f} med={np.median(v):.4f} min={v.min():.3g}")
