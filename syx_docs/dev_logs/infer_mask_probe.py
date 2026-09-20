"""infer_mask_probe.py — 抓 infer 实际传入 decoder layer 的 mask/position_ids

replay-eager 完美自确定且逐位复现 kvk，但 m0_gold（infer 抓）偏 replay 35%
（图像行 14.6%、文本行 2.2%）⇒ infer 的 attention 输入必有结构差异。层是
__call__ 调用（hook 可触发），直接记录第一层收到的 attention_mask /
position_ids，与 replay 的（全零加性 mask / arange）对比。
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
lm = model.paligemma_with_expert.paligemma.model.language_model

G = load_file("/data/apxinf/golden/frame0.safetensors")
m0_gold = G["m0"].astype(np.float64)
NIMG = 768
rel = lambda a, b: np.abs(a - b).max() / max(np.abs(b).max(), 1e-9) * 100

cap = {}


def pre_layer(mod, args, kwargs):
    if "mask" in cap:
        return
    am = kwargs.get("attention_mask") if len(args) < 2 or args[1] is None else args[1]
    pid = kwargs.get("position_ids")
    cap["mask"] = None if am is None else am.detach().clone()
    cap["pos"] = None if pid is None else pid.detach().clone().cpu()
    cap["hs"] = tuple(args[0].shape)


def pre_o(mod, args, kwargs):
    cap.setdefault("m0", args[0].detach().clone())


h1 = lm.layers[0].register_forward_pre_hook(pre_layer, with_kwargs=True)
h2 = lm.layers[0].self_attn.o_proj.register_forward_pre_hook(pre_o, with_kwargs=True)

rng = np.random.default_rng(20260920)
obs = {
    pol.image_keys[0]: rng.integers(0, 256, (256, 256, 3), dtype=np.uint8),
    pol.image_keys[1]: rng.integers(0, 256, (256, 256, 3), dtype=np.uint8),
    pol.state_key: rng.uniform(-1, 1, 8).astype(np.float32),
    "prompt": ("pick up the black bowl and place it on the stove. " * 30),
}
noise = rng.standard_normal((50, 32)).astype(np.float32)
res = pol.infer(obs, noise=noise)
h1.remove()
h2.remove()

m = cap["mask"]
print("[infer] hidden_states", cap["hs"])
if m is None:
    print("[infer] attention_mask = None！（create_causal_mask 会接管）")
else:
    m = m.float().cpu().numpy()
    print(f"[infer] mask shape {m.shape} dtype —— 唯一值: {np.unique(m)[:5]}")
    NEG = m.min()
    nmask = (m < -1.0).sum()
    print(f"[infer] mask 负值条目（被遮）= {nmask} / {m.size}  ({nmask / m.size * 100:.2f}%)")
    if nmask:
        rows, cols = np.where(m < -1.0)
        print(f"[infer] 遮蔽行分布: 行号 min={rows.min()} max={rows.max()}；"
              f"img 行遮蔽数={(rows < NIMG).sum()} txt 行遮蔽数={(rows >= NIMG).sum()}")
        print(f"[infer] 遮蔽列分布: 列号 min={cols.min()} max={cols.max()}；"
              f"img 列遮蔽数={(cols < NIMG).sum()} txt 列遮蔽数={(cols >= NIMG).sum()}")
        # 遮蔽结构采样：几行的可见区间
        for r in [0, 100, 300, 512, 700, 768, 900, 967]:
            vis = np.where(m[0, 0, r] > -1.0)[0] if m.ndim == 4 else np.where(m[r] > -1.0)[0]
            if len(vis):
                print(f"  行 {r}: 可见 {len(vis)} 个，区间 [{vis.min()},{vis.max()}]")
            else:
                print(f"  行 {r}: 全遮蔽")
pos = cap["pos"]
if pos is None:
    print("[infer] position_ids = None")
else:
    p = pos.reshape(-1).numpy()
    print(f"[infer] position_ids: [{p[0]}..{p[-1]}]  非递增处 {int((np.diff(p) < 0).sum())} 个"
          f"  首值 {p[:6].tolist()}  768 处 {p[768]:.0f}")
m0_new = cap["m0"][0].float().cpu().numpy().astype(np.float64).reshape(-1, 2048)
d = np.abs(m0_new - m0_gold)
row = d.max(-1) / np.abs(m0_gold).max() * 100
print(f"[m0] 本次 infer vs m0_gold 键: {d.max() / np.abs(m0_gold).max() * 100:.4f}%"
      f"  img={row[:NIMG].mean():.3f}% txt={row[NIMG:].mean():.3f}%")
