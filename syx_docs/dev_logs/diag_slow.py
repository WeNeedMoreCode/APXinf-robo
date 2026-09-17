"""Isolate the LIBERO-eval slowdown (1378ms/call) vs bench (376ms/call).

Phases (each times policy.infer on chip, N=5, reports median):
  A. synthetic fixed obs, no sim            -> bench condition, expect ~380ms
  B. sim env created + stepped, REAL obs, different state each call
  C. sim env still alive, one REAL obs fixed for all calls
  D. sim env closed, synthetic fixed obs    -> does A's speed come back?

Interpretation:
  A fast, B+C slow, D fast   -> env presence (CPU/GL/NPU contention)
  A fast, B slow, C fast     -> varying state content (prompt recompile?)
  A slow too                 -> machine state changed since bench (contention/clock)
"""
import os
import statistics
import sys
import time

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np

from apxinf_robo import build_robot_policy

PROMPT = "put the black bowl on the stove"


def timed(policy, obs, n=5):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        policy.infer(obs)
        times.append(time.perf_counter() - t0)
    return statistics.median(times) * 1000, times


policy = build_robot_policy(
    "franka_libero", "/data/apxinf/weights/pi05_libero_finetuned",
    engine="npu-torch", precision="fp16",
    tokenizer_dir="/data/apxinf/weights/paligemma-3b-pt-224",
)

rng = np.random.default_rng(0)
synth = {
    "observation/image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
    "observation/wrist_image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
    "observation/state": np.zeros(8, np.float32),
    "prompt": PROMPT,
}

import torch  # noqa: E402

print("== A: synthetic fixed, no sim ==", flush=True)
policy.infer(synth)  # compile/warm
med, _ = timed(policy, synth)
print(f"A median {med:.0f}ms", flush=True)

from libero.libero import benchmark  # noqa: E402
from apxinf_robo.envs.libero import libero_state_lerobot, make_env  # noqa: E402

suite = benchmark.get_benchmark_dict()["libero_10"]()
env = make_env(suite.tasks[0], seed=7)
obs_sim = env.reset()
print("== B: real obs, state varies ==", flush=True)


def real_obs(sim):
    return {
        "observation/image": np.ascontiguousarray(sim["agentview_image"][::-1, ::-1]),
        "observation/wrist_image": np.ascontiguousarray(sim["robot0_eye_in_hand_image"][::-1, ::-1]),
        "observation/state": libero_state_lerobot(sim),
        "prompt": PROMPT,
    }


policy.infer(real_obs(obs_sim))  # warm/compile in env-present condition
b_times = []
for i in range(5):
    obs_sim, _, _, _ = env.step(np.zeros(7, np.float32))
    o = real_obs(obs_sim)
    t0 = time.perf_counter()
    policy.infer(o)
    b_times.append(time.perf_counter() - t0)
print(f"B median {statistics.median(b_times)*1000:.0f}ms times={[round(t*1000) for t in b_times]}", flush=True)

print("== C: real obs fixed ==", flush=True)
fixed_real = o
med, _ = timed(policy, fixed_real)
print(f"C median {med:.0f}ms", flush=True)

env.close()
del env
print("== D: synthetic fixed, sim closed ==", flush=True)
med, _ = timed(policy, synth)
print(f"D median {med:.0f}ms", flush=True)
print("DIAG_DONE", flush=True)
