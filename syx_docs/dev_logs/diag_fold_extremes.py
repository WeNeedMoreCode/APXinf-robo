#!/usr/bin/env python3
"""s_eff 极值取证：(1+g) 分布 + |s_eff|>65504（f16 上限）通道数及其贡献。

问题：s_eff = s_npz/(1+g) 出现 ±e7（f16 smooth 行不可表示）。机制假设：
个别通道 (1+g)≈0（torch 域激活被强压制 → a_k 小 → s_npz 小），除以近零
fold 后爆炸。判据：若极值通道的 torch 域缩放后激活 |x/s_npz| 本就极小，
则 f16 行饱和/截断这些通道是无害的（贡献 ~0）；若贡献可观则须重校准。
"""
import numpy as np
import torch
from safetensors import safe_open

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
GOLDEN = "/data/apxinf/golden/frame0_v3.safetensors"
NPZ = "/data/apxinf/pyo3_check/smooth_calib_v1.npz"
ROOT = "model.paligemma_with_expert.paligemma.model.language_model"


def main():
    npz = np.load(NPZ)
    # 激活包络（与 calib 同式）
    with safe_open(GOLDEN, framework="pt", device="cpu") as f:
        chans = []
        for key in ("x0_vis", "res0", "m0_vis", "prefix_hidden_vis"):
            v = f.get_tensor(key).float().abs().amax(dim=0).numpy()
            chans.append((v.shape[0], v))
        n_max = max(n for n, _ in chans)
        a_k = np.zeros(n_max, dtype=np.float32)
        for n, v in chans:
            a_k[:n] = np.maximum(a_k[:n], v)

    print(f"{'层':>4} {'fold min':>10} {'fold max':>10} {'|f|<1e-3':>8} {'|f|<1e-5':>8} {'负值':>5} | s_eff>65504 (q,gate)")
    worst = []
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for layer in range(18):
            stats = []
            for src, projs in (("input_layernorm", ("q", "k", "v")),
                               ("post_attention_layernorm", ("gate", "up"))):
                g = f.get_tensor(f"{ROOT}.layers.{layer}.{src}.weight").float().numpy()
                fold = 1.0 + g
                n_small = int(np.sum(np.abs(fold) < 1e-3))
                n_tiny = int(np.sum(np.abs(fold) < 1e-5))
                n_neg = int(np.sum(fold < 0))
                stats.append((fold.min(), fold.max(), n_small, n_tiny, n_neg, fold, projs))
            line = f"L{layer:02d}"
            for fold_min, fold_max, n_small, n_tiny, n_neg, fold, projs in stats:
                # 每投影的 s_eff 溢出计数
                ovr = []
                for proj in projs:
                    s = npz[f"prefix/L{layer:02d}/{proj}"]
                    s_eff = s / fold[: len(s)]
                    ovr.append(int(np.sum(np.abs(s_eff) > 65504)))
                line += (f" | {fold_min:>9.2e} {fold_max:>9.2e} {n_small:>8} {n_tiny:>8} {n_neg:>5}"
                         f" | q:{ovr[0] if 'q' in projs else ovr[0]} gate:{ovr[-1]}")
            print(line)
            worst.extend(stats)

        # 最坏矩阵的极值通道贡献：|x/s| 用包络近似（a_k/s_k = 缩放后包络）
        layer, src, proj = 0, "input_layernorm", "q"
        g = f.get_tensor(f"{ROOT}.layers.{layer}.{src}.weight").float().numpy()
        fold = 1.0 + g
        s = npz[f"prefix/L{layer:02d}/{proj}"]
        s_eff = s / fold[: len(s)]
        scaled_env = a_k[: len(s)] / s  # torch 域缩放后激活包络
        bad = np.abs(s_eff) > 65504
        print(f"\nL00/{proj}: |s_eff|>65504 通道 {int(bad.sum())}/{len(s)}")
        if bad.any():
            env_all = a_k[: len(s)] / s
            print(f"  这些通道 torch 域缩放后包络 |x/s|: max={env_all[bad].max():.3e}"
                  f"（全库缩放后包络 max={env_all.max():.1f}）→ 贡献占比 {env_all[bad].max() / env_all.max() * 100:.3f}%")
        # 全库扫描：极值通道的贡献上界
        contrib_bad = 0.0
        contrib_all = 0.0
        n_bad_tot = 0
        for layer in range(18):
            for src, projs in (("input_layernorm", ("q", "k", "v")),
                               ("post_attention_layernorm", ("gate", "up"))):
                g = f.get_tensor(f"{ROOT}.layers.{layer}.{src}.weight").float().numpy()
                fold = 1.0 + g
                for proj in projs:
                    s = npz[f"prefix/L{layer:02d}/{proj}"]
                    s_eff = s / fold[: len(s)]
                    scaled = a_k[: len(s)] / s
                    bad = np.abs(s_eff) > 65504
                    n_bad_tot += int(bad.sum())
                    if bad.any():
                        contrib_bad = max(contrib_bad, float(scaled[bad].max()))
                    contrib_all = max(contrib_all, float(scaled.max()))
        print(f"\n全库：极值通道 {n_bad_tot} 个；其缩放后包络最大 {contrib_bad:.3e}"
              f" vs 全库缩放后包络最大 {contrib_all:.1f}（占比 {contrib_bad / contrib_all * 100:.4f}%）")


if __name__ == "__main__":
    main()
