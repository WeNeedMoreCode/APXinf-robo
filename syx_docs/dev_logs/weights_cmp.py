"""weights_cmp.py — 引擎加载路径复刻 vs torch 模型权重逐张量对拍

引擎路径（weights.rs）：safetensors 直读 → 剥 model. 前缀 → transpose_2d
（[out,in]→[in,out]）→ fold (1+w) 进 q/k/v/gate/up → f16。
torch 侧：NpuTorchPi05Policy 加载的模块参数（golden 真值源）。
任何不等 = 引擎权重加载 bug（GE/eager 共享，l0 k/v 干净 + l1+ 炸的模式）
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
from safetensors import safe_open  # noqa: E402

CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
pol = NpuTorchPi05Policy(CKPT)
lm = pol.policy.model.paligemma_with_expert.paligemma.model.language_model

with safe_open(f"{CKPT}/model.safetensors", framework="numpy") as sf:
    keys = list(sf.keys())
    print("[ckpt] total tensors:", len(keys))
    pre = "paligemma_with_expert.paligemma.model.language_model.layers.0."
    ck = {k: sf.get_tensor(k) for k in keys if k.startswith("model." + pre)}
    print("[ckpt] layer0 keys:", sorted(k[len("model.") + len(pre):] for k in ck))

L0 = lm.layers[0]


def cmp(name, engine_t, torch_t):
    a = np.asarray(engine_t, dtype=np.float64)
    b = np.asarray(torch_t, dtype=np.float64)
    if a.shape != b.shape:
        print(f"[W] {name}: SHAPE engine={a.shape} torch={b.shape}  <<<<")
        return
    rel = np.abs(a - b).max() / max(np.abs(b).max(), 1e-9)
    flag = "  <<<<" if rel > 0.01 else ""
    print(f"[W] {name}: rel={rel * 100:.3f}%{flag}")


w1 = L0.input_layernorm.weight.detach().float().cpu().numpy()
w2 = L0.post_attention_layernorm.weight.detach().float().cpu().numpy()


def eng(k):
    return ck["model." + pre + k].astype(np.float64)


# transpose_2d + fold：[out,in] → [in,out]，输入维乘 (1+w)
t2 = lambda x: x.T
for proj, w in (("q_proj", w1), ("k_proj", w1), ("v_proj", w1)):
    cmp(f"attn.{proj}(fold w1)", t2(eng(f"self_attn.{proj}.weight")) * (1.0 + w1)[:, None],
        L0.self_attn.__getattr__(proj).weight.detach().float().cpu().numpy().T * (1.0 + w1)[:, None])
cmp("attn.o_proj", t2(eng("self_attn.o_proj.weight")),
    L0.self_attn.o_proj.weight.detach().float().cpu().numpy().T)
for proj, w in (("gate_proj", w2), ("up_proj", w2)):
    cmp(f"mlp.{proj}(fold w2)", t2(eng(f"mlp.{proj}.weight")) * (1.0 + w2)[:, None],
        L0.mlp.__getattr__(proj).weight.detach().float().cpu().numpy().T * (1.0 + w2)[:, None])
cmp("mlp.down_proj", t2(eng("mlp.down_proj.weight")),
    L0.mlp.down_proj.weight.detach().float().cpu().numpy().T)
cmp("norm w1", eng("input_layernorm.weight"), w1)
cmp("norm w2", eng("post_attention_layernorm.weight"), w2)
print("[done]")
