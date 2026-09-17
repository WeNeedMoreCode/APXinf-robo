"""Same policy, same frame, same injected noise: official select_action vs
wrapper-style predict_action_chunk + postprocess. If actions agree, the
inference chain is exonerated and the bug lives in the rollout loop."""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np
import torch
import torch_npu
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.pi05 import PI05Policy
from lerobot.processor.env_processor import LiberoProcessorStep

from apxinf_robo.envs.libero import libero_state_lerobot, make_env
from libero.libero import benchmark

torch_npu.npu.set_compile_mode(jit_compile=False)
MODEL = "/data/apxinf/weights/pi05_libero_finetuned"
TOK = "/data/apxinf/weights/paligemma-3b-pt-224"

policy = PI05Policy.from_pretrained(MODEL)
policy.model.gradient_checkpointing_disable()
policy.eval()
preprocess, postprocess = make_pre_post_processors(
    policy.config, MODEL,
    preprocessor_overrides={"device_processor": {"device": "npu"},
                            "tokenizer_processor": {"tokenizer_name": TOK}},
)

suite = benchmark.get_benchmark_dict()["libero_10"]()
task = suite.tasks[0]
env = make_env(task, seed=7)
obs = env.reset()
env.set_init_state(suite.get_task_init_states(0)[0])
for _ in range(10):
    obs, _, _, _ = env.step([0.0] * 6 + [-1.0])

# fixed noise for determinism (padded 32-dim action space)
noise32 = np.zeros((1, 50, 32), np.float32)
noise32[..., :7] = np.random.default_rng(0).standard_normal((1, 50, 7))
noise_t = torch.from_numpy(noise32)

orig_sampler = policy.model.sample_noise
def fixed_noise(shape, device):
    out = torch.zeros(tuple(shape), dtype=torch.float16, device=device)
    out[..., :7] = noise_t[..., :7].to(device=device, dtype=torch.float16)
    return out

# ---- official usage ----
official_obs = {
    "observation.images.image": torch.from_numpy(np.ascontiguousarray(obs["agentview_image"]))[None].permute(0, 3, 1, 2),
    "observation.images.image2": torch.from_numpy(np.ascontiguousarray(obs["robot0_eye_in_hand_image"]))[None].permute(0, 3, 1, 2),
    "observation.robot_state": {
        "eef": {"pos": torch.from_numpy(np.asarray(obs["robot0_eef_pos"], np.float32))[None],
                "quat": torch.from_numpy(np.asarray(obs["robot0_eef_quat"], np.float32))[None],
                "mat": None},
        "gripper": {"qpos": torch.from_numpy(np.asarray(obs["robot0_gripper_qpos"], np.float32))[None],
                    "qvel": None},
        "joints": None,
    },
    "task": [task.language],
}
proc = LiberoProcessorStep()
official_frame = proc._process_observation(official_obs)

with torch.inference_mode():
    # compile warmup on official path (no fixed noise yet)
    policy.select_action(preprocess(dict(official_frame)))
    # official measurement
    policy.model.sample_noise = fixed_noise
    policy.reset()
    sel = policy.select_action(preprocess(dict(official_frame)))
    policy.model.sample_noise = orig_sampler
    official_action = postprocess(sel).cpu().numpy()

# ---- wrapper-style usage ----
wire = {
    "observation/image": obs["agentview_image"],
    "observation/wrist_image": obs["robot0_eye_in_hand_image"],
    "observation/state": libero_state_lerobot(obs),
    "prompt": task.language,
}
frame = {
    "observation.images.image": np.ascontiguousarray(np.asarray(wire["observation/image"])[::-1, ::-1].transpose(2, 0, 1))[None],
    "observation.images.image2": np.ascontiguousarray(np.asarray(wire["observation/wrist_image"])[::-1, ::-1].transpose(2, 0, 1))[None],
    "observation.state": wire["observation/state"][None],
    "task": [wire["prompt"]],
}
with torch.inference_mode():
    policy.model.sample_noise = fixed_noise
    chunk = policy.predict_action_chunk(preprocess(dict(frame)))
    policy.model.sample_noise = orig_sampler
    ours_action = postprocess(chunk).cpu().numpy()

print("official shape:", official_action.shape, "first:", official_action.reshape(-1, 7)[0])
print("ours     shape:", ours_action.shape, "first:", ours_action.reshape(-1, 7)[0])
d = np.abs(official_action.reshape(-1, 7)[0] - ours_action.reshape(-1, 7)[0])
print("per-dim abs diff:", d)
print("max abs diff:", float(d.max()))
print("COMPONENTS_DONE")
