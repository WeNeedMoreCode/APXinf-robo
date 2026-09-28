#!/usr/bin/env python3
"""smooth_calib_v1.npz（torch 域）→ int8 消费 safetensors（v2：g 回图）。

v1 教训（2026-09-28 取证）：纯引擎域 s_eff = s_npz/(1+g) 在 L00 爆炸
（input_layernorm 有 193 通道 (1+g)≈0、26 个负值——s_eff ±e7，f16 行
不可表示；这些通道贡献占 9-31% 不可钳）。

v2 方案（g 回图）：int8 层的 AddRmsNorm gamma 直接用 (1+g) 真值（引擎
f16 路径用 ones+权重折叠——两路在层内语义恒等，残差流两域本就相同），
激活侧回到 torch 域：
  norm 输出 h = rms(x)·(1+g) = torch 激活；op 行输入 = s_npz（f16 安全）
  权重侧不变：w'·s_eff = w·(1+g)·s_npz/(1+g) = w·s_npz（npz bit 级锚点）
组内留在 f16 的成员（GEB_INT8_PROJS 子集）由 Rust 除回 fold。

键：
  prefix/L{nn}/{proj}/s_eff   f32[k]  权重侧吸收因子（= s_npz/(1+g)，仅 f32 域用）
  prefix/L{nn}/{proj}/smooth  f32[k]  算子 smooth_scale 行（= 1/s_npz！算子是
                                      乘法约定——NSM=3 probe 定案，2026-09-28）
  prefix/L{nn}/{proj}/inv     f32[k]  回退 Mul 行（= 1/s_npz，与 smooth 同值）
  prefix/L{nn}/g1             f32[2048] 1+input_layernorm（q/k/v 组 norm 回 torch 域）
  prefix/L{nn}/g2             f32[2048] 1+post_attention_layernorm（gate/up 组）

⚠ 2026-09-28 事故记录：v2 重写时误删 invert 分支，--invert 被静默忽略，
smooth 落成 s_npz 正向值 → 乘法约定算子拿到 x·s @ w·s = s² 放大 ~1300×
（kvk_l0 max_diff 13379 的根因）。现在 smooth 恒为 1/s_npz 并打印实值。
"""
import numpy as np
import torch
from safetensors import safe_open
from safetensors.torch import save_file

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
NPZ = "/data/apxinf/pyo3_check/smooth_calib_v1.npz"
OUT = "/data/apxinf/pyo3_check/smooth_calib_v1_engine.safetensors"
ROOT = "model.paligemma_with_expert.paligemma.model.language_model"
FOLD_SRC = {
    "q": "input_layernorm",
    "k": "input_layernorm",
    "v": "input_layernorm",
    "gate": "post_attention_layernorm",
    "up": "post_attention_layernorm",
    "o": None,
    "down": None,
}


def main():
    npz = np.load(NPZ)
    out = {}
    n_mat = 0
    s_min, s_max = 1e30, 0.0
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for key in sorted(npz.files):
            if not key.startswith("prefix/"):
                continue  # 本轮只做 prefix（flow 不碰）
            _, lay, proj = key.split("/")
            lay_n = int(lay[1:])
            s_npz = npz[key]
            fold = np.ones(len(s_npz), dtype=np.float32)
            src = FOLD_SRC[proj]
            if src is not None:
                g = f.get_tensor(f"{ROOT}.layers.{lay_n}.{src}.weight").float().numpy()
                fold = (1.0 + g).astype(np.float32)
            assert len(s_npz) == len(fold), (key, len(s_npz), len(fold))
            s_eff = (s_npz / fold).astype(np.float32)  # 仅 f32 权重侧（爆值无害）
            inv = (1.0 / s_npz).astype(np.float32)
            out[f"{key}/s_eff"] = torch.from_numpy(s_eff.copy())
            out[f"{key}/smooth"] = torch.from_numpy(inv.copy())  # 乘法约定：1/s
            out[f"{key}/inv"] = torch.from_numpy(inv.copy())
            n_mat += 1
            s_min = min(s_min, float(inv.min()))
            s_max = max(s_max, float(inv.max()))
        # 组 norm 真值（g 回图）
        for layer in range(18):
            for src, tag in (("input_layernorm", "g1"), ("post_attention_layernorm", "g2")):
                g = f.get_tensor(f"{ROOT}.layers.{layer}.{src}.weight").float().numpy()
                out[f"prefix/L{layer:02}/{tag}"] = torch.from_numpy((1.0 + g).astype(np.float32))
    save_file(out, OUT)
    print(f"写出 {OUT}：{n_mat} 矩阵 ×3 键 + 18 层 ×g1/g2")
    print(f"smooth 行（=1/s_npz，乘法约定）∈ [{s_min:.4g},{s_max:.4g}]")
    # f16 行安全性：smooth 须在 [6e-5, 65504] 正规域（负号无害）
    assert s_min > 6e-5, "smooth 下溢 f16 次正规域——行精度塌缩，须回查包络"
    assert s_max < 65504, "smooth 上溢 f16"


if __name__ == "__main__":
    main()
