"""golden_gen.py — M3 e2e golden 一帧 dump（probe GEB_E2E_GOLDEN 对拍源）

npu 容器跑法：
  ASCEND_RT_VISIBLE_DEVICES=7 python3 /data/apxinf/golden_gen.py
产物 /data/apxinf/golden/frame0.safetensors：
  patches[768,588] / token_ids[N] / noise[50,32] / actions[50,32]（全 f32）
侦察输出：pixel_values/input_ids 形状与值域（裁决视图数/padding/行序三疑点）
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
    # language_model：抓 inputs_embeds（= probe 组装的 x0 [968,2048]）
    if low.endswith("paligemma.model.language_model"):
        targets.setdefault("langmodel", name)
if len(targets) < 2:  # 没命中就打全量模块名，下次修
    print("[recon] MISS targets:", targets)
    for name, _ in model.named_modules():
        print("[mod]", name)
handles = []
for key, name in targets.items():
    handles.append(model.get_submodule(name).register_forward_hook(make_hook(key), with_kwargs=True))
print("[recon] hooks:", targets)

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
# 中间量（probe 段边界 bisect 用）：projector 输出 = vision_out [768,2048]；
# langmodel 首个张量输入（inputs_embeds/hidden_states）= x0 [968,2048]
golden["vision_out"] = cap["projector"]["out"].float().reshape(-1, 2048).cpu().numpy()
if "langmodel" in cap:
    lm_in = cap["langmodel"]
    x0_t = lm_in.get(("kw", "inputs_embeds"), lm_in.get(0))
    golden["x0"] = x0_t.float().reshape(-1, 2048).cpu().numpy()
    print("[recon] vision_out", golden["vision_out"].shape, "x0", golden["x0"].shape)
else:
    print("[recon] WARN langmodel 未命中，targets=", targets, "captured=", list(cap))
    print("[recon] vision_out", golden["vision_out"].shape)
save_file(golden, OUT)
print("saved:", OUT)
