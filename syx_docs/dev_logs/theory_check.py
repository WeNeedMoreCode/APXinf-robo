"""theory_check.py — 「infer ≡ 712 可见 token 全开 + arange」等价性证明

根因链：golden_gen 强制 2 视图 → empty_camera 走 missing 路径（-1 pad 图
进 SigLIP 但 pad_mask=0）→ pad_2d 遮蔽 + cumsum 位置塌缩。数学推论：
pad 列 softmax 贡献恰 0、visible 位置恰 arange(712) ⇒ infer 语义等价于
712 token（vision 前 512 行 + lang 200 行）全开 attention + arange(712)。
验证：replay-712 的 m0 行 vs m0_gold（infer 真值）对应行 ≈ f16 噪声。
"""
import numpy as np
import torch
import torch_npu  # noqa: F401
from safetensors.numpy import load_file

torch_npu.npu.set_compile_mode(jit_compile=False)
import os
import sys

sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402

pol = NpuTorchPi05Policy("/data/apxinf/weights/pi05_libero_finetuned")
model = pol.policy.model
pwe = model.paligemma_with_expert
lm = pwe.paligemma.model.language_model
pwe.paligemma.language_model.config._attn_implementation = "eager"

G = load_file("/data/apxinf/golden/frame0.safetensors")
m0_gold = G["m0"].astype(np.float64)
h1_gold = G["h1"].astype(np.float64)
x0 = G["x0"].astype(np.float64)

# 可见 prefix：vision 前 512（2 真实视图）+ lang 200
x0_vis = np.concatenate([x0[:512], x0[768:]], 0)  # [712, 2048]
Pv = x0_vis.shape[0]
cap = {}


def pre(mod, args, kwargs):
    cap.setdefault("m0", args[0].detach().clone())


def pre_h1(mod, args, kwargs):
    cap.setdefault("h1", args[0].detach().clone())


h = [lm.layers[0].self_attn.o_proj.register_forward_pre_hook(pre, with_kwargs=True),
     lm.layers[1].input_layernorm.register_forward_pre_hook(pre_h1, with_kwargs=True)]
with torch.no_grad():
    xt = torch.from_numpy(x0_vis).to(torch.float16).unsqueeze(0).npu()
    pos = torch.arange(Pv, device=xt.device).unsqueeze(0)
    pmask = model._prepare_attention_masks_4d(torch.ones(1, Pv, Pv, dtype=torch.bool, device=xt.device))
    out = pwe.paligemma.language_model.forward(
        inputs_embeds=xt, attention_mask=pmask, position_ids=pos,
        past_key_values=None, use_cache=True, adarms_cond=None)
for hh in h:
    hh.remove()

m0_712 = cap["m0"][0].float().cpu().numpy().astype(np.float64).reshape(-1, 2048)
h1_712 = cap["h1"][0].float().cpu().numpy().astype(np.float64).reshape(-1, 2048)
# 对应行：712 的 [0..512) → gold [0..512)；712 的 [512..712) → gold [768..968)
idx_g = np.concatenate([np.arange(512), np.arange(768, 968)])
rel = lambda a, b: np.abs(a - b).max() / max(np.abs(b).max(), 1e-9) * 100
print(f"[m0] replay712 vs m0_gold 对应行: {rel(m0_712, m0_gold[idx_g]):.3f}%")
print(f"[h1] replay712 vs h1_gold 对应行: {rel(h1_712, h1_gold[idx_g]):.3f}%")
d = np.abs(m0_712 - m0_gold[idx_g]).max(-1) / np.abs(m0_gold).max() * 100
print(f"[m0] 分块行偏差: 前 512(真视图) {d[:512].mean():.3f}%  后 200(文本) {d[512:].mean():.3f}%")
print("\n[判读] ≈0.x% ⇒ 等价性成立，引擎修法 = x0 丢弃 empty view 行（968→712），全开+arange 语义不变。")
