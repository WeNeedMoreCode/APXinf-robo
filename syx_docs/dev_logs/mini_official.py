"""Official-semantics 60-step rollout, log eef trajectory for comparison with
mini_rollout (our semantics). Same env, same init."""
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


def off_obs(o):
    return proc._process_observation({
        "observation.images.image": torch.from_numpy(np.ascontiguousarray(o["agentview_image"]))[None].permute(0, 3, 1, 2),
        "observation.images.image2": torch.from_numpy(np.ascontiguousarray(o["robot0_eye_in_hand_image"]))[None].permute(0, 3, 1, 2),
        "observation.robot_state": {
            "eef": {"pos": torch.from_numpy(np.asarray(o["robot0_eef_pos"], np.float32))[None],
                    "quat": torch.from_numpy(np.asarray(o["robot0_eef_quat"], np.float32))[None],
                    "mat": None},
            "gripper": {"qpos": torch.from_numpy(np.asarray(o["robot0_gripper_qpos"], np.float32))[None],
                        "qvel": None},
            "joints": None,
        },
        "task": [prompt],
    })


env = make_env(task, seed=7)
env.reset()
obs = env.set_init_state(init0)
for _ in range(10):
    obs, _, _, _ = env.step([0.0] * 6 + [-1.0])

with torch.inference_mode():
    policy.reset()
    policy.select_action(preprocess(off_obs(obs)))  # compile warm
    policy.reset()
    for step in range(60):
        sel = policy.select_action(preprocess(off_obs(obs)))
        act = postprocess(sel).cpu().numpy().reshape(-1, 7)[0]
        obs, _, _, _ = env.step(act)
        if step % 5 == 0:
            print("step", step, "act", np.round(act, 3).tolist(),
                  "eef", np.asarray(obs["robot0_eef_pos"]).round(3).tolist(),
                  "grip", np.asarray(obs["robot0_gripper_qpos"]).round(3).tolist(), flush=True)
        if hasattr(env, "check_success") and env.check_success():
            print(f"SUCCESS at {step}")
            break
print("OFFICIAL_MINI_DONE")
