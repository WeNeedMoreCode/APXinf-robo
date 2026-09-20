"""attn_impl_probe.py — eager vs sdpa 世界裁决

golden v2 的键混世界：m0/h1/q0i 来自 infer（sample_actions 先设 eager），
kvk cache 来自手工重放（未设 eager → sdpa）。本脚本同一 x0 分别跑两种
implementation 抓层 0 o_proj 输入（m0），对号入座：
  m0_eager ≈ m0_gold 且 m0_sdpa ≈ f64 教科书 ⇒ 世界分裂实锤。
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
lm = pwe.paligemma.model.language_model  # GemmaModel 真体

G = load_file("/data/apxinf/golden/frame0.safetensors")
m0_gold = G["m0"].astype(np.float64)
P = G["x0"].shape[0]
x0 = torch.from_numpy(G["x0"]).to(torch.float16).unsqueeze(0).npu()

rel = lambda a, b: np.abs(a - b).max() / max(np.abs(b).max(), 1e-9) * 100
NIMG = 768


def run_prefix(impl):
    pwe.paligemma.language_model.config._attn_implementation = impl
    lm.config._attn_implementation = impl
    cap = {}

    def pre(mod, args, kwargs):
        cap.setdefault("m0", args[0].detach().clone())

    h = lm.layers[0].self_attn.o_proj.register_forward_pre_hook(pre, with_kwargs=True)
    with torch.no_grad():
        pos = torch.arange(P, device=x0.device).unsqueeze(0)
        pmask = model._prepare_attention_masks_4d(torch.ones(1, P, P, dtype=torch.bool, device=x0.device))
        out = pwe.paligemma.language_model.forward(
            inputs_embeds=x0, attention_mask=pmask, position_ids=pos,
            past_key_values=None, use_cache=True, adarms_cond=None)
    h.remove()
    m0 = cap["m0"][0].float().cpu().numpy().astype(np.float64).reshape(-1, 2048)
    k1 = out.past_key_values.key_cache[1] if hasattr(out.past_key_values, "key_cache") else out.past_key_values[1][0]
    k1 = k1.float().reshape(-1, k1.shape[-1]).cpu().numpy().astype(np.float64)
    return m0, k1


print("[init] lm.config._attn_implementation =", lm.config._attn_implementation)
m0_eager, k1_eager = run_prefix("eager")
m0_eager2, _ = run_prefix("eager")  # 确定性对照（aclnn 非确定性量级）


def prof(tag, m):
    d = np.abs(m - m0_gold)
    row = d.max(-1) / np.abs(m0_gold).max() * 100
    print(f"[m0] {tag}: vs_gold={d.max() / np.abs(m0_gold).max() * 100:.2f}%"
          f"  行均值 img={row[:NIMG].mean():.2f}% txt={row[NIMG:].mean():.2f}%")


prof("replay-eager#1", m0_eager)
prof("replay-eager#2", m0_eager2)
print(f"[m0] replay#1 vs #2（自确定性）: {rel(m0_eager, m0_eager2):.4f}%")
print(f"[k1] replay k1 vs golden kvk_l1: {rel(k1_eager, G['kvk_l1'].astype(np.float64)):.2f}%")
print(f"[k1] replay k1 vs golden kvk_l0 位置校验——k1 shape {k1_eager.shape}")
