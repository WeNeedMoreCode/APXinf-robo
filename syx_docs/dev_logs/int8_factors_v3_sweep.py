#!/usr/bin/env python3
"""int8_factors_v3_sweep.py — 校准 v3 因子离线扫描（α × envelope，免烤先筛）。

数据面 = golden_gen_v3calib.py 的 calib_v3.safetensors（多帧包络 penv/fenv
+ 代表帧激活采样 sim_p/sim_f）。对每个候选 (envelope, α) 构造 s 集，在
真实激活上模拟引擎量化数学（per-token 动态激活量化 + per-row 权重量化，
qmd 同构），对 f32 参考算 y 误差——排名选优，写胜者 npz（convert 脚本
schema 直供：prefix/L{nn}/{proj} 与 flow/L{nn}/{proj}）。

候选空间：
  prefix: env ∈ {v2（smooth_calib_v2.npz 单帧基线，同数据同尺度对拍）,
                v3（penv 多帧包络）} × α ∈ {0.4, 0.5, 0.6}
  flow:   env ∈ {v2（smooth_calib_v2_flow.npz 单帧跨步折叠基线）,
                v3_uniform（fenv 全步 max——多帧版 v2 语义）,
                v3_late（fenv 步 5-9 max——importance 加权：末段步定义
                actions 输出）} × α ∈ {0.4, 0.5, 0.6}
sim 域（引擎数学镜像）：
  y_q = dequant(per-token-quant(X·(1/s))) @ dequant(per-row-quant(W_eff·s))
  W_eff = ckpt w，prefix 的 q/k/v 折 g1、gate/up 折 g2（loader fold 镜像；
  o/down 无 fold；flow 全无 fold——action loader 只 take）
  y_ref = X @ W_eff（f32）
flow 按 (采样帧, step∈{0,4,9}) 分组报告 per-step 误差（per-step s 因权重
静态耦合不可行——本扫描的 v3_late 即"感知"落地形态）。
产物：胜者 npz ×2 + 决策 JSON（全候选表）。
"""
import json
import os

import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file

CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
CALIB = os.environ.get("CALIB", "/data/apxinf/golden/calib_v3.safetensors")
V2_P = "/data/apxinf/pyo3_check/smooth_calib_v2.npz"
V2_F = "/data/apxinf/pyo3_check/smooth_calib_v2_flow.npz"
# v3o = 已产出的 v3 object 谱系因子（α 烤死，作为固定基线候选）——
# spatial 跑法下即 transfer 判定对照：object 因子在 spatial 激活上的误差
V3O_P = os.environ.get("V3O_P", "/data/apxinf/pyo3_check/smooth_calib_v3.npz")
V3O_F = os.environ.get("V3O_F", "/data/apxinf/pyo3_check/smooth_calib_v3_flow.npz")
OUT_P = os.environ.get("OUT_P", "/data/apxinf/pyo3_check/smooth_calib_v3.npz")
OUT_F = os.environ.get("OUT_F", "/data/apxinf/pyo3_check/smooth_calib_v3_flow.npz")
OUT_JSON = os.environ.get("OUT_JSON", "/data/apxinf/pyo3_check/sweep_v3.json")
DEPTH = 18
ALPHAS = (0.4, 0.5, 0.6)
SIM_TAGS = ("a", "b", "c", "d")
FLOW_STEPS = (0, 4, 9)
MAX_ROWS = 64  # sim 行上限（per-token 量化 sim 的统计量足够，控 CPU 时长）

PROOT = "model.paligemma_with_expert.paligemma.model.language_model"
FROOT = "model.paligemma_with_expert.gemma_expert.model"
PSRC = {"q": ("nrm1", "self_attn.q_proj", "g1"), "k": ("nrm1", "self_attn.k_proj", "g1"),
        "v": ("nrm1", "self_attn.v_proj", "g1"), "o": ("m", "self_attn.o_proj", None),
        "gate": ("nrm2", "mlp.gate_proj", "g2"), "up": ("nrm2", "mlp.up_proj", "g2"),
        "down": ("act", "mlp.down_proj", None)}
FSRC = {"q": ("fq", "self_attn.q_proj"), "k": ("fq", "self_attn.k_proj"),
        "v": ("fq", "self_attn.v_proj"), "o": ("fm", "self_attn.o_proj"),
        "gate": ("fn", "mlp.gate_proj"), "up": ("fn", "mlp.up_proj"),
        "down": ("fact", "mlp.down_proj")}


def sim_err(X, Weff, s):
    """qmd 同构量化 sim：返回 (rms_rel, max_rel)。X 可为 [S,C] 或 [1,S,C]
    （dump 存原始 hook 形态）；跨序列等距抽样至 MAX_ROWS——vision/text
    行分布不同，头截断会偏采样。"""
    X = X.reshape(-1, X.shape[-1])
    step = max(1, X.shape[0] // MAX_ROWS)
    X = X[::step][:MAX_ROWS].astype(np.float32)
    a = X / s[None, :]
    t = np.maximum(np.abs(a).max(axis=1, keepdims=True), 1e-12) / 127.0
    aq = np.clip(np.round(a / t), -127, 127)
    w = Weff * s[None, :]
    sw = np.maximum(np.abs(w).max(axis=1, keepdims=True), 1e-12) / 127.0
    wq = np.clip(np.round(w / sw), -127, 127)
    y_q = (aq @ wq.T) * (t * sw.T)
    y_ref = X @ Weff.T
    d = np.abs(y_q - y_ref)
    denom = max(float(np.abs(y_ref).max()), 1e-9)
    return float(np.sqrt((d ** 2).mean()) / max(float(np.sqrt((y_ref ** 2).mean())), 1e-9)), float(d.max() / denom)


def main():
    cal = load_file(CALIB)
    # ---- 权重与 (1+g) 载入 ----
    Wp, Wf, G = {}, {}, {}
    with safe_open(CKPT, framework="pt", device="cpu") as f:
        for i in range(DEPTH):
            for proj, (_, suf, gf) in PSRC.items():
                Wp[(i, proj)] = f.get_tensor(f"{PROOT}.layers.{i}.{suf}.weight").float().numpy()
            for proj, (_, suf) in FSRC.items():
                Wf[(i, proj)] = f.get_tensor(f"{FROOT}.layers.{i}.{suf}.weight").float().numpy()
            G[(i, "g1")] = f.get_tensor(f"{PROOT}.layers.{i}.input_layernorm.weight").float().numpy()
            G[(i, "g2")] = f.get_tensor(f"{PROOT}.layers.{i}.post_attention_layernorm.weight").float().numpy()

    def Weff_p(i, proj):
        w = Wp[(i, proj)]
        gf = PSRC[proj][2]
        return w * G[(i, gf)][None, :] if gf else w

    # ---- prefix 候选 ----
    v2p = dict(np.load(V2_P))
    v3op = dict(np.load(V3O_P))  # object 谱系 v3 因子（transfer 对照/复用候选）
    report = {"prefix": {}, "flow": {}}
    print("== prefix（sim = 4 采样帧 × 126 矩阵，rms_rel 均值 / max_rel 均值）==")

    def penv_s(i, proj, alpha):
        return np.power(
            np.maximum(cal[f"penv_{PSRC[proj][0]}_l{i}"], 1e-8)
            / np.maximum(np.abs(Wp[(i, proj)]).max(axis=0), 1e-8), alpha).astype(np.float32)

    # v2/v3o 因子是单一基线（α 已烤死在生成时）——不扫 α；v3 envelope 扫
    for env_name, alpha_list in [("v2", (None,)), ("v3o", (None,)), ("v3", ALPHAS)]:
        for alpha in alpha_list:
            rms_l, max_l = [], []
            for i in range(DEPTH):
                for proj in PSRC:
                    key_site = PSRC[proj][0]
                    for t in SIM_TAGS:
                        X = cal.get(f"sim_p_{t}_{key_site}_l{i}")
                        if X is None:
                            continue
                        if env_name == "v2":
                            svec = v2p[f"prefix/L{i:02}/{proj}"]
                        elif env_name == "v3o":
                            svec = v3op[f"prefix/L{i:02}/{proj}"]
                        else:
                            svec = penv_s(i, proj, alpha)
                        r, m = sim_err(X, Weff_p(i, proj), svec)
                        rms_l.append(r)
                        max_l.append(m)
            tag = env_name if alpha is None else f"{env_name}_a{alpha}"
            report["prefix"][tag] = {"rms": float(np.mean(rms_l)), "max": float(np.mean(max_l))}
            print(f"  {tag:14s}: rms={np.mean(rms_l):.4%} max={np.mean(max_l):.4%}  (n={len(rms_l)})")

    # ---- flow 候选（per-step 分组报告）----
    v2f = dict(np.load(V2_F))
    v3of = dict(np.load(V3O_F))  # object 谱系 v3 flow 因子（transfer 对照）
    fenv_cache = {}

    def fenv_of(site, i, mode):
        key = (site, i, mode)
        if key not in fenv_cache:
            e = cal[f"fenv_{site}_l{i}"]
            fenv_cache[key] = e.max(axis=0) if mode == "uniform" else e[5:].max(axis=0)
        return fenv_cache[key]

    print("== flow（sim = 4 帧 × steps {0,4,9} × 126 矩阵；分步报告）==")
    for env_name in ("v2", "v3o", "v3_uniform", "v3_late"):
        for alpha in ALPHAS:
            per_step = {s: ([], []) for s in FLOW_STEPS}
            for i in range(DEPTH):
                for proj in FSRC:
                    site = FSRC[proj][0]
                    if env_name == "v2":
                        svec = v2f[f"flow/L{i:02}/{proj}"]
                    elif env_name == "v3o":
                        svec = v3of[f"flow/L{i:02}/{proj}"]
                    else:
                        svec = np.power(
                            np.maximum(fenv_of(site, i, "uniform" if env_name == "v3_uniform" else "late"), 1e-8)
                            / np.maximum(np.abs(Wf[(i, proj)]).max(axis=0), 1e-8), alpha).astype(np.float32)
                    for t in SIM_TAGS:
                        for st in FLOW_STEPS:
                            X = cal.get(f"sim_f_{t}_s{st}_{site}_l{i}")
                            if X is None:
                                continue
                            r, m = sim_err(X, Wf[(i, proj)], svec)
                            per_step[st][0].append(r)
                            per_step[st][1].append(m)
            tag = f"{env_name}_a{alpha}"
            wmean = float(np.mean([np.mean(per_step[s][0]) for s in FLOW_STEPS]))
            report["flow"][tag] = {
                "steps": {str(s): {"rms": float(np.mean(per_step[s][0])), "max": float(np.mean(per_step[s][1]))}
                          for s in FLOW_STEPS},
                "rms_late2x": float((np.mean(per_step[4][0]) + 2 * np.mean(per_step[9][0])) / 3),
            }
            steps_str = " ".join(f"s{s}={np.mean(per_step[s][0]):.4%}" for s in FLOW_STEPS)
            print(f"  {tag:14s}: {steps_str}  late2x={report['flow'][tag]['rms_late2x']:.4%}")

    # ---- 选优写盘（rms 主指标；flow 用 late2x）----
    best_p = min(report["prefix"], key=lambda k: report["prefix"][k]["rms"])
    best_f = min(report["flow"], key=lambda k: report["flow"][k]["rms_late2x"])
    print(f"胜者：prefix={best_p} flow={best_f}")

    def build(env_name, alpha, root, src, wmap, fenv_mode=None):
        out = {}
        fixed = None
        if env_name == "v2":
            fixed = v2p if root == "prefix" else v2f
        elif env_name == "v3o":
            fixed = v3op if root == "prefix" else v3of
        for i in range(DEPTH):
            for proj in src:
                if fixed is not None:
                    out[f"{root}/L{i:02}/{proj}"] = fixed[f"{root}/L{i:02}/{proj}"]
                else:
                    site = src[proj][0]
                    if root == "prefix":
                        a = cal[f"penv_{site}_l{i}"]
                    else:
                        a = fenv_of(site, i, fenv_mode)
                    out[f"{root}/L{i:02}/{proj}"] = np.power(
                        np.maximum(a, 1e-8) / np.maximum(np.abs(wmap[(i, proj)]).max(axis=0), 1e-8),
                        alpha).astype(np.float32)
        return out

    if best_p in ("v2", "v3o"):
        pe, palpha = best_p, None
    else:
        pe, pa = best_p.split("_a")
        palpha = float(pa)
    if best_f.split("_a")[0] in ("v2", "v3o"):
        fe = best_f.split("_a")[0]
        falpha = None
        fmode = None
    else:
        fe, fa = best_f.split("_a")
        falpha = float(fa)
        fmode = "uniform" if fe == "v3_uniform" else "late"
    np.savez(OUT_P, **build(pe, palpha, "prefix", PSRC, Wp))
    np.savez(OUT_F, **build(fe, falpha, "flow", FSRC, Wf, fenv_mode=fmode))
    with open(OUT_JSON, "w") as jf:
        json.dump({"best_prefix": best_p, "best_flow": best_f, "report": report}, jf, indent=1)
    print(f"写出 {OUT_P} / {OUT_F} / {OUT_JSON}")


if __name__ == "__main__":
    main()
