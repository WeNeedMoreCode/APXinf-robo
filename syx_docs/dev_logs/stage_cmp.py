"""stage_cmp.py — GE 调试槽位逐级判读：槽值匹配教科书哪一级"""
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401

torch_npu.npu.set_compile_mode(jit_compile=False)
sys.path.insert(0, "/data/apxinf/robo_src")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402
from safetensors.numpy import load_file  # noqa: E402

pol = NpuTorchPi05Policy("/data/apxinf/weights/pi05_libero_finetuned")
lm = pol.policy.model.paligemma_with_expert.paligemma.model.language_model
g = load_file("/data/apxinf/golden/frame0.safetensors")
P = 968

slots = {}
for f in sorted(os.listdir("/data/apxinf")):
    if f.startswith("ge_slot") and f.endswith(".f16"):
        slots[int(f[7:-4])] = np.fromfile(f"/data/apxinf/{f}", dtype=np.float16)
print("[slots]", {k: len(v) for k, v in slots.items()})

L0, L1 = lm.layers[0], lm.layers[1]
owv = L0.self_attn.o_proj.weight.detach().float().cpu().numpy()
w2v = L0.post_attention_layernorm.weight.detach().float().cpu().numpy()
gwv = L0.mlp.gate_proj.weight.detach().float().cpu().numpy()
uwv = L0.mlp.up_proj.weight.detach().float().cpu().numpy()
dwv = L0.mlp.down_proj.weight.detach().float().cpu().numpy()
w1v1 = L1.input_layernorm.weight.detach().float().cpu().numpy()
kw1 = L1.self_attn.k_proj.weight.detach().float().cpu().numpy()
x0f = g["x0"].astype(np.float64)
m0_c = slots[4].astype(np.float64).reshape(P, 2048)  # m0 槽（教科书验证 0.5%）

stages = {}
stages["m0"] = m0_c
proj = m0_c @ owv.T
stages["proj(o_proj)"] = proj
res1 = x0f + proj
stages["res(x+attn)"] = res1
n2 = res1 / np.sqrt((res1 * res1).mean(-1, keepdims=True) + 1e-6)
stages["norm2"] = n2
gg = n2 @ (gwv * (1.0 + w2v)[None, :]).T
uu = n2 @ (uwv * (1.0 + w2v)[None, :]).T
stages["gate"] = gg
stages["up"] = uu
gact = 0.5 * gg * (1 + np.tanh(0.7978845608028654 * (gg + 0.044715 * gg ** 3)))
stages["gelu(gate)"] = gact
act = gact * uu
stages["act(gelu*up)"] = act
down = act @ dwv.T
stages["down"] = down
h1 = res1 + down
stages["h1(l0_out)"] = h1
nrm = h1 / np.sqrt((h1 * h1).mean(-1, keepdims=True) + 1e-6)
k1 = rope = None
INV16 = np.float64(np.float16(10000.0 ** (-np.arange(128) * 2.0 / 256.0)))
ANG = np.arange(P)[:, None] * INV16[None, :]
C, S = np.cos(ANG), np.sin(ANG)
k_pre = nrm @ (kw1 * (1.0 + w1v1)[None, :]).T
a, b = k_pre[:, :128], k_pre[:, 128:]
stages["k_l1(post-rope)"] = np.concatenate([a * C - b * S, b * C + a * S], -1)

for idx in sorted(slots):
    v = slots[idx].astype(np.float64)
    best, bestd = None, 1e18
    for name, st in stages.items():
        if st.size != v.size:
            continue
        d = np.abs(v.reshape(st.shape) - st).max() / max(np.abs(st).max(), 1e-9)
        if d < bestd:
            best, bestd = name, d
    print(f"[slot{idx}] size={v.size} best_match={best} rel={bestd * 100 if bestd < 1e17 else -1:.2f}%")
