"""Replay comparison: run the official rollout, record obs; then on the SAME
obs with the SAME injected noise, compare predict_action_chunk (our wrapper's
call) vs a fresh select_action (official call). Isolates call-shape from
environment dynamics."""
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

from apxinf_robo.envs.libero import make_env
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
proc = LiberoProcessorStep()

suite = benchmark.get_benchmark_dict()["libero_object"]()
task = suite.tasks[0]
init0 = suite.get_task_init_states(0)[0]
prompt = task.language


def official_obs_dict(obs):
    return {
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
        "task": [prompt],
    }


def our_frame(obs):
    return {
        "observation.images.image": np.ascontiguousarray(np.asarray(obs["agentview_image"])[::-1, ::-1].transpose(2, 0, 1))[None],
        "observation.images.image2": np.ascontiguousarray(np.asarray(obs["robot0_eye_in_hand_image"])[::-1, ::-1].transpose(2, 0, 1))[None],
        "observation.state": np.concatenate([
            np.asarray(obs["robot0_eef_pos"], np.float32),
            _aa(np.asarray(obs["robot0_eef_quat"], np.float32)),
            np.asarray(obs["robot0_gripper_qpos"], np.float32),
        ])[None],
        "task": [prompt],
    }


def _aa(q):
    q = np.asarray(q, np.float64)
    w = np.clip(q[3], -1.0, 1.0)
    den = np.sqrt(max(0.0, 1.0 - w * w))
    if den < 1e-10:
        return np.zeros(3)
    return (q[:3] / den) * (2.0 * np.arccos(w))


env = make_env(task, seed=7)
env.reset()
obs = env.set_init_state(init0)
for _ in range(10):
    obs, _, _, _ = env.step([0.0] * 6 + [-1.0])

# record 12 obs along the OFFICIAL trajectory (queue semantics)
recorded = []
with torch.inference_mode():
    policy.reset()
    policy.select_action(preprocess(proc._process_observation(official_obs_dict(obs))))  # compile warm
    policy.reset()
    for i in range(24):
        recorded.append(obs)
        sel = policy.select_action(preprocess(proc._process_observation(official_obs_dict(obs))))
        act = postprocess(sel).cpu().numpy().reshape(-1, 7)[0]
        obs, _, _, _ = env.step(act)
env.close()

noise32 = np.zeros((1, 50, 32), np.float32)
noise32[..., :7] = np.random.default_rng(7).standard_normal((1, 50, 7))
noise_t = torch.from_numpy(noise32)


def inject():
    def fixed(shape, device):
        out = torch.zeros(tuple(shape), dtype=torch.float16, device=device)
        out[..., :7] = noise_t[..., :7].to(device=device, dtype=torch.float16)
        return out
    policy.model.sample_noise = fixed


def restore():
    policy.model.sample_noise = PI05Pytorch_sampler


PI05Pytorch_sampler = policy.model.sample_noise

with torch.inference_mode():
    for i, ob in enumerate(recorded[::4]):
        inject()
        chunk = policy.predict_action_chunk(preprocess(our_frame(ob)))
        restore()
        ours = postprocess(chunk).cpu().numpy().reshape(-1, 7)

        inject()
        policy.reset()
        sel = policy.select_action(preprocess(proc._process_observation(official_obs_dict(ob))))
        restore()
        official = postprocess(sel).cpu().numpy().reshape(-1, 7)

        d0 = float(np.abs(ours[0] - official[0]).max())
        print(f"obs {i*4}: first-action max diff = {d0:.4f} | ours[0]={np.round(ours[0],3)} official[0]={np.round(official[0],3)}")
print("REPLAY_DONE")
