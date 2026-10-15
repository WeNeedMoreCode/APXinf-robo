#!/usr/bin/env python
# probe_frame_breakdown_1015.py — I9 取证B：真实 _frame_inputs 链分项计时
# 跑法（宿主）: docker exec -e ASCEND_RT_VISIBLE_DEVICES=2 apxinf_npu bash -lc \
#   'PYTHONPATH=/data/apxinf/robo_src python /data/apxinf/probe_frame_breakdown_1015.py'
# 背景：tokenizer 单测仅 0.43ms（probe_tok_cost_1015），186ms 归因不成立——
# 本探针在真实 npu 宿主上把 infer() 的非模型部分逐件计时，找真凶。
import collections
import os
import sys
import time

os.environ.setdefault("APXINF_GE_SERVE_ROOT", "/data/apxinf/serve_gear")
sys.path.insert(0, "/data/apxinf/robo_src")

import numpy as np


def ms_of(f, n):
    t0 = time.perf_counter()
    for _ in range(n):
        out = f()
    return (time.perf_counter() - t0) / n * 1000.0, out


t0 = time.perf_counter()
from apxinf_robo.npu_ge import GeServePi05Policy

pol = GeServePi05Policy(
    "/data/apxinf/weights/pi05_libero_finetuned",
    tokenizer_dir="/data/apxinf/weights/paligemma-3b-pt-224",
    device="npu",
)
print(f"init_s={time.perf_counter()-t0:.1f} gear_mode={pol._gear_mode}")

import torch

tp = pol._torch_pol
print(f"image_keys={tp.image_keys} state_key={tp.state_key} prompt_key={tp.prompt_key}")

rng = np.random.default_rng(0)
obs = {}
for k in tp.image_keys:
    obs[k] = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
if tp.state_key is not None and tp._model_state_dim is not None:
    obs[tp.state_key] = rng.uniform(-0.9, 0.9, tp._model_state_dim).astype(np.float32)
obs[tp.prompt_key] = "put the black bowl on the stove element"

# -- warm（含首次 NPU 算子编译/桶握手）----------------------------------
patches, ids = pol._frame_inputs(obs)
print(f"warm L={len(ids)}")
_ = pol.infer(obs)
print("warm infer done")

N = 20
print(f"--- per-component ms (N={N}) ---")

# 1. _to_frame
m, frame = ms_of(lambda: tp._to_frame(dict(obs)), N)
print(f"to_frame_ms={m:.2f}")

# 2. pipeline 逐步（step_through 生成器，yield 间隔 = 该步耗时）
step_ms = collections.OrderedDict()
pipe = tp.preprocess


def run_pipe_steps():
    step_ms.clear()
    it = pipe.step_through(frame)
    next(it)  # 初始 transition（含 to_transition 成本，计入首步前）
    for s in pipe.steps:
        t1 = time.perf_counter()
        next(it)
        name = f"{type(s).__name__}"
        step_ms[name] = step_ms.get(name, 0.0) + (time.perf_counter() - t1) * 1000.0


for _ in range(N):
    run_pipe_steps()
for k, v in step_ms.items():
    print(f"pipe_{k}_ms={v/N:.2f}")

# pipeline 整体一把（含 to_transition/to_output 包装成本对照）
m, batch = ms_of(lambda: tp.preprocess(frame), N)
print(f"pipe_whole_ms={m:.2f} (steps_sum={sum(step_ms.values())/N:.2f})")

# 3. ids 截断
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS

m, _ = ms_of(
    lambda: batch[OBS_LANGUAGE_TOKENS][0].detach().to(torch.long).cpu().numpy(), N
)
print(f"ids_extract_ms={m:.2f}")

# 4. SigLIP 图像预处理（npu 上 resize/归一化）
m, pair = ms_of(lambda: tp.policy._preprocess_images(batch), N)
imgs, _masks = pair
print(f"preprocess_images_ms={m:.2f} n_views={len(imgs)}")

# 5. cat/float/cpu/unfold
def unfold_part():
    pv = torch.cat([t.detach() for t in imgs], dim=0).float().cpu()
    flat = pv.reshape(-1, 3, pv.shape[-2], pv.shape[-1])
    u = torch.nn.functional.unfold(flat, kernel_size=14, stride=14)
    return u.permute(0, 2, 1).reshape(-1, u.shape[1]).numpy()

m, _ = ms_of(unfold_part, N)
print(f"unfold_ms={m:.2f}")

# 6. noise 生成
m, _ = ms_of(lambda: torch.normal(0.0, 1.0, size=(50, 32)).numpy().astype(np.float32), N)
print(f"noise_ms={m:.2f}")

# 7. postprocess（unnormalize + 回 cpu）
acts0 = np.asarray(rng.normal(size=(50, 7)), dtype=np.float32)


def post_part():
    normalized = torch.from_numpy(acts0)[None].to(tp.device)
    a = tp.postprocess(normalized).detach().cpu().numpy()
    return a

m, _ = ms_of(post_part, N)
print(f"postprocess_ms={m:.2f}")

# 8. 全链 _frame_inputs
m, _ = ms_of(lambda: pol._frame_inputs(obs), N)
print(f"frame_inputs_whole_ms={m:.2f}")

# 9. 真实 infer ×3（锚点：total 与 model 的差 = 上面各项之和 + 装配开销）
print("--- real infer x3 ---")
for i in range(3):
    r = pol.infer(obs)
    t = r["timing"]
    print(
        f"infer[{i}] total_ms={t['total_ms']:.1f} model_ms={t['model_ms']:.1f} "
        f"gap={t['total_ms']-t['model_ms']:.1f} engine={t['engine_ms']}"
    )
print("PROBE_B_DONE")
