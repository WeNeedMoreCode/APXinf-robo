"""Step-by-step rollout divergence hunt: official lerobot eval loop vs our
eval_libero loop, two envs, same init state. Reports the first step where
actions or end-effector pose diverge."""
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
STEPS = 40
REPLAN = 5

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
print("task:", prompt)


def reset_env():
    env = make_env(task, seed=7)
    env.reset()
    obs = env.set_init_state(init0)
    for _ in range(10):
        obs, _, _, _ = env.step([0.0] * 6 + [-1.0])
    return env, obs


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
        "observation.state": libero_state_lerobot(obs)[None],
        "task": [prompt],
    }


def unpost(t):
    return postprocess(t).cpu().numpy().reshape(-1, 7)


# warm compile
env_w, obs_w = reset_env()
with torch.inference_mode():
    policy.select_action(preprocess(proc._process_observation(official_obs_dict(obs_w))))
env_w.close()

# ---- official rollout: select_action every step, queue semantics (n=50) ----
env_a, obs_a = reset_env()
actions_a = []
with torch.inference_mode():
    policy.reset()
    for i in range(STEPS):
        sel = policy.select_action(preprocess(proc._process_observation(official_obs_dict(obs_a))))
        act = unpost(sel)[0]
        obs_a, _, _, _ = env_a.step(act)
        actions_a.append(act)
env_a.close()

# ---- our rollout: predict_action_chunk, replan every REPLAN, apply first REPLAN ----
env_b, obs_b = reset_env()
actions_b = []
plan_b = []
with torch.inference_mode():
    for i in range(STEPS):
        if i % REPLAN == 0:
            chunk = policy.predict_action_chunk(preprocess(our_frame(obs_b)))
            plan_b = unpost(chunk).tolist()
        act = np.asarray(plan_b[i % REPLAN], np.float32)
        obs_b, _, _, _ = env_b.step(act)
        actions_b.append(act)
env_b.close()

a = np.asarray(actions_a); b = np.asarray(actions_b)
diff = np.abs(a - b).max(axis=1)
print("per-step max action diff:", np.round(diff, 4).tolist())
first = int(np.argmax(diff > 0.05)) if (diff > 0.05).any() else -1
print("first divergent step (>0.05):", first)
print("official first actions:\n", np.round(a[:6], 4))
print("ours first actions:\n", np.round(b[:6], 4))
print("ROLLOUT_CMP_DONE")
