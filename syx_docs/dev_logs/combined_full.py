"""Full-length A/B on ONE env: official segment until success (or 200), then
our segment same length from the same init. Prints trajectories."""
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

from apxinf_robo.envs.libero import libero_images, libero_state_lerobot, make_env
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
env = make_env(task, seed=7)


def settle():
    env.reset()
    o = env.set_init_state(init0)
    for _ in range(10):
        o, _, _, _ = env.step([0.0] * 6 + [-1.0])
    return o


def off_batch(o):
    return preprocess(proc._process_observation({
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
    }))


def our_batch(o):
    images = libero_images(o["agentview_image"], o["robot0_eye_in_hand_image"])
    return preprocess({
        "observation.images.image": np.ascontiguousarray(np.asarray(images[0]).transpose(2, 0, 1))[None],
        "observation.images.image2": np.ascontiguousarray(np.asarray(images[1]).transpose(2, 0, 1))[None],
        "observation.state": libero_state_lerobot(o)[None],
        "task": [prompt],
    })


with torch.inference_mode():
    o = settle()
    policy.reset(); policy.select_action(off_batch(o))  # compile warm

    print("== OFFICIAL until success ==", flush=True)
    o = settle()
    policy.reset()
    off_steps = 0
    for s in range(200):
        sel = policy.select_action(off_batch(o))
        act = postprocess(sel).cpu().numpy().reshape(-1, 7)[0]
        o, _, _, _ = env.step(act)
        off_steps += 1
        if s % 20 == 0:
            print(" off", s, "eef", np.asarray(o["robot0_eef_pos"]).round(3).tolist(),
                  "grip", np.asarray(o["robot0_gripper_qpos"]).round(3).tolist(), flush=True)
        if env.check_success():
            print(f"OFFICIAL SUCCESS at {s}", flush=True)
            break

    print("== OURS queue semantics, same length ==", flush=True)
    o = settle()
    for s in range(off_steps):
        sel = policy.select_action(our_batch(o))
        act = postprocess(sel).cpu().numpy().reshape(-1, 7)[0]
        o, _, _, _ = env.step(act)
        if s % 20 == 0:
            print(" our", s, "eef", np.asarray(o["robot0_eef_pos"]).round(3).tolist(),
                  "grip", np.asarray(o["robot0_gripper_qpos"]).round(3).tolist(), flush=True)
        if env.check_success():
            print(f"OURS SUCCESS at {s}", flush=True)
            break
print("AB_DONE")
